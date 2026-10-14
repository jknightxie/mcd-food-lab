"""命令行入口：问一句，给答案。

用法：
    # 交互模式（会真的问出来）
    python scripts/run.py

    # 已经知道场景，直接跑；--store 支持 code 或门店名关键词
    python scripts/run.py --store 建外SOHO --scene discipline
    python scripts/run.py --store 1950564 --answer "今天刚练完，想吃点东西"

    # 输出可分享卡片（四套风格可选）
    python scripts/run.py --store 建外SOHO --scene kid --card out.html --style midnight

    # 所有卡默认就带四风格切换器（顶部按钮点着换肤）；
    # 只想要一张干净的单风格卡（纯分享）才加 --single-style
    python scripts/run.py --store 建外SOHO --scene kid --card out.html
    python scripts/run.py --store 建外SOHO --scene kid --card out.html --single-style

    # 麦门战力测试：3 道实测数据反转题，答完出段位战报卡
    python scripts/run.py --store 建外SOHO --quiz --card report.html

**门店上下文是必传的** —— 实测北上广深四城中，同一个巨无霸的价格
就不同（¥25.5 vs ¥26.5），预置价格表在任何一家店都可能算错。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import card
from card import (  # noqa: E402
    random_style,
    render_card,
    render_quiz_card,
    resolve_style,
    style_options,
)
from fuel_index import (  # noqa: E402
    SCENARIOS,
    build_index,
    build_options,
    build_question,
    render_report,
    resolve_answer,
)
from mcd_client import McdClient, McpError  # noqa: E402
from order import (  # noqa: E402
    format_receipt,
    order_items_payload,
    parse_cancel_response,
    parse_create_response,
    parse_quote,
    resolve_picks,
    summarize_order,
)
from quiz import build_quiz, score_quiz  # noqa: E402


def _parse_choice(reply: str, n: int) -> int | None:
    """解析作答：A-D 或 1-n。听不懂返回 None，按没答算。"""
    r = reply.strip().upper()
    if len(r) == 1 and r in "ABCDEFG"[:n]:
        return "ABCDEFG".index(r)
    if r.isdigit() and 1 <= int(r) <= n:
        return int(r) - 1
    return None


def _run_quiz(
    index, store_name: str, style: str, card_path: str | None, switchable: bool = False
) -> int:
    """麦门战力测试：一题一问，答完出战报卡。

    这里**必须列选项** —— 猜题游戏不给选项就没法猜。
    这是「主流程不许列选项」规则的唯一例外，SKILL.md 里写明了。
    """
    from quiz import rank_for

    quiz = build_quiz(index)
    letters = "ABCDEFG"
    answers: list[int | None] = []
    for no, q in enumerate(quiz, 1):
        print(f"\nQ{no}. {q.text}")
        for i, opt in enumerate(q.options):
            print(f"   {letters[i]}. {opt}")
        try:
            reply = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ABORT] 测试中止")
            return 130
        a = _parse_choice(reply, len(q.options))
        answers.append(a)
        if a is None:
            print("  没听懂，这题按没答算")
        else:
            mark = "✓" if q.is_correct(a) else "✗"
            print(f"  {mark} {q.reveal}")

    score = score_quiz(quiz, answers)
    title, _ = rank_for(score, len(quiz))
    print(f"\n  你是「{title}」，答对 {score}/{len(quiz)}")

    if card_path:
        out = Path(card_path)
        out.write_text(
            render_quiz_card(
                index,
                tuple(answers),
                store_name=store_name,
                project_url="https://github.com/jknightxie/mcd-food-lab",
                style=style,
                switchable=switchable,
            ),
            encoding="utf-8",
        )
        print(f"\n  战报卡已生成：{out}（{card.STYLE_LABELS[style]}）")
    return 0


def _fetch_favorites(client: McdClient) -> list[dict]:
    """读取用户的收藏门店（searchType=1）。

    麦当劳 MCP 本身就知道用户收藏了哪些店 —— 问之前先查这里，
    比让用户打字报位置省事得多。取不到就返回空列表，不报错。
    """
    try:
        result = client.call("query-nearby-stores", beType=1, searchType=1)
    except McpError:
        return []
    if not isinstance(result, list):
        return []
    return [
        {"code": str(s.get("storeCode") or ""), "name": str(s.get("storeName") or "")}
        for s in result
        if isinstance(s, dict) and s.get("storeCode")
    ]


def _search_store(
    client: McdClient, hint: str, city: str | None = None
) -> tuple[str, str] | None:
    """按商圈搜索门店，返回 (code, name)。

    实测约束：`searchType=2` **必须同时传 city + keyword**，
    只传 keyword 会报 600058。`city` 缺省时先拿 keyword 试，
    失败则要求用户补城市。
    """
    if not hint:
        return None
    try:
        result = client.call(
            "query-nearby-stores",
            beType=1,
            searchType=2,
            city=city or hint,
            keyword=hint,
        )
    except McpError:
        if city:
            print(f"[FAIL] 门店搜索失败：没在 {city} 搜到「{hint}」")
            return None
        # 失败时让用户补城市再试
        try:
            raw = input(f"  「{hint}」是哪个城市？> ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(130)
        if not raw:
            return None
        try:
            result = client.call(
                "query-nearby-stores",
                beType=1,
                searchType=2,
                city=raw,
                keyword=hint,
            )
        except McpError as exc:
            print(f"[FAIL] 门店搜索失败：{exc}")
            return None

    if not isinstance(result, list) or not result:
        print(f"  没搜到「{hint}」附近的门店，换个说法试试")
        return None
    first = result[0]
    return str(first.get("storeCode")), str(first.get("storeName") or "")


def _resolve_store(
    client: McdClient, explicit: str | None, city: str | None = None
) -> tuple[str, str]:
    """确定用哪家店，返回 (code, name)。

    顺序：**收藏门店 → 让用户选 → 用户要其他的才搜位置**。

    **卡片和报告里要显示店名，不是 code** —— 读者认识「建外SOHO」，
    不认识「1950564」。所以这里必须把名字一起带回来：
    - 收藏门店：接口直接给 `storeName`
    - 关键词搜索：接口直接给 `storeName`
    - 显式传 code：试收藏反查，查不到就留空（宁可没有名字，不放编号）

    门店必须有 —— 实测同一个巨无霸北上广 ¥25.5、深圳 ¥26.5，
    门店错了结论就是错的。
    """
    if explicit:
        if explicit.isdigit():
            # 是 code：收藏反查店名，查不到就认了
            for s in _fetch_favorites(client):
                if s["code"] == explicit:
                    return explicit, s["name"]
            return explicit, ""
        found = _search_store(client, explicit, city=city)
        return (found[0], found[1]) if found else ("", "")

    favorites = _fetch_favorites(client)
    if favorites:
        print()
        print("你收藏的麦当劳：")
        for i, s in enumerate(favorites, 1):
            print(f"  {i}. {s['name']}（{s['code']}）")
        print("  0. 其他位置")
        print()
        try:
            pick = input("选哪家？（直接回车 = 第 1 家）> ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(130)
        if pick.isdigit() and 1 <= int(pick) <= len(favorites):
            chosen = favorites[int(pick) - 1]
            return chosen["code"], chosen["name"]
        if not pick or pick == "0":
            try:
                hint = input("  说门店名或商圈（如「国贸」「建外SOHO」）> ").strip()
            except (EOFError, KeyboardInterrupt):
                raise SystemExit(130)
            found = _search_store(client, hint)
            return (found[0], found[1]) if found else ("", "")
        found = _search_store(client, pick)
        return (found[0], found[1]) if found else ("", "")

    print()
    print("你在哪家店？（说门店名或商圈，如「国贸」「建外SOHO」）")
    try:
        hint = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(130)
    found = _search_store(client, hint)
    return (found[0], found[1]) if found else ("", "")


def _default_style(scene: str) -> str:
    """没指定风格时按场景权重随机（用户拍板：默认不固定，同场景不重样）。

    权重表在 `card.random_style`（与 SKILL.md 同一份规则）；氛围亲和
    （深夜→黑金、请客→复古、点餐单→小票）保留为权重而非定论。
    """
    return random_style(scene)


def _run_order(
    client: McdClient,
    index,
    store_code: str,
    store_name: str,
    spec: str,
    style: str | None,
    card_path: str | None,
    confirm: bool = False,
    switchable: bool = False,
) -> int:
    """点餐单链路：解析点单 → calculate-price 实时计价 → 点餐单卡。

    **默认到点餐单为止（只读）**。`confirm=True` 才调用 create-order
    真实下单（写操作）——CLI 里对应 `--order-confirm`，对话里对应
    用户的明确二次确认。下单后回传三要素：支付链接 / 订单号 / 取消方式。
    """
    from card import render_order_card

    try:
        picks = resolve_picks(index, spec)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 2

    payload = order_items_payload(picks)
    try:
        raw = client.call(
            "calculate-price",
            storeCode=store_code,
            beType=1,
            orderType=1,
            items=payload,
            reservationDate=_reservation_date(),
        )
    except McpError as exc:
        # 打烊/限流等：退回菜单标价合计，如实标注来路 —— 不估算、不编造
        print(f"[WARN] 实时计价失败（{exc}），按菜单标价合计")
        raw = None

    quote = parse_quote(raw, picks)
    summary = summarize_order(index, picks, quote)

    print("\n点餐单：")
    for line in quote.lines:
        print(f"  {line.quantity}× {line.name}  ¥{line.unit_price * line.quantity:.1f}")
    print(f"  合计 ¥{summary['total']:.1f}（{quote.source}）")
    if summary.get("protein_per_yuan"):
        print(
            f"  这单燃料：{summary['protein']}g 蛋白 · "
            f"每元 {summary['protein_per_yuan']}g"
        )

    # ── 写操作门控：没有明确确认，到点餐单为止 ──
    if not confirm:
        print("\n[只读] 未真实下单。确认无误要下单时，加 --order-confirm（对话里说「确认下单」）。")
    else:
        print("\n[下单] 用户已明确确认 —— 调用 create-order …")
        try:
            raw = client.call(
                "create-order",
                storeCode=store_code,
                beType=1,
                orderType=1,
                items=payload,
                reservationDate=_reservation_date(),
                takeWayCode="take-in-store",
            )
        except McpError as exc:
            print(f"[FAIL] 下单失败：{exc}")
            print("  订单可能没有创建成功；若 App 里出现待支付订单，请手动取消。")
            return 2
        try:
            receipt = parse_create_response(raw)
        except ValueError as exc:
            print(f"[FAIL] {exc}")
            return 2
        print("\n" + format_receipt(receipt))

    if card_path:
        style = style or random_style("order")  # 小票权重最高，但不定死
        out = Path(card_path)
        out.write_text(
            render_order_card(
                index,
                summary,
                store_name=store_name,
                project_url="https://github.com/jknightxie/mcd-food-lab",
                style=style,
                switchable=switchable,
            ),
            encoding="utf-8",
        )
        print(f"\n  点餐单卡已生成：{out}（{card.STYLE_LABELS[style]}）"
          + ("，顶部可切换四套风格" if switchable else ""))
    return 0


def _reservation_date() -> str:
    """算一个**未来**的预约时间。

    非营业时段查询要带 `reservationDate` 才能绕过 600057，但它必须是
    未来时间 —— 曾经硬编码过日期，第二天就全部报 600053。
    规则：当前时间往后推 1 小时，落在营业时段外（8 点前 / 22 点后）
    就顺延到明天中午。
    """
    candidate = datetime.now() + timedelta(hours=1)
    if not (8 <= candidate.hour < 22):
        candidate = (datetime.now() + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
    return candidate.strftime("%Y-%m-%d %H:%M")


def _fetch(store_code: str, client: McdClient):
    """拉取门店菜单与营养库，任一失败都明确报错，不返回半成品。"""
    try:
        menu = client.call(
            "query-meals",
            storeCode=store_code,
            orderType=1,
            beType=1,
            reservationDate=_reservation_date(),
        )
    except McpError as exc:
        raise SystemExit(f"[FAIL] 菜单查询失败：{exc}")
    try:
        nutrition = client.call("list-nutrition-foods")
    except McpError as exc:
        raise SystemExit(f"[FAIL] 营养库查询失败：{exc}")
    return build_index(menu, nutrition)


def main() -> int:
    ap = argparse.ArgumentParser(description="麦门食验室")
    ap.add_argument("--store", help="门店 code 或门店名关键词；省略则先列收藏门店")
    ap.add_argument("--city", help="搜索门店时的城市（searchType=2 必须城市+关键词）")
    ap.add_argument("--scene", choices=[s.key for s in SCENARIOS], help="直接指定场景")
    ap.add_argument("--answer", help="自然语言回答，自动映射场景")
    ap.add_argument("--card", help="输出可分享卡片的 HTML 路径")
    ap.add_argument(
        "--quiz",
        action="store_true",
        help="麦门战力测试：3 道实测数据反转题，答完出段位战报卡",
    )
    ap.add_argument(
        "--order",
        metavar="餐品",
        help="点餐单：如「那么大鸡排x2, 纯牛奶」—— 实时计价后出点餐单卡（不下单）",
    )
    ap.add_argument(
        "--order-confirm",
        action="store_true",
        help="真实下单（写操作！）：在 --order 基础上调用 create-order 并回传支付链接",
    )
    ap.add_argument(
        "--cancel",
        metavar="订单号",
        help="取消指定订单（写操作：cancel-order，原因：改主意）",
    )
    ap.add_argument(
        "--single-style",
        action="store_true",
        help="只要单风格干净卡（纯分享用）；默认所有卡都带四风格切换器",
    )
    ap.add_argument(
        "--style",
        choices=list(card.STYLES),
        default=None,
        help="卡片风格：classic 黄黑 / midnight 黑金 / receipt 小票 / retro 复古；"
        "省略则按场景智能默认，交互模式会问一句",
    )
    args = ap.parse_args()

    client = McdClient()

    if args.cancel:
        # 取消订单也是写操作，但它本身就是「取消」—— 无需再确认
        try:
            rc = client.call(
                "cancel-order", orderId=args.cancel, cancelReasonCode="1"
            )
        except McpError as exc:
            print(f"[FAIL] 取消失败：{exc}")
            return 2
        if parse_cancel_response(rc):
            print(f"订单 {args.cancel} 已取消。")
        else:
            print(f"[FAIL] 取消结果异常：{rc}")
        return 0

    # 1) 场景：命令行参数 > 自然语言 > 交互提问（战力测试/点餐单不需要场景）
    scene = None
    if not args.quiz and not args.order:
        scene = args.scene
        if not scene and args.answer:
            scene = resolve_answer(args.answer)
            if scene is None:
                print(f"[WARN] 无法从「{args.answer}」判断场景。")
                print(f"       {build_options()}")
                print("       也可以用 --scene 直接指定一个。")
                return 2
            print(f"  识别为「{next(s.label for s in SCENARIOS if s.key == scene)}」\n")

        if not scene:
            print()
            print(build_question())
            print()
            for attempt in (1, 2):
                try:
                    reply = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n[ABORT] 已取消")
                    return 130
                if not reply:
                    continue
                scene = resolve_answer(reply)
                if scene is not None:
                    break
                if attempt == 1:
                    print("  没太理解 —— 可以直接说，比如"
                          "「刚练完」「带小孩来」「今天很累」「请朋友吃饭」")
                    print()
                    continue
                print(build_options())
                print()
            if scene is None:
                print("[WARN] 还是没判断出来。用 --scene 直接指定一个场景。")
                return 2
            print(f"  识别为「{next(s.label for s in SCENARIOS if s.key == scene)}」\n")

    # 2) 门店：显式指定 > 收藏门店 > 搜索
    store, store_name = _resolve_store(client, args.store, city=args.city)
    if not store:
        print("[WARN] 没确定门店，无法继续 —— 门店不同，菜单和价格都不同。")
        return 2

    # 3) 算 + 呈现
    index = _fetch(store, client)

    if args.quiz:
        # 战力测试：风格只有显式或智能默认（无场景，按测试氛围走黑金）
        style = args.style or random_style("quiz")
        return _run_quiz(index, store_name, style, args.card, not args.single_style)

    if args.order:
        return _run_order(
            client,
            index,
            store,
            store_name,
            args.order,
            args.style,
            args.card,
            confirm=args.order_confirm,
            switchable=not args.single_style,
        )

    print(render_report(index, scene))

    if args.card:
        # 风格：显式 > 场景智能默认 > 交互问一句（EOF 直接落默认，脚本不断）
        style = args.style or _default_style(scene)
        if args.style is None and sys.stdin.isatty():
            print(f"\n卡片风格？（直接回车 = {card.STYLE_LABELS[style]}；{style_options()}）")
            try:
                reply = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                reply = ""
            if resolve_style(reply):
                style = resolve_style(reply)
            elif reply:
                print(f"  没听懂风格，用默认的 {card.STYLE_LABELS[style]}")
        out = Path(args.card)
        out.write_text(
            render_card(
                index,
                scene,
                store_name=store_name,
                project_url="https://github.com/jknightxie/mcd-food-lab",
                style=style,
                switchable=not args.single_style,
            ),
            encoding="utf-8",
        )
        print(f"\n  卡片已生成：{out}（{card.STYLE_LABELS[style]}）"
          + ("，顶部可切换四套风格" if not args.single_style else ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())