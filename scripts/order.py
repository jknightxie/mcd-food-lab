"""点餐单 —— 把「推荐」变成「能直接拿去点的东西」。

链路闭环的最后一块：玩游戏（战力测试）→ 选想吃的（场景推荐）→ 定餐（本模块）。

**分层与边界（这是本模块最重要的设计）**：

    calculate-price  = 只读计价，随便调 —— 输出「点餐单」
    create-order     = 真实写操作，会产生待支付订单 —— 默认绝不调用

定餐这一步只做到「实时计价 + 点餐单」，不自动下单：真实下单属于写操作，
必须用户明确二次确认后才碰一次，且支付永远在官方 App 完成（MCP 无支付能力）。
宁可少做一步，不碰真实交易。

实测踩坑（2026-10-13，门店 1950564）：

- calculate-price 同样有营业时间限制，打烊报 `60003 门店暂停营业`，
  必须带 `reservationDate`（与 query-meals 同款逃生口）
- 价格单位是**分**（3500 = ¥35.0），响应里 `productList[].subtotal`
  是逐项小计，`price` 是应付合计
- 到店自取（beType=1, orderType=1）不传 beCode

数字纪律不变：计价失败就明说「按菜单标价合计」，绝不用估算价冒充接口价。

**create-order 实测（2026-10-13，真实下单后立即取消）**：

- 响应三要素：`orderId` / `payH5Url`（支付链接）/ `orderDetail`
- `orderDetail.orderStatus` = 待支付，`expirePayTime` = **15 分钟**支付时限
- 到店自取同样不需要 beCode/addressId；`takeWayCode` 来自 calculate-price
  的 `takeWayList`（eat-in 堂食 / take-in-store 外带）
- 取消：`cancel-order(orderId, cancelReasonCode=1)`，实测返回 `cancelResult: true`
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from fuel_index import FuelIndex, FuelItem

__all__ = [
    "OrderLine",
    "OrderQuote",
    "OrderReceipt",
    "resolve_picks",
    "parse_quote",
    "summarize_order",
    "parse_create_response",
    "order_items_payload",
    "parse_cancel_response",
]

# 支付链接域名白名单 —— MCP 若被劫持，可能回钓鱼链接。
# 域名不对的支付链接照常解析，但标记为不可信，回传时显著警告。
_PAY_URL_HOSTS = ("m.mcd.cn", "www.mcd.cn", "mcd.cn")


def _pay_url_trusted(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _PAY_URL_HOSTS

# 数量写法：名称末尾的 x2 / ×2 / *2
_QTY_SUFFIX = re.compile(r"\s*[x×*]\s*(\d+)\s*$")


@dataclass(frozen=True)
class OrderLine:
    """点餐单的一行。"""

    name: str
    quantity: int
    unit_price: float  # 菜单单价（元）
    code: str = ""


@dataclass(frozen=True)
class OrderQuote:
    """一次计价结果。

    `source` 说明合计价的来路：
      'calculate-price' = 接口实时算价（含门店促销）
      'menu-price'      = 接口失败，退回菜单标价合计（必须如实标注）
    """

    lines: tuple[OrderLine, ...]
    total: float
    discount: float | None
    source: str
    note: str = ""


def resolve_picks(index: FuelIndex, spec: str) -> list[tuple[FuelItem, int]]:
    """解析点单文本，返回 (餐品, 数量) 列表。

    语法：`那么大鸡排x2, 纯牛奶` —— 顿号/逗号分隔，数量用 x/×/* 后缀。
    匹配顺序：精确同名 → 子串包含。匹配到多个候选时报错并列出，
    **绝不猜** —— 点错餐比推荐错严重得多。
    """
    if not spec or not spec.strip():
        raise ValueError("点单是空的")
    picks: list[tuple[FuelItem, int]] = []
    seen_names: set[str] = set()
    for raw in re.split(r"[、,，;；\n]", spec):
        token = raw.strip()
        if not token:
            continue
        qty = 1
        m = _QTY_SUFFIX.search(token)
        if m:
            qty = max(1, int(m.group(1)))
            token = token[: m.start()].strip()
        if not token:
            raise ValueError(f"「{raw.strip()}」里没写餐品名")
        exact = [i for i in index.items if i.name == token]
        if len(exact) == 1:
            picked = exact[0]
        else:
            fuzzy = [i for i in index.items if token in i.name or i.name in token]
            if len(fuzzy) > 1:
                names = "、".join(i.name for i in fuzzy[:5])
                raise ValueError(
                    f"「{token}」匹配到多款：{names} —— 说清楚点哪款"
                )
            if not fuzzy:
                raise ValueError(f"这家店没有「{token}」，看看推荐列表里的名字")
            picked = fuzzy[0]
        if picked.name in seen_names:
            # 同款重复出现 → 合并数量
            picks = [
                (item, quantity + qty if item.name == picked.name else quantity)
                for item, quantity in picks
            ]
        else:
            picks.append((picked, qty))
            seen_names.add(picked.name)
    return picks


def parse_quote(raw: object, picks: list[tuple[FuelItem, int]]) -> OrderQuote:
    """解析 calculate-price 响应。价格单位是分。

    逐行小计以**接口**为准；接口给不出时退回菜单单价合计，
    并把来路如实写进 source —— 绝不冒充。
    """
    if not isinstance(raw, dict) or not raw.get("productList"):
        total_menu = sum(i.price * q for i, q in picks)
        return OrderQuote(
            lines=tuple(
                OrderLine(name=i.name, quantity=q, unit_price=i.price, code=i.code)
                for i, q in picks
            ),
            total=round(total_menu, 1),
            discount=None,
            source="menu-price",
            note="实时计价没成功 —— 合计按菜单标价算，促销以门店为准。",
        )

    lines: list[OrderLine] = []
    for p in raw["productList"]:
        if not isinstance(p, dict):
            continue
        raw_qty = p.get("quantity")
        if raw_qty is None:
            qty = 1
        else:
            try:
                qty = int(raw_qty)
            except (TypeError, ValueError):
                continue  # 数量不是数字的行丢弃 —— 不猜
        if qty <= 0:
            continue  # quantity=0 会让除法爆炸，也说明这行数据不可信
        try:
            subtotal = float(p.get("subtotal") or 0)
        except (TypeError, ValueError):
            continue
        lines.append(
            OrderLine(
                name=str(p.get("productName", "")),
                quantity=qty,
                unit_price=round(subtotal / qty / 100, 1),
                code=str(p.get("productCode", "")),
            )
        )
    if not lines:
        # 接口响应全是脏行 → 等同于计价失败，退回菜单标价
        return parse_quote(None, picks)
    try:
        total = float(raw.get("price") or 0)
        discount_raw = raw.get("discount")
        discount = None if discount_raw is None else float(discount_raw)
    except (TypeError, ValueError):
        total, discount = 0.0, None
    return OrderQuote(
        lines=tuple(lines),
        total=round(total / 100, 1),
        discount=None if discount is None else round(discount / 100, 1),
        source="calculate-price",
    )


def summarize_order(
    index: FuelIndex, picks: list[tuple[FuelItem, int]], quote: OrderQuote
) -> dict[str, object]:
    """这一单的燃料总结 —— 每元效率从单品推广到整单。

    「这单 ¥35 买到 58g 蛋白」是把核心卖点带进点餐环节的最后一口气。
    所有数字来自已匹配营养库 + 实际数量，None 字段如实缺席。
    """
    total_protein = 0.0
    total_kcal = 0.0
    has_protein = has_kcal = False
    for item, qty in picks:
        if item.protein is not None:
            total_protein += item.protein * qty
            has_protein = True
        if item.kcal is not None:
            total_kcal += item.kcal * qty
            has_kcal = True
    result: dict[str, object] = {
        "lines": quote.lines,
        "total": quote.total,
        "source": quote.source,
        "note": quote.note,
    }
    if has_protein and quote.total:
        result["protein"] = round(total_protein, 1)
        result["protein_per_yuan"] = round(total_protein / quote.total, 2)
    if has_kcal and quote.total:
        result["kcal"] = round(total_kcal)
    return result


# ── 真实下单（写操作，必须门控）────────────────────────────────────────

@dataclass(frozen=True)
class OrderReceipt:
    """create-order 的回执 —— 回传给用户的三要素都在这里。

    支付链接是**私人**的（绑定这笔订单），只回给用户本人，
    绝不放进可分享卡片。
    """

    order_id: str
    pay_url: str
    pay_url_trusted: bool  # 域名在官方白名单内才为 True
    status: str  # 实测为「待支付」
    store_name: str
    total: float
    expire_pay_time: str
    take_way: str
    lines: tuple[str, ...]  # 「1× 那么大鸡排（椒盐风味） ¥14.0」


def order_items_payload(picks: list[tuple[FuelItem, int]]) -> list[dict]:
    """把点单转成 calculate-price / create-order 共用的 items 参数。"""
    return [{"productCode": item.code, "quantity": qty} for item, qty in picks]


def parse_create_response(raw: object) -> OrderReceipt:
    """解析 create-order 响应（2026-10-13 真实下单实测的结构）。

    解析不到订单号时抛 ValueError —— 一笔「不知道订单号」的真实订单
    比报错危险得多：用户连取消都做不到。
    """
    if not isinstance(raw, dict):
        raise ValueError("create-order 响应不是 JSON 对象，无法解析")
    order_id = str(raw.get("orderId") or "")
    if not order_id:
        raise ValueError("create-order 响应里没有 orderId —— 状态未知，绝不当作没发生")
    detail = raw.get("orderDetail") if isinstance(raw.get("orderDetail"), dict) else {}
    lines = []
    for p in detail.get("orderProductList") or []:
        try:
            price = float(p.get("price", 0))
        except (TypeError, ValueError):
            price = 0.0
        lines.append(f"{p.get('quantity', 1)}× {p.get('productName', '')} ¥{price:.1f}")
    try:
        total = float(detail.get("realTotalAmount") or detail.get("totalAmount") or 0)
    except (TypeError, ValueError):
        total = 0.0
    pay_url = str(raw.get("payH5Url") or "")
    return OrderReceipt(
        order_id=order_id,
        pay_url=pay_url,
        pay_url_trusted=_pay_url_trusted(pay_url) if pay_url else False,
        status=str(detail.get("orderStatus") or "待支付"),
        store_name=str(detail.get("storeName") or ""),
        total=total,
        expire_pay_time=str(detail.get("expirePayTime") or ""),
        take_way=str(detail.get("takeWay") or ""),
        lines=tuple(lines),
    )


def parse_cancel_response(raw: object) -> bool:
    """解析 cancel-order 响应。实测结构：{"cancelResult": true, "orderId": "..."}。"""
    if isinstance(raw, dict):
        return bool(raw.get("cancelResult"))
    return False


def format_receipt(receipt: OrderReceipt) -> str:
    """回传给用户的标准文本：支付链接 + 订单号 + 取消方式，一个不少。

    支付链接域名不在官方白名单时，明确警告钓鱼风险 —— 链接可以展示，
    但必须让用户知道「这不是官方域名的链接」。
    """
    pay_block = receipt.pay_url
    if receipt.pay_url and not receipt.pay_url_trusted:
        pay_block = (
            f"⚠ 支付链接域名异常（非官方 mcd.cn 域），疑似钓鱼，"
            f"请勿在该页面输入任何账号信息！\n请到麦当劳官方 App 核对本单后再付款。\n"
            f"原始链接：{receipt.pay_url}"
        )
    lines = [
        f"订单已创建（{receipt.status}）",
        f"门店：{receipt.store_name}" if receipt.store_name else "",
        *receipt.lines,
        f"应付：¥{receipt.total:.1f}（{receipt.take_way}）" if receipt.total else "",
        f"支付（{receipt.expire_pay_time} 前有效）：" if receipt.expire_pay_time else "支付：",
        pay_block,
        f"订单号：{receipt.order_id}",
        "不想吃了？随时说「取消订单」，我用 cancel-order 帮你退掉。",
    ]
    return "\n".join(l for l in lines if l)
