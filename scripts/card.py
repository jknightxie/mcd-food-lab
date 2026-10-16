"""生成可分享的结果卡片（静态 HTML）。

为什么要有这个：排名按公开 star 数算。零存量受众的账号没有渠道去推，
star 只能靠产品自己「让人想转发」。

设计目标不是「信息全」，是「让人想发出去」。第一版是白底表格 +
免责声明 —— 信息准确，但没人会转发一张表格。这一版是
**麦当劳品牌色的新粗野主义风格**：

    - 红条品牌头 + 黄色大字结论区 + 黑描边硬阴影 —— 一眼认出是麦当劳
    - 「每 1 元 = X 克蛋白质」签名条 —— 核心卖家用最大字号钉在冠军名下
    - 反差贴纸（微旋转）—— 转发时被截图的那一句
    - 条形图榜单 —— 长短对比比数字表格直觉得多
    - 剪裁线下的覆盖率 —— 边界披露保留，但做成「顺便告诉你的事实」

数字纪律不变：**所有数字由真实 MCP 响应算出，绝不在模板里手写示例值。**
「比巨无霸便宜 X 元」这类对比只在两个餐品都在同一门店菜单里时才生成。
"""

from __future__ import annotations

import html
from typing import Any

from fuel_index import (
    METRICS,
    SCENARIOS,
    FuelIndex,
    _category_medians,
    _fmt,
    recommend,
)
from order import OrderQuote
from quiz import build_quiz, rank_for, reversal_pair, score_quiz

__all__ = [
    "render_card",
    "card_filename",
    "STYLES",
    "STYLE_LABELS",
    "resolve_style",
    "style_options",
]

# 四套视觉风格，DOM 完全一致，只换皮肤（CSS 变量 + 主题选择器）。
#   classic  雀跃黄黑 —— 新粗野主义，麦当劳经典红黄黑
#   midnight 深夜黑金 —— 黑底金调，适合「犒劳自己」和深夜场景
#   receipt  营养小票 —— 等宽字体 + 虚线 + 双线表头，像一张真的点餐小票
#   retro    复古海报 —— 奶油底 + 深棕红 + 衬线标题，美式老海报味
STYLES = ("classic", "midnight", "receipt", "retro")

# 开源仓库地址 —— 全站落款里的「具体链接」，调用方没传 project_url 时兜底
PROJECT_URL = "https://github.com/jknightxie/mcd-food-lab"

# ── 「最优」是分场景的 ────────────────────────────────────────────────
#
# 「管住嘴」的最优是蛋白质效率，「请客」是钙效率，「解馋」是每元热量。
# 签名条和眉题必须说清**是哪个维度的最优**，否则读者会把「请客」场景的
# 双层吉士汉堡误读成「蛋白质最优」—— 它是钙效率最优，蛋白只是顺带的。
#
# 蛋白质/元仍是核心卖点：蛋白质场景用它做大字；其余场景每行徽章 +
# 冠军副行都恒定显示它，但它不冒充排序标准。

# 签名条文案（大字那句）—— 键 = 场景主指标
_SIGNATURES = {
    "protein_per_yuan": "每 1 元 = {v} 克蛋白质",
    "calcium_per_yuan": "每 1 元 = {v} 毫克钙",
    "kcal_per_yuan": "每 1 元只摄入 {v} 大卡",
    "energy_density": "每 1 元 = {v} 大卡供能",
    "price": "请客要拿得出手：¥{v} 的排面担当",
}

# 眉题里「最优」的判定标准
_CRITERION = {
    "protein_per_yuan": "蛋白质效率最高",
    "calcium_per_yuan": "钙效率最高",
    "kcal_per_yuan": "每元热量最低",
    "energy_density": "供能效率最高",
    "price": "价格档位最高（请客不为性价比买单）",
}

# ── 风格词 → style ─────────────────────────────────────────────────────
#
# 用户不会说「midnight」，他们说「黑金」「小票」「复古」。
# 映射逻辑放这里而不是调用方 —— 和 `resolve_answer` 同一个理由：
# 保证口径一致，谁调都不走样。听不懂返回 None，绝不猜。

STYLE_LABELS = {
    "classic": "经典黄黑",
    "midnight": "深夜黑金",
    "receipt": "营养小票",
    "retro": "复古海报",
}

_STYLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("midnight", ("深夜", "黑金", "夜宵", "夜间", "黑底", "dark")),
    ("receipt", ("小票", "票据", "收据", "打印", "纸条")),
    ("retro", ("复古", "海报", "怀旧", "美式", "老式")),
    ("classic", ("经典", "默认", "黄黑", "雀跃")),
)


def resolve_style(text: str) -> str | None:
    """把用户嘴里的风格词映射到 style key；听不懂返回 None。"""
    if not text:
        return None
    t = text.strip().lower()
    for key, patterns in _STYLE_PATTERNS:
        for p in patterns:
            if p in t:
                return key
    return None


def style_options() -> str:
    """风格兜底文案 —— 只在用户明确想挑风格时才说。"""
    return "可选：" + " / ".join(STYLE_LABELS[s] for s in STYLES)


# ── 场景 → 风格权重（没指定风格时按权重随机）────────────────────────────
#
# 用户拍板（2026-10-14）：「四套版本默认是根据场景随机来的，不是默认不变」——
# 同一个场景连开两次，初始风格不重样；顶上切换器反正随时能点。
# 氛围亲和（深夜→黑金、请客→复古、点餐单→小票）保留为**权重**而非定论：
# 是「偏心」，不是「命中」。

_SCENE_STYLE_WEIGHTS: dict[str, dict[str, int]] = {
    "comfort": {"midnight": 3, "classic": 1, "receipt": 1, "retro": 1},
    "host": {"retro": 3, "classic": 1, "receipt": 1, "midnight": 1},
    "order": {"receipt": 3, "classic": 1, "midnight": 1, "retro": 1},
    "quiz": {"midnight": 3, "classic": 1, "receipt": 1, "retro": 1},
}
_UNIFORM_WEIGHTS = {s: 1 for s in STYLES}


def random_style(scenario_key: str | None = None, rng=None) -> str:
    """没指定风格时按场景权重随机挑一套。

    和 `resolve_style` 放同一个模块的理由一样：agent 与 CLI 共用一份规则。
    传 `rng`（random.Random 实例）可复现；不传用系统 random。
    """
    import random

    rng = rng or random
    weights = _SCENE_STYLE_WEIGHTS.get(scenario_key or "", _UNIFORM_WEIGHTS)
    keys = list(STYLES)
    return rng.choices(keys, weights=[weights.get(k, 1) for k in keys])[0]


# ── 四风格切换器（switchable 模式专用）─────────────────────────────────
#
# 分享卡默认单风格（干净、无 JS 依赖）；预览/挑风格时才带切换器。
# 四套主题的 CSS 本来就都在同一张样式表里（t-xxx 类），
# 所以切换 = 在 body 和 .card 上换类，零 CSS 重复、零额外请求。

_SWITCH_CSS = """
/* ── 风格切换器（只在 switchable 卡片里出现）── */
.style-switch {
  position: sticky; top: 10px; z-index: 99;
  display: flex; gap: 6px; justify-content: center; flex-wrap: wrap;
  margin-bottom: 14px;
}
.style-switch button {
  font-family: inherit; cursor: pointer;
  border: 2px solid #1a1a1a; background: #fff; color: #1a1a1a;
  border-radius: 999px; padding: 5px 12px;
  font-size: 12px; font-weight: 800;
  box-shadow: 2px 2px 0 #1a1a1a;
}
.style-switch button.on { background: #1a1a1a; color: #ffc72c; }
"""

_SWITCH_JS = """
<script>
(function () {
  var KEYS = ["classic", "midnight", "receipt", "retro"];
  var btns = document.querySelectorAll(".style-switch button");
  var card = document.querySelector(".card");
  function apply(s) {
    KEYS.forEach(function (k) {
      document.body.classList.remove("t-" + k);
      if (card) card.classList.remove("t-" + k);
    });
    document.body.classList.add("t-" + s);
    if (card) card.classList.add("t-" + s);
    btns.forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-style") === s);
    });
  }
  btns.forEach(function (b) {
    b.addEventListener("click", function () { apply(b.getAttribute("data-style")); });
  });
  // 暴露给宿主页：演示页要按本次随机主题给每张卡定初始外观
  // （宿主只换主题、不复制主题逻辑 —— 否则两份实现迟早会漂）
  window.__cardSetStyle = apply;
})();
</script>
"""


def _switch_html(style: str) -> tuple[str, str]:
    """返回 (切换器 HTML, 切换 JS)。style = 初始高亮的那套。"""
    buttons = "".join(
        f'<button data-style="{s}" class="{"on" if s == style else ""}">'
        f"{STYLE_LABELS[s]}</button>"
        for s in STYLES
    )
    return f'<div class="style-switch">{buttons}</div>', _SWITCH_JS


_CARD_CSS = """
:root {
  --ink: #1a1a1a;
  --yellow: #ffc72c;
  --red: #da291c;
  --cream: #f4eee1;
  --paper: #ffffff;
  --soft: #faf6ea;
  --tan: #6f6552;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--cream); color: var(--ink);
  font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont,
               "Segoe UI", sans-serif;
  padding: 26px 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.card {
  max-width: 400px; margin: 0 auto; background: var(--paper);
  border: 3px solid var(--ink); border-radius: 20px; overflow: hidden;
  box-shadow: 9px 9px 0 var(--ink);
}

/* ── 品牌条 ── */
.strip {
  background: var(--red); color: #fff; padding: 12px 15px;
  display: flex; align-items: center; gap: 9px;
  border-bottom: 3px solid var(--ink);
}
.m-badge {
  width: 26px; height: 26px; flex: none;
  background: var(--yellow); color: var(--ink);
  border: 2px solid var(--ink); border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-family: Georgia, "Times New Roman", serif;
  font-style: italic; font-weight: 900; font-size: 15px;
}
.strip-name { font-weight: 900; font-size: 15px; flex: 1; letter-spacing: .02em; }
.strip-tag {
  border: 2px solid #fff; border-radius: 999px; padding: 3px 11px;
  font-size: 12px; font-weight: 800; white-space: nowrap;
}

/* ── 结论区 ── */
.hero { background: var(--yellow); padding: 20px 16px 18px; }
.eyebrow {
  font-size: 11px; font-weight: 800; letter-spacing: .07em;
  color: rgba(26,26,26,.72); margin-bottom: 8px;
}
.champ { font-size: 30px; font-weight: 900; line-height: 1.18; letter-spacing: -.01em; }
.signature {
  margin-top: 13px; display: inline-block;
  background: var(--ink); color: var(--yellow);
  border-radius: 10px; padding: 8px 13px;
  font-size: 14px; font-weight: 700;
}
.signature b {
  font-size: 22px; font-weight: 900;
  font-variant-numeric: tabular-nums; margin: 0 2px;
}
.champ-sub {
  margin-top: 11px; font-size: 12.5px; font-weight: 600;
  color: rgba(26,26,26,.78); font-variant-numeric: tabular-nums;
}

/* ── 反差贴纸 ── */
.sticker {
  margin: 16px 16px 0; display: inline-block;
  background: #fff; border: 2px solid var(--ink); border-radius: 12px;
  box-shadow: 4px 4px 0 var(--ink); transform: rotate(-1.2deg);
  padding: 10px 13px; font-size: 14px; font-weight: 800;
  font-variant-numeric: tabular-nums;
}
.sticker b { color: var(--red); }

/* ── 条形图榜单 ── */
.race { padding: 20px 16px 8px; }
.race-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 10px; margin-bottom: 12px;
}
.race-title { font-size: 14.5px; font-weight: 900; }
.race-note {
  font-size: 10.5px; color: var(--tan); font-weight: 600;
  text-align: right; line-height: 1.4;
}
.row { padding: 9px 0; border-bottom: 1.5px dashed rgba(26,26,26,.18); }
.row:last-child { border-bottom: none; }
.row-top { display: flex; align-items: center; gap: 8px; }
.rk {
  width: 21px; height: 21px; flex: none;
  border: 2px solid var(--ink); border-radius: 6px; background: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 900;
}
.row.gold .rk { background: var(--red); color: #fff; }
.nm { font-size: 14.5px; font-weight: 800; flex: 1; min-width: 0; }
.sig {
  flex: none; background: var(--ink); color: var(--yellow);
  border-radius: 999px; padding: 2.5px 9px;
  font-size: 11.5px; font-weight: 800; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.sig i { font-style: normal; font-size: 9.5px; opacity: .85; margin-left: 1px; }
.track { display: flex; align-items: center; gap: 7px; margin: 7px 0 5px; }
.fill {
  height: 15px; flex: none; min-width: 8px;
  border: 2px solid var(--ink); border-radius: 7px;
  background: var(--yellow);
}
.row.gold .fill { background: var(--red); }
.barv {
  font-size: 13.5px; font-weight: 900;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.barv i { font-style: normal; font-size: 10px; font-weight: 700; color: var(--tan); margin-left: 2px; }
.sub {
  font-size: 11.5px; color: var(--tan); font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ── 数据存疑 ── */
.sus {
  margin: 12px 16px 0; border: 1.5px dashed var(--tan); border-radius: 10px;
  padding: 9px 11px; font-size: 11px; color: var(--tan); line-height: 1.6;
}
.sus b { color: var(--ink); }
.sus ul { margin: 5px 0 0 15px; }

/* ── 覆盖率（剪裁线）── */
.cut {
  margin: 18px 16px 0; border-top: 2px dashed var(--ink);
  text-align: center;
}
.cut span {
  position: relative; top: -10px; background: var(--paper);
  padding: 0 9px; font-size: 10.5px; font-weight: 800;
  letter-spacing: .12em; color: var(--tan);
}
.cover { display: flex; gap: 13px; margin: 4px 16px 0; align-items: flex-start; }
.cover-num {
  flex: none; font-size: 36px; font-weight: 900; color: var(--red);
  line-height: 1; font-variant-numeric: tabular-nums;
}
.cover-num i {
  display: block; font-style: normal; font-size: 9.5px; font-weight: 700;
  letter-spacing: .08em; color: var(--tan); margin-top: 4px;
}
.cover-txt { font-size: 11.5px; color: var(--tan); line-height: 1.65; font-weight: 600; }
.cover-txt b { color: var(--ink); font-variant-numeric: tabular-nums; }

/* ── 页脚（全站统一落款：参赛声明 + 数据来源 + 可点开源地址）── */
.foot {
  margin-top: 18px; border-top: 3px solid var(--ink); background: var(--soft);
  padding: 11px 16px;
}
.foot-brand { font-size: 11.5px; font-weight: 900; }
.foot .disclaimer {
  font-size: 10px; font-weight: 600; color: var(--tan);
  margin-top: 3px; line-height: 1.7;
}
.foot .disclaimer a {
  color: var(--ink); font-weight: 700;
  text-decoration: underline; text-underline-offset: 2px;
  word-break: break-all;
}

/* ── 战力测试战报卡 ── */
.qz { padding: 20px 16px 8px; }
.qz-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 10px; margin-bottom: 12px;
}
.qz-title { font-size: 14.5px; font-weight: 900; }
.qz-note { font-size: 10.5px; color: var(--tan); font-weight: 600; }
.qz-row { padding: 10px 0; border-bottom: 1.5px dashed rgba(26,26,26,.18); }
.qz-row:last-child { border-bottom: none; }
.qz-top { display: flex; align-items: baseline; gap: 8px; }
.qz-no {
  flex: none; font-size: 11px; font-weight: 900; color: var(--tan);
  font-variant-numeric: tabular-nums;
}
/* white-space: pre-wrap 是**必须**的 —— 日志体（21:31:04 加入购物车）和公文体
   （「问：…答：…」逐行）的排版全靠换行，默认值会把 \n 折叠成一个空格，整段糊成一坨。
   题面字重与卡片其他文字一致（700）。曾做过"铺垫常规 / 问句加粗"的分级，
   用户直接指着说「这里的字体和别的不一致」—— 那是题面 150 字时代的权宜之计，
   压到 60 字后分级已无必要。层次靠空白行，不靠字重。 */
.qz-q {
  font-size: 13px; font-weight: 700; flex: 1; min-width: 0;
  white-space: pre-wrap; line-height: 1.7;
}
/* .q-ask 保留为钩子：将来若想用**颜色**（而非字重）做层次，改这里 —— 字重别再动。 */
.qz-q .q-ask { }
/* ── 战绩水印图章 ──
   对/错不是题旁的小图标，是两枚**盖在答案区正中的水印大印**：
   朱砂色、双边框（外粗内细，outline 负偏移内描边）、宋体大字、
   微旋、浓印 —— 用户实测「透明度很低，要有强烈对比，突出效果」，
   浓度从 .38 提到 .62：盖得住，又还没糊到答案的字读不出来。 */
.qz-body { position: relative; }
.qz-seal {
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%, -50%) rotate(-13deg);
  width: 92px; height: 92px;
  display: flex; align-items: center; justify-content: center;
  font-family: "SimSun", "STSong", "SimSun-ExtB", Georgia, serif;
  font-size: 50px; font-weight: 900; line-height: 1;
  color: var(--red);
  border: 4px solid currentColor; border-radius: 11px;
  outline: 2px solid currentColor; outline-offset: -8px;
  opacity: .62;
  pointer-events: none; user-select: none;
}
.qz-seal.qz-bad {
  border-style: dashed; outline-style: dashed;
  transform: translate(-50%, -50%) rotate(11deg);
}
.qz-ans { font-size: 11.5px; color: var(--tan); font-weight: 600; margin-top: 4px; }
.qz-ans b { color: var(--ink); }
.qz-ans .miss { color: var(--red); text-decoration: line-through; }
.qz-reveal {
  margin-top: 6px; font-size: 12px; font-weight: 700; line-height: 1.6;
  font-variant-numeric: tabular-nums;
}
.t-midnight .qz-row { border-bottom-color: rgba(242,239,232,.15); }
.t-midnight .qz-ans { color: #9a9384; }
.t-midnight .qz-ans b { color: #f2efe8; }
.t-midnight .qz-ans .miss { color: #ff7b72; }
.t-midnight .qz-no, .t-midnight .qz-note { color: #9a9384; }
/* 深夜底吃光深红，印泥提亮并加重 —— 不然盖上看不见 */
.t-midnight .qz-seal { color: #ff6a52; opacity: .68; }
.t-retro .qz-row { border-bottom-color: rgba(58,36,21,.2); }
.t-retro .qz-ans { color: #8a6a45; }
.t-retro .qz-ans b { color: #3a2415; }
.t-retro .qz-no, .t-retro .qz-note { color: #8a6a45; }
.t-retro .qz-seal { color: #a33327; opacity: .6; }
.t-receipt .qz-row { border-bottom: 1px dashed #c9c4b6; }
/* 小票的印泥是墨黑，方角 —— 像票据上洇开的印 */
.t-receipt .qz-seal { color: #1a1a1a; border-radius: 3px; opacity: .5; }

/* ── 点餐单 ── */
.od { padding: 20px 16px 8px; }
.od-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 10px; margin-bottom: 12px;
}
.od-title { font-size: 14.5px; font-weight: 900; }
.od-note { font-size: 10.5px; color: var(--tan); font-weight: 600; }
.od-row { padding: 9px 0; border-bottom: 1.5px dashed rgba(26,26,26,.18); }
.od-row:last-child { border-bottom: none; }
.od-top { display: flex; align-items: baseline; gap: 8px; }
.od-qty {
  flex: none; min-width: 26px; font-size: 12px; font-weight: 900;
  color: var(--tan); font-variant-numeric: tabular-nums;
}
.od-name { font-size: 14px; font-weight: 800; flex: 1; min-width: 0; }
.od-price {
  flex: none; font-size: 14px; font-weight: 900;
  font-variant-numeric: tabular-nums;
}
.od-sub {
  margin-top: 3px; font-size: 11.5px; color: var(--tan); font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.od-src {
  margin: 12px 16px 0; border: 1.5px dashed var(--tan); border-radius: 10px;
  padding: 9px 11px; font-size: 11px; color: var(--tan); line-height: 1.6;
}
.od-src b { color: var(--ink); }
.t-midnight .od-row { border-bottom-color: rgba(242,239,232,.15); }
.t-midnight .od-name { color: #f2efe8; }
.t-midnight .od-qty, .t-midnight .od-sub, .t-midnight .od-note { color: #9a9384; }
.t-midnight .od-src { border-color: #55524a; color: #9a9384; }
.t-midnight .od-src b { color: #f2efe8; }
.t-retro .od-row { border-bottom-color: rgba(58,36,21,.2); }
.t-retro .od-name { color: #3a2415; }
.t-retro .od-qty, .t-retro .od-sub, .t-retro .od-note { color: #8a6a45; }
.t-retro .od-src { border-color: #c9b795; color: #8a6a45; }
.t-retro .od-src b { color: #3a2415; }
.t-receipt .od-row { border-bottom: 1px dashed #c9c4b6; }

/* ══ 主题：深夜黑金 ══════════════════════════════════════════════ */
body.t-midnight { background: #101012; color: #f2efe8; }
.t-midnight {
  /* 根上必须先立浅色文字：题干/揭示/价格这些没单独覆盖 color 的元素
     全靠继承 —— 少了这行就是黑底黑字（真实事故，回归测试锁死）。 */
  color: #f2efe8;
  background: #1b1b1e; border-color: var(--yellow);
  box-shadow: 9px 9px 0 #000;
}
.t-midnight .strip { background: var(--yellow); color: #1a1a1a; border-bottom-color: #1a1a1a; }
.t-midnight .m-badge { background: #1a1a1a; color: var(--yellow); border-color: #1a1a1a; }
.t-midnight .strip-name { color: #1a1a1a; }
.t-midnight .strip-tag { border-color: #1a1a1a; color: #1a1a1a; }
.t-midnight .hero { background: #1b1b1e; }
.t-midnight .eyebrow { color: #9a9384; }
.t-midnight .champ { color: #ffffff; }
.t-midnight .signature { background: var(--yellow); color: #1a1a1a; }
.t-midnight .champ-sub { color: #b9b2a4; }
.t-midnight .sticker {
  background: #1b1b1e; color: #ffffff; border-color: var(--yellow);
  box-shadow: 4px 4px 0 var(--yellow);
}
.t-midnight .sticker b { color: var(--yellow); }
.t-midnight .race-title, .t-midnight .nm, .t-midnight .barv { color: #f2efe8; }
.t-midnight .race-note, .t-midnight .sub, .t-midnight .barv i { color: #9a9384; }
.t-midnight .rk { background: #1b1b1e; color: #f2efe8; border-color: #f2efe8; }
.t-midnight .row.gold .rk { background: #ff5a3c; color: #1a1a1a; border-color: #ff5a3c; }
.t-midnight .sig { background: var(--yellow); color: #1a1a1a; }
.t-midnight .sig i { color: #1a1a1a; opacity: .7; }
.t-midnight .fill { background: var(--yellow); border-color: #f2efe8; }
.t-midnight .row.gold .fill { background: #ff5a3c; border-color: #f2efe8; }
.t-midnight .row { border-bottom-color: rgba(242,239,232,.15); }
.t-midnight .sus { border-color: #55524a; color: #9a9384; }
.t-midnight .sus b { color: #f2efe8; }
.t-midnight .cut { border-top-color: #55524a; }
.t-midnight .cut span { background: #1b1b1e; color: #9a9384; }
.t-midnight .cover-num { color: var(--yellow); }
.t-midnight .cover-num i { color: #9a9384; }
.t-midnight .cover-txt { color: #b9b2a4; }
.t-midnight .cover-txt b { color: #f2efe8; }
.t-midnight .foot { background: #151517; border-top-color: var(--yellow); }
.t-midnight .foot-brand { color: #f2efe8; }
.t-midnight .foot .disclaimer { color: #9a9384; }
.t-midnight .foot a { color: var(--yellow); }

/* ══ 主题：营养小票 ══════════════════════════════════════════════ */
body.t-receipt { background: #dcd8cc; }
.t-receipt, .t-receipt * { font-family: "Consolas", "Courier New", "Microsoft YaHei", monospace; }
.t-receipt {
  background: #fdfcf7; border: 2px dashed #8a8578;
  box-shadow: 6px 6px 0 #b9b4a6; border-radius: 6px;
}
.t-receipt .strip {
  background: #fdfcf7; color: #1a1a1a;
  border-bottom: 3px double #1a1a1a; justify-content: center;
}
.t-receipt .m-badge { background: #1a1a1a; color: #fdfcf7; border-color: #1a1a1a; }
.t-receipt .strip-tag { border: 1.5px dashed #1a1a1a; color: #1a1a1a; }
.t-receipt .hero { background: #fdfcf7; text-align: center; }
.t-receipt .champ { font-size: 24px; color: #1a1a1a; }
.t-receipt .signature { background: #1a1a1a; color: #fdfcf7; border-radius: 4px; }
.t-receipt .champ-sub { color: #6f6552; }
.t-receipt .sticker {
  display: block; text-align: center; transform: none; box-shadow: none;
  background: #fdfcf7; border: 1.5px dashed #1a1a1a; margin: 16px 14px 0;
}
.t-receipt .sticker b { color: #1a1a1a; text-decoration: underline; }
.t-receipt .race-title::before { content: "* "; }
.t-receipt .fill {
  height: 13px; border-radius: 3px; border-width: 1.5px;
  background: repeating-linear-gradient(-45deg, #1a1a1a 0 2px, transparent 2px 5px);
}
.t-receipt .row.gold .fill { background: #1a1a1a; }
.t-receipt .row.gold .rk { background: #1a1a1a; color: #fdfcf7; }
.t-receipt .row.gold .nm::before { content: ">> "; }
.t-receipt .row { border-bottom: 1px dashed #c9c4b6; }
.t-receipt .sus { border-style: solid; border-color: #c9c4b6; }
.t-receipt .cut { border-top: 2px dashed #8a8578; }
.t-receipt .cut span { background: #fdfcf7; }
.t-receipt .cover-num { color: #1a1a1a; }
.t-receipt .foot { background: #fdfcf7; border-top: 2px dashed #8a8578; }
.t-receipt .foot a { color: #1a1a1a; }

/* ══ 主题：复古海报 ══════════════════════════════════════════════ */
body.t-retro { background: #e9dcc3; }
.t-retro {
  background: #f7efdd; border-color: #7c2a1e;
  box-shadow: 8px 8px 0 #c9b795; border-radius: 14px;
}
.t-retro .champ, .t-retro .race-title, .t-retro .strip-name { font-family: Georgia, "Times New Roman", "SimSun", serif; }
.t-retro .strip { background: #7c2a1e; color: #f3e2c0; border-bottom-color: #7c2a1e; }
.t-retro .m-badge { background: #f3e2c0; color: #7c2a1e; border-color: #7c2a1e; }
.t-retro .strip-tag { border-color: #f3e2c0; color: #f3e2c0; }
.t-retro .hero { background: #f0d48a; }
.t-retro .eyebrow { color: #7a5b33; }
.t-retro .champ { color: #3a2415; }
.t-retro .signature { background: #7c2a1e; color: #f3e2c0; }
.t-retro .champ-sub { color: #6b4a2a; }
.t-retro .sticker {
  background: #f7efdd; border-color: #7c2a1e;
  box-shadow: 4px 4px 0 #c9b795; transform: rotate(-1.5deg);
}
.t-retro .sticker b { color: #a33327; }
.t-retro .nm, .t-retro .race-title, .t-retro .barv { color: #3a2415; }
.t-retro .race-note, .t-retro .sub, .t-retro .barv i { color: #8a6a45; }
.t-retro .rk { border-color: #3a2415; color: #3a2415; }
.t-retro .row.gold .rk { background: #a33327; color: #f7efdd; border-color: #a33327; }
.t-retro .fill { background: #c8892f; border-color: #3a2415; }
.t-retro .row.gold .fill { background: #a33327; }
.t-retro .sig { background: #7c2a1e; color: #f3e2c0; }
.t-retro .sig i { color: #f3e2c0; opacity: .8; }
.t-retro .row { border-bottom-color: rgba(58,36,21,.2); }
.t-retro .sus { border-color: #c9b795; color: #8a6a45; }
.t-retro .sus b { color: #3a2415; }
.t-retro .cut { border-top-color: #7c2a1e; }
.t-retro .cut span { background: #f7efdd; color: #8a6a45; }
.t-retro .cover-num { color: #a33327; }
.t-retro .cover-num i { color: #8a6a45; }
.t-retro .cover-txt { color: #6b4a2a; }
.t-retro .cover-txt b { color: #3a2415; }
.t-retro .foot { background: #f0e6cd; border-top-color: #7c2a1e; }
.t-retro .foot-brand { color: #3a2415; }
.t-retro .foot .disclaimer { color: #8a6a45; }
.t-retro .foot a { color: #7c2a1e; }
"""


def card_filename(scenario_key: str) -> str:
    return f"mcd-food-lab-{scenario_key}.html"


# ── 全站统一落款 ────────────────────────────────────────────────────────
#
# 用户拍板：「所有页面落款 —— 本项目为参赛作品，非麦当劳官方产品。
# 数据以麦当劳官方渠道实时结果为准。开源地址：给出具体链接」。
# 所以链接带兜底：调用方没传 project_url 也用 PROJECT_URL，
# 保证每张卡落款里都有真链接；传入的 URL 仍过协议白名单，
# 过不了就回落兜底链接 —— 绝不把 javascript: 放进 href。

_FOOTER_TEXT = (
    "本项目为参赛作品，非麦当劳官方产品。"
    "数据以麦当劳官方渠道实时结果为准。"
)


def _footer_html(project_url: str = "") -> str:
    """全站统一落款：参赛声明 + 数据来源 + 可点的开源地址。"""
    url = _safe_url(project_url) or PROJECT_URL
    return (
        '<div class="foot">'
        '<div class="foot-brand">麦门食验室</div>'
        f'<div class="disclaimer">{_FOOTER_TEXT}<br>'
        f'开源地址：<a href="{_esc(url)}">{_esc(url)}</a></div>'
        "</div>"
    )


def _qz_text(text: Any) -> str:
    """题面渲染：用空行把「铺垫」和「问句」分开，铺垫常规字重、问句加粗。

    为什么要分：梗壳重写后题面从平均 45 字涨到 100~160 字（日志体/公文体），
    整段特粗读起来很累。配合 .qz-q 的 white-space:pre-wrap，
    换行原样保留 —— 日志体的时间列、公文体的「问：/答：」逐行都靠它。
    """
    raw = str(text).strip()
    parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if len(parts) <= 1:
        return f'<span class="q-ask">{_esc(raw)}</span>'
    head = "\n\n".join(parts[:-1])
    return f'{_esc(head)}\n\n<span class="q-ask">{_esc(parts[-1])}</span>'


def _esc(text: Any) -> str:
    return html.escape(str(text))


_SAFE_URL_SCHEMES = ("https://", "http://")


def _safe_url(url: str) -> str:
    """只放行 http(s) 链接 —— 防 `javascript:` XSS。

    project_url 会进 `<a href>`；html.escape 只转义引号和尖括号，
    挡不住 `javascript:alert(1)` 这种协议注入。协议不在白名单里
    就整个丢弃链接 —— 宁可少一个「开源地址」，不放行可疑协议。
    """
    u = (url or "").strip()
    if u.lower().startswith(_SAFE_URL_SCHEMES):
        return u
    return ""


def _pretty_store(name: str) -> str:
    """门店名给读者看，不要官方全称。

    「麦当劳北京建外SOHO(A座)餐厅」→「北京建外SOHO(A座)」。
    前缀「麦当劳」和后缀「餐厅」在卡片语境里都是废话 ——
    用户看到的是麦当劳工具的卡片，店里卖的是麦当劳。
    """
    s = (name or "").strip()
    if s.startswith("麦当劳"):
        s = s[3:]
    if s.endswith("餐厅"):
        s = s[: -len("餐厅")]
    return s.strip()


def _smart(v: float | None) -> str:
    """条形图数值：个位数的用两位小数，两位数以上一位就够。"""
    if v is None:
        return "—"
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"


def _bar_widths(top: list, primary: str, higher_is_better: bool) -> list[float]:
    """把主指标换算成条长（百分比）。

    条长表达的是「这个场景下的好坏」，所以越好的越长 ——
    低优指标（如热量/元）取倒数后再归一化，读图规则永远一致。
    最短保底 10%，避免短到看不见。
    """
    raws = []
    for item in top:
        v = item.metric(primary)
        if v is None or v <= 0:
            raws.append(0.0)
        elif higher_is_better:
            raws.append(float(v))
        else:
            raws.append(1.0 / float(v))
    best = max(raws) if raws else 0.0
    if best <= 0:
        return [10.0] * len(raws)
    return [10 + 65 * (r / best) for r in raws]


def _coverage_html(index: FuelIndex) -> str:
    """覆盖率披露块 —— 剪裁线下的大数字。主卡与战报卡共用。"""
    cover_items = "、".join(_esc(n) for n in index.unmatched_names[:4])
    more = f" 等 {len(index.unmatched_names)} 款" if len(index.unmatched_names) > 4 else ""
    return f"""
  <div class="cut"><span>数据边界</span></div>
  <div class="cover">
    <div class="cover-num">{index.coverage:.0f}%<i>有营养数据</i></div>
    <div class="cover-txt">
      本店 <b>{index.menu_total}</b> 款在售，有营养数据的 <b>{index.matched}</b> 款。
      没查到的（{cover_items}{more}）<b>不参与推荐</b> —— 不拿估算值凑数。
    </div>
  </div>"""


def render_card(
    index: FuelIndex,
    scenario_key: str,
    store_name: str = "",
    project_url: str = "",
    style: str = "classic",
    switchable: bool = True,
) -> str:
    """渲染一张**值得转发**的结果卡。

    结构（从上到下）：

        1. 红色品牌条 —— 一眼认出麦当劳
        2. 黄色结论区 —— 冠军名 + 场景签名条（大字 = 该场景的排序标准，
           眉题写明「最优解按什么判」；蛋白质/元恒定出现在冠军副行与每行徽章）
        3. 反差贴纸 —— 只在同店有知名款可比时生成
        4. 条形图榜单 —— 条长 = 场景主指标；每行恒定带 g蛋白/元 徽章
        5. 剪裁线覆盖率 —— 披露数据边界，但说成「顺便告诉你的事实」

    **诚实边界**：所有数字来自 MCP 实测；对比句只在两个餐品
    都在同一门店菜单里时才成立，否则不生成。绝不为增强说服力而编造。

    `style` 见 `STYLES`；`store_name` 传**门店名**（会被 `_pretty_store`
    简化），不要传门店 code —— 读者不认识 1950564，只认识「建外SOHO」。
    `switchable`（**默认 True**）时卡片顶部带四风格切换器（同一张样式表里
    四套主题的 CSS 本来就在，切换只是换 t-xxx 类 + 一小段原生 JS）。
    所有生成的卡默认就是四套可切换的；只要用户明确要一张**干净的**
    单风格卡（纯分享、不想让看的人乱点），才传 `switchable=False`。
    """
    if style not in STYLES:
        raise ValueError(f"未知风格：{style}（可选：{' / '.join(STYLES)}）")

    switch_html, switch_js = _switch_html(style) if switchable else ("", "")
    switch_css = _SWITCH_CSS if switchable else ""

    scenario = next((s for s in SCENARIOS if s.key == scenario_key), None)
    if scenario is None:
        raise ValueError(f"未知场景：{scenario_key}")

    top = recommend(index, scenario_key, top=5)
    if not top:
        return _empty_card(index, scenario.label, style, project_url=project_url)

    metric = next((m for m in METRICS if m.key == scenario.primary), None)
    if metric is None:
        raise ValueError(f"场景 {scenario_key} 绑定了无效指标")

    # ── 结论区 ──
    champ = top[0]
    theme = f"t-{style}"
    store_display = _pretty_store(store_name)
    if store_display.isdigit():
        # 传进来的是门店 code，不是名字 —— 读者认识店名不认识编号，
        # 宁可不显示也不把 1950564 放到读者眼前。
        store_display = ""
    store = f" · {_esc(store_display)}" if store_display else ""

    # 眉题说清「最优」按什么判 —— 不然「请客」场景的钙冠军会被误读成蛋白最优
    criterion = _CRITERION.get(
        scenario.primary,
        f"{metric.label}效率最优",
    )
    eyebrow = (
        f"「{_esc(scenario.label)}」最优解：{criterion} · 实时菜单{store}"
    )

    # 大字签名条显示**该场景的排序标准**；蛋白质/元作为核心卖点
    # 恒定出现在冠军副行与每行徽章里，但不冒充别的场景的标准。
    sig_template = _SIGNATURES.get(scenario.primary)
    signature_html = ""
    champ_value = champ.metric(scenario.primary)
    if sig_template and champ_value is not None:
        signature_html = (
            f'<div class="signature">'
            f'{sig_template.format(v=f"<b>{_smart(champ_value)}</b>")}'
            f"</div>"
        )
    champ_sub = (
        f"¥{champ.price:.1f} · 蛋白 {_fmt(champ.protein)}g"
        f" · 热量 {_fmt(champ.kcal)}kcal · 钙 {_fmt(champ.calcium)}mg"
    )
    if scenario.primary != "protein_per_yuan" and champ.protein_per_yuan is not None:
        # 核心卖点不缺席：非蛋白场景里，冠军副行带上蛋白效率
        champ_sub += f" · 蛋白效率 {champ.protein_per_yuan:.2f}g/元"

    # ── 反差贴纸 ──
    sticker_html = _sticker_html(champ, top)

    # ── 条形图榜单 ──
    direction = "条越长越好" if metric.higher_is_better else "数值越低越好，条越长越省"
    widths = _bar_widths(top, scenario.primary, metric.higher_is_better)
    rows = []
    for rank, item in enumerate(top):
        gold = " gold" if rank == 0 else ""
        v = item.metric(scenario.primary)
        sub = (
            f"¥{item.price:.1f} · 蛋白 {_fmt(item.protein)}g"
            f" · 钙 {_fmt(item.calcium)}mg"
        )
        if scenario.tier == "pro":
            sub += f" · 钠 {_fmt(item.sodium)}mg · 脂肪 {_fmt(item.nutrition.fat)}g"
        rows.append(
            f'<div class="row{gold}">'
            f'<div class="row-top">'
            f'<span class="rk">{rank + 1}</span>'
            f'<span class="nm">{_esc(item.name)}</span>'
            f'<span class="sig">{_fmt(item.protein_per_yuan, 2)}<i>g蛋白/元</i></span>'
            f"</div>"
            f'<div class="track">'
            f'<div class="fill" style="width:{widths[rank]:.0f}%"></div>'
            f'<span class="barv">{_smart(v)}<i>{_esc(metric.unit)}</i></span>'
            f"</div>"
            f'<div class="sub">{sub}</div>'
            f"</div>"
        )
    race_html = "".join(rows)

    # ── 数据存疑标注 ──
    medians = _category_medians(index.items)
    notes = [
        f"<li>{_esc(i.name)}：{_esc(i.suspect(medians.get(i.category)))}</li>"
        for i in top
        if i.suspect(medians.get(i.category))
    ]
    sus_html = (
        f'<div class="sus"><b>数据存疑（官方原样输出）</b><ul>{"".join(notes)}</ul></div>'
        if notes
        else ""
    )

    # ── 覆盖率 ──
    gap_html = _coverage_html(index)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦门食验室 · {_esc(scenario.label)}</title>
<style>{_CARD_CSS}{switch_css}</style>
</head>
<body class="{theme}">
{switch_html}<div class="card {theme}">
  <div class="strip">
    <div class="m-badge">M</div>
    <div class="strip-name">麦门食验室</div>
    <div class="strip-tag">{_esc(scenario.label)}</div>
  </div>

  <div class="hero">
    <div class="eyebrow">{eyebrow}</div>
    <div class="champ">{_esc(champ.name)}</div>
    {signature_html}
    <div class="champ-sub">{champ_sub}</div>
  </div>

  {sticker_html}

  <div class="race">
    <div class="race-head">
      <span class="race-title">效率榜 TOP {len(top)}</span>
      <span class="race-note">按{_esc(metric.label)} {_esc(metric.unit)} 排序<br>{direction}</span>
    </div>
    {race_html}
  </div>
  {sus_html}
  {gap_html}

  {_footer_html(project_url)}
</div>
{switch_js}</body>
</html>"""


def _famous_runner_up(top: list) -> Any | None:
    """找出榜单里最「众所周知」的那个作为对比对象。

    对比要成立，两个餐品必须**都来自同一家门店的菜单数据**。
    找不到知名款就返回 None —— 那就不写对比。
    """
    known = ("巨无霸", "板烧", "麦辣", "吉士", "鳕鱼", "麦香", "派")
    for item in top[1:]:
        if any(k in item.name for k in known):
            return item
    return None


def _sticker_html(champ: Any, top: list) -> str:
    """反差贴纸 —— **只在两人同属一家门店数据时才写**。

    不为增强说服力而编造对比。榜首没有知名款可比、或差距太小
    （<5%）时，返回空字符串。
    """
    runner = _famous_runner_up(top)
    if runner is None:
        return ""

    a = champ.protein_per_yuan
    b = runner.protein_per_yuan
    if not a or not b:
        return ""

    times = a / b
    if times < 1.05:
        return ""

    saved = runner.price - champ.price
    parts = []
    if saved >= 1:
        parts.append(f"比 {_esc(runner.name)} 便宜 <b>¥{saved:.1f}</b>")
    parts.append(f"蛋白密度高 <b>{(times - 1) * 100:.0f}%</b>")
    return f'<div class="sticker">{"，".join(parts)}</div>'


def _empty_card(
    index: FuelIndex,
    label: str,
    style: str = "classic",
    switchable: bool = True,
    project_url: str = "",
) -> str:
    """没有可推荐数据时的诚实输出 —— 不用占位数字糊过去。"""
    theme = f"t-{style}"
    switch_html, switch_js = _switch_html(style) if switchable else ("", "")
    switch_css = _SWITCH_CSS if switchable else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦门食验室</title><style>{_CARD_CSS}{switch_css}</style></head>
<body class="{theme}">{switch_html}<div class="card {theme}">
  <div class="strip">
    <div class="m-badge">M</div>
    <div class="strip-name">麦门食验室</div>
    <div class="strip-tag">{_esc(label)}</div>
  </div>
  <div class="hero">
    <div class="eyebrow">「{_esc(label)}」最优解 · 实时菜单</div>
    <div class="champ">这家店暂时算不出来</div>
    <div class="champ-sub">{_esc(index.coverage_note)}</div>
  </div>
  <div class="cover" style="margin-top:18px">
    <div class="cover-txt">没有足够数据给出可信推荐 —— 不拿估算值凑数。</div>
  </div>
  {_footer_html(project_url)}
</div>{switch_js}</body></html>"""


def render_quiz_card(
    index: FuelIndex,
    answers: tuple[int | None, ...],
    store_name: str = "",
    project_url: str = "",
    style: str = "classic",
    switchable: bool = True,
    quiz: tuple[Question, ...] | None = None,
) -> str:
    """麦门战力测试战报卡。

    3 道题全部由当前门店实时数据生成（见 quiz.py），这张卡只负责
    把「段位 + 逐题反转揭示」变成值得晒图的东西：

        1. 品牌条 + 段位大字（麦门路人 → 麦门战神）
        2. 答对 X / 3 签名条
        3. 反差贴纸 —— 每元蛋白反转，只在实际成立时出现
        4. 逐题卡：题面 · 你的答案区上盖一枚水印图章
           （对=白文印实线 / 错=朱文印虚线，朱砂双框宋体大字微旋低透明）
           · 正确答案 · 真实数字揭示

    `answers` 与 build_quiz 的题序一一对应，None = 没答（按错算）。
    数字纪律与主卡相同：所有揭示数字来自实时数据，不为效果硬造。
    """
    if style not in STYLES:
        raise ValueError(f"未知风格：{style}（可选：{' / '.join(STYLES)}）")

    switch_html, switch_js = _switch_html(style) if switchable else ("", "")
    switch_css = _SWITCH_CSS if switchable else ""

    quiz = quiz if quiz is not None else build_quiz(index)
    if not quiz:
        return _empty_card(index, "战力测试", style, project_url=project_url)
    if len(answers) != len(quiz):
        raise ValueError(
            f"答案数（{len(answers)}）与题数（{len(quiz)}）不一致"
        )

    total = len(quiz)
    score = score_quiz(quiz, answers)
    rank_title, tagline = rank_for(score, total)
    theme = f"t-{style}"

    store_display = _pretty_store(store_name)
    if store_display.isdigit():
        store_display = ""
    store = f" · {_esc(store_display)}" if store_display else ""

    signature_html = (
        f'<div class="signature">答对 <b>{score}</b> / {total} 题</div>'
    )

    # 反差贴纸：与出题共用同一个反转对 —— 同一个事实，不另造
    sticker_html = ""
    pair = reversal_pair(index)
    if pair:
        famous, champ = pair
        pct = (champ.protein_per_yuan / famous.protein_per_yuan - 1) * 100
        sticker_html = (
            f'<div class="sticker">第 1 题的反转：'
            f"{_esc(champ.name)} 才是每元蛋白王，"
            f"比{_esc(famous.name)}高 <b>{pct:.0f}%</b></div>"
        )

    rows = []
    for no, (q, a) in enumerate(zip(quiz, answers), 1):
        if q.is_correct(a):
            mark, mark_cls = "对", "qz-ok"
            ans_html = f"你答对了：<b>{_esc(q.options[q.correct])}</b>"
        else:
            mark, mark_cls = "错", "qz-bad"
            yours = (
                _esc(q.options[a]) if a is not None and 0 <= a < len(q.options) else "没答"
            )
            ans_html = (
                f'你答了 <span class="miss">{yours}</span>，'
                f"正确是 <b>{_esc(q.options[q.correct])}</b>"
            )
        rows.append(
            f'<div class="qz-row">'
            f'<div class="qz-top">'
            f'<span class="qz-no">Q{no}</span>'
            f'<span class="qz-q">{_qz_text(q.text)}</span>'
            f"</div>"
            # 水印图章盖在答案区上：绝对定位 + 低透明度 + 不拦截指针
            f'<div class="qz-body">'
            f'<div class="qz-ans">{ans_html}</div>'
            f'<div class="qz-reveal">{_esc(q.reveal)}</div>'
            f'<span class="qz-seal {mark_cls}">{mark}</span>'
            f"</div>"
        )
    qz_html = "".join(rows)

    gap_html = _coverage_html(index)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦门战力测试 · {rank_title}</title>
<style>{_CARD_CSS}{switch_css}</style>
</head>
<body class="{theme}">
{switch_html}<div class="card {theme}">
  <div class="strip">
    <div class="m-badge">M</div>
    <div class="strip-name">麦门食验室</div>
    <div class="strip-tag">战力测试</div>
  </div>

  <div class="hero">
    <div class="eyebrow">麦门战力测试 · 实时菜单{store}</div>
    <div class="champ">{_esc(rank_title)}</div>
    {signature_html}
    <div class="champ-sub">{_esc(tagline)}</div>
  </div>

  {sticker_html}

  <div class="qz">
    <div class="qz-head">
      <span class="qz-title">逐题复盘</span>
      <span class="qz-note">全部来自本店实测数据</span>
    </div>
    {qz_html}
  </div>
  {gap_html}

  {_footer_html(project_url)}
</div>
{switch_js}</body>
</html>"""


def render_order_card(
    index: FuelIndex,
    summary: dict,
    store_name: str = "",
    project_url: str = "",
    style: str = "classic",
    switchable: bool = True,
) -> str:
    """点餐单卡：选好的餐 + 实时计价 + 这单的燃料总结。

    大字是**应付合计**（点餐时最关心的一个数），黑底签名条是
    这单的燃料效率 —— 把「每元效率」带到下单前最后一秒。

    `summary` 来自 `order.summarize_order`，字段：
    lines / total / source / note / protein? / protein_per_yuan? / kcal?

    **边界**：这张卡只是点餐单，不产生订单 —— 真实下单是写操作，
    必须用户明确二次确认后在官方 App 完成，MCP 无支付能力。
    """
    if style not in STYLES:
        raise ValueError(f"未知风格：{style}（可选：{' / '.join(STYLES)}）")

    switch_html, switch_js = _switch_html(style) if switchable else ("", "")
    switch_css = _SWITCH_CSS if switchable else ""
    theme = f"t-{style}"

    store_display = _pretty_store(store_name)
    if store_display.isdigit():
        store_display = ""
    store = f" · {_esc(store_display)}" if store_display else ""

    total = float(summary.get("total") or 0)
    source = str(summary.get("source") or "menu-price")

    # 大字 = 应付合计；签名条 = 这单燃料
    signature_html = ""
    fuel_parts = []
    if summary.get("protein") is not None:
        fuel_parts.append(f"{summary['protein']}g 蛋白")
    if summary.get("kcal") is not None:
        fuel_parts.append(f"{summary['kcal']} 大卡")
    if summary.get("protein_per_yuan"):
        fuel_parts.append(f"每元 {summary['protein_per_yuan']}g 蛋白")
    if fuel_parts:
        signature_html = f'<div class="signature">这一单 = {" · ".join(fuel_parts)}</div>'

    src_note = str(summary.get("note") or "")
    if source == "calculate-price":
        src_html = (
            '<div class="od-src"><b>实时计价</b> —— 价格含门店当期活动，'
            "以下单页为准。点餐单不产生订单，付款在官方 App/到店完成。</div>"
        )
    else:
        src_html = (
            f'<div class="od-src"><b>按菜单标价合计</b> —— '
            f"{_esc(src_note) or '实时计价未成功'}"
            f"促销与优惠券以门店为准。</div>"
        )

    rows = []
    for line in summary.get("lines", ()):
        rows.append(
            f'<div class="od-row">'
            f'<div class="od-top">'
            f'<span class="od-qty">{line.quantity}×</span>'
            f'<span class="od-name">{_esc(line.name)}</span>'
            f'<span class="od-price">¥{line.unit_price * line.quantity:.1f}</span>'
            f"</div>"
            f"</div>"
        )
    rows_html = "".join(rows)

    gap_html = _coverage_html(index)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>点餐单 · ¥{total:.1f}</title>
<style>{_CARD_CSS}{switch_css}</style>
</head>
<body class="{theme}">
{switch_html}<div class="card {theme}">
  <div class="strip">
    <div class="m-badge">M</div>
    <div class="strip-name">麦门食验室</div>
    <div class="strip-tag">点餐单</div>
  </div>

  <div class="hero">
    <div class="eyebrow">点餐单 · 实时计价{store}</div>
    <div class="champ">¥{total:.1f}</div>
    {signature_html}
    <div class="champ-sub">共 {len(summary.get("lines", ()))} 项 · 拿这张单到店/在 App 直接点</div>
  </div>

  <div class="od">
    <div class="od-head">
      <span class="od-title">菜单明细</span>
      <span class="od-note">{_esc("实时计价" if source == "calculate-price" else "菜单标价")}</span>
    </div>
    {rows_html}
  </div>
  {src_html}
  {gap_html}

  {_footer_html(project_url)}
</div>
{switch_js}</body>
</html>"""
