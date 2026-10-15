#!/usr/bin/env python3
"""构建在线演示页：`demo/index.html`（快照驱动，运行时零网络、零 Token）。

**为什么要有这个页面**：README 的截图会随卡片设计变更而过期，而静态图也演示不了
「交互」这件事。这个页面把 2026-10-14 在门店 1950564 抓到的真实响应冻结在
`assets/snapshot.json` 里，然后用**仓库里同一套 scripts** 现渲所有卡片 ——
访客能亲手答反转题、切换六个场景看推荐卡怎么变，而全程不碰 MCP。

卡片**不在这个脚本里重新实现**：战报卡（每套题库 8 种作答组合）、6 张场景卡、
3 张点餐单，全部调用 `card.py` 的真实渲染函数产出，再以 iframe srcdoc 嵌进演示页。
（`card.build_quiz` 会被临时打桩成冻结题库，保证「页面上出的题」=「战报卡上的题」。）

**每次打开不一样**：页内预置多套冻结题库、六个场景、三张真实计价点餐单，
打开时随机各选一份 —— 刷新就换一套题 / 换一个默认场景 / 换一单。
之所以预置而不是"当场随机生成"，是因为页面必须**冻结**（运行时不碰 MCP），
随机只能发生在"展示哪一份真实快照"这一层，数字永远来自实测。

**卡片 CSS 共享一份**：20+ 张卡每张都内嵌一份完全相同的 CSS（基础 + 四套主题），
不去重就是几百 KB 纯重复 —— 构建时抽出共享、运行时展开（不一致会直接报错）。

用法：
    python tools/build_demo.py            # 生成 demo/index.html
"""

from __future__ import annotations

import json
import random
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import card  # noqa: E402
import quiz as quiz_mod  # noqa: E402
from fuel_index import SCENARIOS, build_index  # noqa: E402
from order import parse_quote, resolve_picks, summarize_order  # noqa: E402

SNAPSHOT = ROOT / "assets/snapshot.json"
OUT = ROOT / "demo/index.html"

# 预置题库的种子：每个种子 = 一套题（换它 = 换一套题，但页内永远自洽）
QUIZ_SEEDS = (42, 7, 2026, 111)
# 点餐单候选（与 `snapshot["order_specs"]` 对齐，价格全部来自真实 calculate-price）
ORDER_SPECS = ("鸡排x1, 牛奶x2", "板烧鸡腿堡x1", "双层吉士汉堡x2")

# 共享 CSS 的占位标记。刻意不用 HTML 注释（`<!--`）—— 它出现在 <script> 里会
# 把 HTML 解析器带进 "script data escaped" 状态，是另一个坑；纯文本标记最安全。
CARD_CSS_SENTINEL = "__SHARED_CARD_CSS__"


def _dedupe_card_css(cards: dict[str, str]) -> tuple[dict[str, str], str]:
    """把每张卡里那份**完全相同**的 `<style>` 抽出来，全页共享一份。

    页内 20+ 张卡每张都带完整卡片 CSS（基础 + 四套主题，约 14KB）——
    不去重就是几百 KB 的纯重复。不一致时直接报错：共享的前提是它们真的相同，
    悄悄让某张卡掉样式比构建失败糟糕得多。
    """
    shared: str | None = None
    out: dict[str, str] = {}
    for key, html in cards.items():
        m = re.search(r"<style>(.*?)</style>", html, re.S)
        if m is None:
            raise SystemExit(f"[FAIL] {key} 里没有 <style>，无法共享 CSS")
        found = m.group(1)
        if shared is None:
            shared = found
        elif found != shared:
            raise SystemExit(f"[FAIL] {key} 的 CSS 与其他卡不一致，共享会改变样式")
        out[key] = html[: m.start()] + CARD_CSS_SENTINEL + html[m.end() :]
    return out, (shared or "")


def build_quiz_cards(index, frozen, store_name: str) -> dict[str, str]:
    """8 种「对/错」组合的战报卡（真实渲染），错项的「你答了 X」留占位符。"""
    n = len(frozen)
    cards: dict[str, str] = {}
    for bits in range(1 << n):
        answers: list[int] = []
        placeholders: list[tuple[int, str]] = []
        for qi, q in enumerate(frozen):
            right = bool(bits & (1 << qi))
            if right:
                answers.append(q.correct)
            else:
                wrong = next(i for i in range(len(q.options)) if i != q.correct)
                answers.append(wrong)
                placeholders.append((qi, q.options[wrong]))
        html = card.render_quiz_card(
            index, tuple(answers), store_name=store_name, style="classic"
        )
        for qi, opt in placeholders:
            html = html.replace(
                f'<span class="miss">{escape(opt)}</span>',
                f'<span class="miss">{{{{Q{qi}}}}}</span>',
            )
        cards[str(bits)] = html
    return cards


def main() -> int:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    index = build_index(snapshot["menu"], snapshot["nutrition"])
    store_name = snapshot["store"]["name"]

    # ── 多套冻结题库（每套：题目 + 8 版战报卡，页内自洽）──
    quiz_sets = []
    n_questions = None
    for seed in QUIZ_SEEDS:
        frozen = quiz_mod.build_quiz(index, rng=random.Random(seed))
        if not frozen:
            raise SystemExit(f"[FAIL] 种子 {seed} 的题库为空，快照可能不完整")
        if n_questions is None:
            n_questions = len(frozen)
        elif len(frozen) != n_questions:
            # 段位表按「答对几题」查，各套题数必须一致，否则段位会串
            raise SystemExit(
                f"[FAIL] 种子 {seed} 出题 {len(frozen)} 道，与其他套"
                f"（{n_questions} 道）不一致，段位表无法共用"
            )
        card.build_quiz = lambda index, rng=None, _f=frozen: _f  # 打桩：仅本进程内有效
        quiz_sets.append(
            {
                "seed": seed,
                "questions": [
                    {
                        "text": q.text,
                        "options": list(q.options),
                        "correct": q.correct,
                        "reveal": q.reveal,
                    }
                    for q in frozen
                ],
                "cards": build_quiz_cards(index, frozen, store_name),
            }
        )

    ranks = {
        str(score): list(quiz_mod.rank_for(score, n_questions))
        for score in range(n_questions + 1)
    }

    scene_cards = {
        s.key: card.render_card(index, s.key, store_name=store_name, style="classic")
        for s in SCENARIOS
    }
    scene_labels = {s.key: s.label for s in SCENARIOS}

    # ── 点餐单：走生产同一条链路（resolve_picks → parse_quote → summarize_order）──
    quotes = snapshot.get("quotes") or {}
    order_cards = []
    for spec in ORDER_SPECS:
        picks = resolve_picks(index, spec)
        raw = quotes.get(spec, snapshot.get("quote"))
        quote = parse_quote(raw, picks)
        summary = summarize_order(index, picks, quote)
        order_cards.append(
            {
                "spec": spec,
                "total": summary["total"],
                "source": summary["source"],
                "card": card.render_order_card(
                    index, summary, store_name=store_name, style="receipt"
                ),
            }
        )

    # ── CSS 共享：20+ 张卡只留一份 ──
    all_cards: dict[str, str] = {}
    for i, s in enumerate(quiz_sets):
        for bits, html in s["cards"].items():
            all_cards[f"quiz{i}-{bits}"] = html
    for key, html in scene_cards.items():
        all_cards[f"scene-{key}"] = html
    for i, o in enumerate(order_cards):
        all_cards[f"order{i}"] = o["card"]
    slim, shared_css = _dedupe_card_css(all_cards)

    for i, s in enumerate(quiz_sets):
        s["cards"] = {bits: slim[f"quiz{i}-{bits}"] for bits in s["cards"]}
    scene_cards = {k: slim[f"scene-{k}"] for k in scene_cards}
    for i, o in enumerate(order_cards):
        o["card"] = slim[f"order{i}"]

    payload = {
        "capturedAt": snapshot["captured_at"],
        "store": snapshot["store"],
        "coverage": {
            "total": index.menu_total,
            "matched": index.matched,
            "percent": round(index.coverage),
        },
        "cardCss": shared_css,
        "styles": list(card.STYLES),
        "styleLabels": dict(card.STYLE_LABELS),
        "quizSets": quiz_sets,
        "ranks": ranks,
        "sceneCards": scene_cards,
        "sceneLabels": scene_labels,
        "sceneOrder": [s.key for s in SCENARIOS],
        "orderCards": order_cards,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(_page(payload), encoding="utf-8")

    # 顺带产出三张**独立**示例卡（README 里 `assets/demo-*.html` 指的就是它们）。
    # 取的是去重前、带完整 CSS 的原版卡；全对那版战报卡没有 `{{Qn}}` 占位符，
    # 所以正好可以当单文件示例。示例卡与演示页同源同一次渲染 ——
    # 以前它们是手工复制的，卡片一改就过期（真发生过），现在每次构建自动跟上。
    SAMPLES = (
        ("assets/demo-quiz.html", f"quiz0-{(1 << n_questions) - 1}"),  # 全对 → 战神卡
        ("assets/demo-recommend.html", "scene-training"),
        ("assets/demo-order.html", "order0"),
    )
    sample_note = []
    for rel, key in SAMPLES:
        html = all_cards.get(key)
        if html is None:
            raise SystemExit(f"[FAIL] 示例卡 {rel} 找不到源卡 {key}")
        target = ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        sample_note.append(f"{target.name} {round(target.stat().st_size / 1024)}KB")

    size = OUT.stat().st_size
    cards_total = len(all_cards)
    print(f"[OK] {OUT.relative_to(ROOT)}  {round(size / 1024)} KB")
    print(f"     题库 {len(quiz_sets)} 套（种子 {', '.join(map(str, QUIZ_SEEDS))}）· "
          f"每套 {n_questions} 题 · 战报卡 {len(quiz_sets) * (1 << n_questions)} 版 · "
          f"场景卡 {len(scene_cards)} 张 · 点餐单 {len(order_cards)} 单")
    print(f"     卡片共 {cards_total} 张，CSS 共享 {round(len(shared_css) / 1024)} KB"
          f"（不去重约多 {round(cards_total * len(shared_css) / 1024)} KB）")
    print(f"     示例卡：{' · '.join(sample_note)}")
    return 0


def _page(data: dict) -> str:
    # 卡片 HTML 里自带 <script>（风格切换器）——原样嵌进页面的 <script> 里，
    # 里面的 </script> 会把页面脚本提前截断（真踩过的坑）。把 < 全部转成
    # \u003c 后，JSON 仍是合法 JS 字符串，但不会再出现 </script> 序列。
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦门食验室 · 在线演示（免安装 · 免 Token）</title>
<!-- 社交分享卡片。og:image 走的是 meta 标签而不是 img 元素 —— 因此不碰
     「演示页零外链图片」那条门禁（见 tests/test_demo.py::test_no_img_tags，
     它是朴素子串匹配，所以这段注释本身也不能出现那三个字符）。
     og.png 由 assets/og-card.svg 经 tools/render_assets.py 光栅化而来：
     源是 SVG、产物是 PNG。URL 必须写绝对地址，所以固定成 Pages 域名。 -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://jknightxie.github.io/mcd-food-lab/">
<meta property="og:title" content="麦门食验室 · 在线演示（免安装 · 免 Token）">
<meta property="og:description" content="把麦当劳官方营养数据除以门店实时价格，回答「这钱花得值不值」。四城七店实测：营养库与在售餐品的可匹配比例 18%~21%，查不到的一律不推荐、也不用估算值凑数。">
<meta property="og:image" content="https://jknightxie.github.io/mcd-food-lab/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="麦门食验室 · 营养 ÷ 价格">
<meta name="twitter:description" content="麦当劳 MCP 的每元营养效率助手。四城七店实测，营养库可匹配比例 18%~21%。">
<meta name="twitter:image" content="https://jknightxie.github.io/mcd-food-lab/og.png">
<style>
:root {{
  --ink:#1a1a1a; --red:#da291c; --yellow:#ffc72c; --cream:#f4eee1;
  --paper:#fff; --tan:#6f6552;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--cream); color:var(--ink); line-height:1.6;
  font-family:"PingFang SC","Microsoft YaHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  padding:26px 14px 40px; -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:520px; margin:0 auto; }}
header {{ text-align:center; margin-bottom:18px; }}
.brandbar {{
  display:inline-flex; align-items:center; gap:8px;
  background:var(--red); color:#fff; border:3px solid var(--ink);
  border-radius:14px; padding:7px 14px; font-weight:900; box-shadow:4px 4px 0 var(--ink);
}}
.m {{ background:var(--yellow); color:var(--ink); border-radius:6px;
      width:22px; height:22px; display:grid; place-items:center;
      font-family:Georgia,serif; font-style:italic; }}
h1 {{ font-size:21px; margin:14px 0 6px; }}
.sub {{ font-size:12px; color:var(--tan); }}
.sub b {{ color:var(--ink); }}
.tabs {{ display:flex; gap:6px; justify-content:center; margin:16px 0 14px; flex-wrap:wrap; }}
.tabs button, .scenes button {{
  font-family:inherit; cursor:pointer; border:2px solid var(--ink);
  background:var(--paper); color:var(--ink); border-radius:999px;
  padding:6px 13px; font-size:13px; font-weight:800; box-shadow:2px 2px 0 var(--ink);
}}
.tabs button.on, .scenes button.on {{ background:var(--ink); color:var(--yellow); }}
.panel {{ display:none; }}
.panel.on {{ display:block; }}
.qbox {{ background:var(--paper); border:3px solid var(--ink); border-radius:16px;
         padding:16px; box-shadow:6px 6px 0 var(--ink); }}
.qmeta {{ font-size:11px; font-weight:800; color:var(--tan); letter-spacing:.06em; }}
/* white-space:pre-wrap 必须 —— 日志体（时间列）和公文体（问：/答：逐行）的排版全靠换行。
   题面字重必须与选项、与页面其他文字**完全一致**（都 700）。
   曾经在这里做过"铺垫常规 / 问句加粗"的分级，用户直接指着说「这里的字体和别的不一致」——
   那是题面 150 字时代的权宜之计；题面压到 60 字后分级已无必要，反而破坏统一。
   空白行仍然把铺垫和问句分开（pre-wrap 保留换行），层次靠留白，不靠字重。 */
.qtext {{ font-size:14px; font-weight:700; margin:8px 0 13px;
          white-space:pre-wrap; line-height:1.75; }}
/* .q-ask 保留为钩子：若将来想用**颜色**（而非字重）做层次，改这里即可 —— 字重别再动。 */
.qtext .q-ask {{ }}
.opts {{ display:grid; gap:8px; }}
.opts button {{
  font-family:inherit; cursor:pointer; text-align:left;
  border:2px solid var(--ink); background:var(--paper); color:var(--ink);
  border-radius:10px; padding:10px 12px; font-size:14px; font-weight:700;
}}
.opts button:hover:not(:disabled) {{ background:#fff7de; }}
.opts button:disabled {{ cursor:default; opacity:.55; }}
.opts button.pick-right {{ background:#e8f6e9; border-color:#1a7f37; opacity:1; }}
.opts button.pick-wrong {{ background:#fdecea; border-color:var(--red); opacity:1; }}
.verdict {{ margin-top:13px; font-size:13.5px; font-weight:800; }}
.verdict.ok {{ color:#1a7f37; }}
.verdict.no {{ color:var(--red); }}
.reveal {{ margin-top:7px; font-size:12.5px; font-weight:600; color:#3d3a33; }}
.nextbtn {{
  margin-top:14px; font-family:inherit; cursor:pointer; width:100%;
  border:2px solid var(--ink); background:var(--yellow); color:var(--ink);
  border-radius:10px; padding:10px; font-size:14px; font-weight:900;
  box-shadow:3px 3px 0 var(--ink);
}}
.final {{ text-align:center; margin-bottom:12px; }}
.final .rank {{ font-size:26px; font-weight:900; }}
.final .note {{ font-size:12px; color:var(--tan); font-weight:700; }}
.scenes {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:center; margin-bottom:12px; }}
iframe {{ width:100%; border:0; display:block; }}
.cardholder {{ margin-top:4px; }}
.hint {{ font-size:11.5px; color:var(--tan); text-align:center; margin-top:10px; }}
footer {{ margin-top:22px; text-align:center; font-size:11px; color:var(--tan); line-height:1.8; }}
footer a {{ color:var(--ink); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brandbar"><span class="m">M</span> 麦门食验室 · 在线演示</div>
    <h1>免安装、免 Token，直接玩</h1>
    <p class="sub">
      {data["capturedAt"]} 在门店「{escape(data["store"]["name"].replace("麦当劳", "").replace("餐厅", ""))}」用真实 Token 跑通的
      <b>快照</b>（{data["coverage"]["total"]} 款在售 · 营养库覆盖 {data["coverage"]["matched"]} 款，
      即 {data["coverage"]["percent"]}%），<b>不是实时查询</b>。三个玩法每次打开<b>随机换一份</b>。
    </p>
  </header>

  <nav class="tabs" id="tabs">
    <button data-tab="quiz" class="on">① 考考我</button>
    <button data-tab="scenes">② 六个场景</button>
    <button data-tab="order">③ 点餐单</button>
  </nav>

  <section class="panel on" id="panel-quiz">
    <div class="qbox" id="qbox"></div>
    <div class="final" id="final" hidden>
      <div class="rank" id="rankTitle"></div>
      <div class="note" id="rankNote"></div>
    </div>
    <div class="cardholder" id="quizCardBox" hidden>
      <iframe id="quizCard" title="战报卡" height="1200"></iframe>
    </div>
    <p class="hint" id="quizHint"></p>
  </section>

  <section class="panel" id="panel-scenes">
    <div class="scenes" id="scenes"></div>
    <div class="cardholder"><iframe id="sceneCard" title="推荐卡" height="1200"></iframe></div>
    <p class="hint" id="sceneHint"></p>
  </section>

  <section class="panel" id="panel-order">
    <div class="cardholder"><iframe id="orderCard" title="点餐单卡" height="1000"></iframe></div>
    <p class="hint" id="orderHint"></p>
  </section>

  <footer>
    麦门食验室 · 本项目为参赛作品，非麦当劳官方产品。数据以麦当劳官方渠道实时结果为准。<br>
    开源地址：<a href="https://github.com/jknightxie/mcd-food-lab">https://github.com/jknightxie/mcd-food-lab</a>
  </footer>
</div>

<script>
const DATA = {blob};
const CSS_SLOT = "{CARD_CSS_SENTINEL}";

/* ── 每次打开随机一份：一套题 / 一个默认场景 / 一单点餐单 ──
   页面是冻结快照（运行时不碰 MCP），所以"随机"只决定**展示哪一份真实数据**：
   数字永远来自实测，随机的只是这次先给你看哪一面。刷新即换。 */
function pickOne(list) {{ return list[Math.floor(Math.random() * list.length)]; }}
const SET = pickOne(DATA.quizSets);
const START_SCENE = pickOne(DATA.sceneOrder);
const ORDER = pickOne(DATA.orderCards);
const THEME = pickOne(DATA.styles);   // 本次主题：四种随机一种（卡片顶部仍可随时换）

/* ── 卡片：srcdoc 直接灌入 card.py 的真实渲染结果 ──
   两个坑（真踩过）：
   1. 面板初始 display:none —— 隐藏容器里的 iframe 量不到高度（body.scrollHeight≈0），
      直接写进 style.height 会把卡片压成 0px，切过去就是一片空白。
      量到可疑高度就**跳过**，保留 HTML 上的默认 height，等可见时再补量。
   2. 量高度不能读根元素的 scrollHeight —— 它被 iframe **自身**高度撑大
      （卡 774px 高、iframe 1000px 时它报 1000，永远「量不准」）。
      要读 body 的 scrollHeight（只反映内容，与视口无关）。
   补量用三保险：ResizeObserver（卡内变高）+ 切页签时补量 + 低速定时兜底。 */
function fit(frame) {{
  try {{
    const d = frame.contentDocument;
    if (!d || !d.body) return;
    const h = d.body.scrollHeight || 0;
    if (!h || h < 60) return;               // 隐藏中量不到：不覆盖默认高度
    const want = h + 12;                    // + 卡片 9px 硬阴影的外溢余量
    if (frame.dataset.fit !== String(want)) {{
      frame.dataset.fit = String(want);
      frame.style.height = want + "px";
    }}
  }} catch (e) {{ /* 读不到就保留默认高度 */ }}
}}
function watch(frame) {{
  try {{
    const d = frame.contentDocument;
    if (!d || !window.ResizeObserver) return;
    new ResizeObserver(() => fit(frame)).observe(d.body);
  }} catch (e) {{ /* 跨源或不可读：靠 showTab/load 兜底 */ }}
}}
function put(frame, html) {{
  delete frame.dataset.fit;
  frame.onload = () => {{
    try {{ frame.contentWindow.__cardSetStyle?.(THEME); }} catch (e) {{}}
    fit(frame); watch(frame);
  }};
  // 卡片 CSS 全页共享一份（见 build_demo.py 的 _dedupe_card_css）：这里展开回去
  frame.srcdoc = html.split(CSS_SLOT).join(`<style>${{DATA.cardCss}}</style>`);
  setTimeout(() => fit(frame), 160);
}}
function refit(scope) {{
  scope.querySelectorAll("iframe").forEach((f) =>
    requestAnimationFrame(() => setTimeout(() => fit(f), 30)));
}}

/* ── 标签页（支持 #quiz / #scenes / #order 深链）── */
function showTab(name) {{
  const btn = document.querySelector(`.tabs button[data-tab="${{name}}"]`);
  if (!btn) return;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b === btn));
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("on"));
  const panel = document.getElementById("panel-" + name);
  panel.classList.add("on");
  refit(panel);  // 显形后立刻补量一次（隐藏期间量不到高度）
}}
window.addEventListener("resize", () => refit(document));
document.getElementById("tabs").addEventListener("click", (e) => {{
  const btn = e.target.closest("button[data-tab]");
  if (btn) showTab(btn.dataset.tab);
}});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

/* ── 玩法一：答题（题目来自快照，卡片的题面与它同源）── */
const state = {{ i: 0, picks: [], done: false }};
const Q = SET.questions;  // 随机抽中的那一套（每套题数与段位表一致）

/* ── 题面渲染：空行把「铺垫」和「问句」分开，问句加粗 ──
   换行必须原样保留（配合 .qtext 的 pre-wrap）：日志体的时间列、
   公文体的「问：/答：」逐行，全靠它。
   ⚠️ 这里是 Python f-string：JS 里的 \n 必须写成 \\n，否则会被 Python
   先解释成真换行，把 JS 字符串字面量截断 —— 整段脚本静默不执行。 */
function askHtml(t) {{
  const parts = String(t).split("\\n\\n").map(s => s.trim()).filter(Boolean);
  if (!parts.length) return "";
  if (parts.length === 1) return `<span class="q-ask">${{parts[0]}}</span>`;
  const head = parts.slice(0, -1).join("\\n\\n");
  return `${{head}}\\n\\n<span class="q-ask">${{parts[parts.length - 1]}}</span>`;
}}

function renderQuestion() {{
  const box = document.getElementById("qbox");
  const q = Q[state.i];
  const letters = "ABCD";
  box.innerHTML = `
    <div class="qmeta">Q${{state.i + 1}} / ${{Q.length}}</div>
    <div class="qtext">${{askHtml(q.text)}}</div>
    <div class="opts" id="opts"></div>
    <div id="verdict"></div>`;
  const opts = document.getElementById("opts");
  q.options.forEach((text, idx) => {{
    const b = document.createElement("button");
    b.textContent = `${{letters[idx]}}. ${{text}}`;
    b.onclick = () => answer(idx);
    opts.appendChild(b);
  }});
}}

function answer(pick) {{
  const q = Q[state.i];
  const right = pick === q.correct;
  state.picks.push(pick);
  const letters = "ABCD";
  const btns = [...document.querySelectorAll("#opts button")];
  btns.forEach((b, idx) => {{
    b.disabled = true;
    if (idx === q.correct) b.classList.add("pick-right");
    else if (idx === pick) b.classList.add("pick-wrong");
  }});
  document.getElementById("verdict").innerHTML = `
    <div class="verdict ${{right ? "ok" : "no"}}">
      ${{right ? "✓ 答对了：" + q.options[q.correct] : "✗ 你答了 " + q.options[pick] + "，正确是 " + q.options[q.correct]}}
    </div>
    <div class="reveal">${{q.reveal}}</div>`;

  const next = document.createElement("button");
  next.className = "nextbtn";
  const last = state.i === Q.length - 1;
  next.textContent = last ? "看我的战报卡 →" : "下一题 →";
  next.onclick = () => {{ state.i += 1; last ? finish() : renderQuestion(); }};
  document.getElementById("qbox").appendChild(next);
}}

function finish() {{
  state.done = true;
  document.getElementById("qbox").hidden = true;
  let bits = 0;
  Q.forEach((q, i) => {{ if (state.picks[i] === q.correct) bits |= (1 << i); }});
  const score = Q.filter((q, i) => state.picks[i] === q.correct).length;
  const [title, tagline] = DATA.ranks[String(score)];
  document.getElementById("final").hidden = false;
  document.getElementById("rankTitle").textContent = title;
  document.getElementById("rankNote").textContent = tagline + ` · 答对 ${{score}} / ${{Q.length}}`;
  document.getElementById("quizCardBox").hidden = false;  // 答完才露出战报卡
  let html = SET.cards[String(bits)];
  Q.forEach((q, i) => {{
    if (state.picks[i] !== q.correct) {{
      html = html.split(`{{{{Q${{i}}}}}}`).join(q.options[state.picks[i]]);
    }}
  }});
  put(document.getElementById("quizCard"), html);
}}

/* ── 玩法二：六场景切换 ── */
const scenesBox = document.getElementById("scenes");
DATA.sceneOrder.forEach((key) => {{
  const b = document.createElement("button");
  b.dataset.scene = key;
  b.textContent = DATA.sceneLabels[key];
  b.onclick = () => {{
    scenesBox.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    put(document.getElementById("sceneCard"), DATA.sceneCards[key]);
  }};
  scenesBox.appendChild(b);
}});
scenesBox.querySelector(`button[data-scene="${{START_SCENE}}"]`)?.classList.add("on");

/* ── 初始化 ── */
renderQuestion();
put(document.getElementById("sceneCard"), DATA.sceneCards[START_SCENE]);
put(document.getElementById("orderCard"), ORDER.card);
document.getElementById("quizHint").textContent =
  `题目、选项、揭示全部由快照数据生成 —— 本次主题「${{DATA.styleLabels[THEME]}}」，`
  + "卡片顶部可随时换；刷新页面换一套题、换一种主题。";
document.getElementById("sceneHint").textContent =
  `六个场景各有一套排序标准 —— 本次默认「${{DATA.sceneLabels[START_SCENE]}}」，点按钮换场景。`;
document.getElementById("orderHint").textContent =
  `这一单是「${{ORDER.spec}}」（¥${{ORDER.total.toFixed(1)}}，${{ORDER.source === "calculate-price" ? "实时计价" : "菜单标价"}}）。`
  + "点餐单是只读产出；真实下单要用户明确确认，回传支付链接且随时可退。";
/* 低速兜底：隐藏期间量不到高度的卡，显形后自动补上（高度稳定后不再写入）*/
setInterval(() => document.querySelectorAll("iframe").forEach(fit), 400);
if (location.hash) showTab(location.hash.slice(1));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
