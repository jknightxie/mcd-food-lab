"""每元营养效率指数。

把两处互不相干的官方数据接在一起：

  `list-nutrition-foods` → 全国通用营养库（热量/蛋白/脂肪/碳水/钠/钙）
  `query-meals`         → 门店实时菜单 +真实价格

两者做除法，得到「每元钱能买到多少营养」。

为什么要做这个除法：营养库和菜单各自都能拿到，但把营养除以价格
之后，才会出现一个反直觉的结论 —— 巨无霸不是麦当劳蛋白质性价比
最高的汉堡，而 14 元的那么大鸡排才是。

三条不可让步的边界：

1. **覆盖率必须报出来。** 营养库是全国固定的，菜单是单店实时的，
   两者必然不同步。匹配率通常只有 18% 左右，藏起来等于骗人。
2. **缺失 ≠ 0。** 没有价格或没有营养值的餐品直接排除，并计入未覆盖
   清单，绝不当作 0 参与排序。
3. **异常值原样输出 + 标注可疑。** 不静默删除，也不替官方判断对错。
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "Nutrition",
    "MenuItem",
    "FuelItem",
    "Metric",
    "Scenario",
    "FuelIndex",
    "parse_nutrition",
    "parse_menu",
    "build_index",
    "SCENARIOS",
    "METRICS",
    "recommend",
    "render_decision_table",
    "render_report",
]

# ── 营养库解析 ──────────────────────────────────────────────────────────

# 服务端返回的不是 JSON，而是一种紧凑表头 + 换行分隔的格式：
#   [160]{productName,energyKcal,protein,...}:
#   猪柳麦满分,null,308,16,16,24,781,213
_NUTRITION_HEADER = re.compile(r"\[(\d+)\]\{([^}]*)\}\s*:\s*(.*)", re.S)

# 餐品名里的规格后缀在营养库和菜单两边写法不一致，比对时先剥掉。
#
# 规格后缀 = 名字**末尾**一段成对括号（全/半角圆括号、方括号、书名号）。
# 两条硬约束缺一不可：
#
#   1. **必须锚定在末尾。** 曾经写的是 `[（(【\[(（].*` —— 没有锚定，且 `.*`
#      贪婪，会把「【美汁源】“多汁柠柠”」从**第一个** 【 一路吃到行尾，
#      塌成空串；于是在 `by_core` 里与「【美汁源】“黄金橙橙”」互相覆盖，
#      柠柠吃到了橙橙的营养值（实测 165 kcal）。品牌方括号出现在名字
#      **开头**，它不是规格后缀，不该被剥。
#   2. **剥完不能是空串。** 否则「（椒盐风味）」这种整个名字就是一段括号的
#      条目也会塌成 `""`，再去 `by_core` 里和别的条目互相覆盖。剥空即说明
#      它不满足「名字 + 后缀」结构，应当原样返回。
_SPEC_SUFFIX = re.compile(r"(?:\s*[（(\[【][^（()）\[\]【】]*[）)\]】])+\s*$")


def _strip_spec(name: str) -> str:
    """去掉**末尾**的规格后缀，让「那么大鸡排（椒盐风味）」能匹配上「那么大鸡排」。

    只剥行尾的成对括号段；剥完为空则原样返回 —— 空串会让 `by_core` 里所有
    「整个名字就是一段括号」的条目互相覆盖，把一个单品的营养值串到另一个上。
    """
    stripped = _SPEC_SUFFIX.sub("", name).strip()
    return stripped or name


@dataclass(frozen=True)
class Nutrition:
    """一个餐品的营养值。注意字段单位：热量是 kcal，钠和钙是 mg。"""

    name: str
    energy_kcal: float | None = None
    protein: float | None = None
    fat: float | None = None
    carbohydrate: float | None = None
    sodium: float | None = None
    calcium: float | None = None

    @property
    def macro_kcal(self) -> float | None:
        """由宏量营养素反推的热量：4+4+4 kcal/g。

        用于校验标注的热量是否自洽。任一宏量为空则无法校验。
        """
        if None in (self.protein, self.fat, self.carbohydrate):
            return None
        return 4 * self.protein + 4 * self.fat + 4 * self.carbohydrate


def _to_float(raw: Any) -> float | None:
    text = str(raw).strip()
    if not text or text == "null":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_nutrition(raw: Any) -> dict[str, Nutrition]:
    """解析 `list-nutrition-foods` 的紧凑文本格式。

    实测 160 条全部可解析。字段顺序由表头声明，不做硬编码。
    """
    text = raw if isinstance(raw, str) else str(raw)
    match = _NUTRITION_HEADER.match(text)
    if not match:
        raise ValueError("营养库返回格式无法识别，无法解析")

    columns = [c.strip() for c in match.group(2).split(",")]
    body = match.group(3).strip()

    out: dict[str, Nutrition] = {}
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(columns):
            continue  # 字段数对不上的行直接丢弃，不猜测对齐
        row = dict(zip(columns, parts))
        name = row.get("productName", "").strip()
        if not name:
            continue
        out[name] = Nutrition(
            name=name,
            energy_kcal=_to_float(row.get("energyKcal")),
            protein=_to_float(row.get("protein")),
            fat=_to_float(row.get("fat")),
            carbohydrate=_to_float(row.get("carbohydrate")),
            sodium=_to_float(row.get("sodium")),
            calcium=_to_float(row.get("calcium")),
        )
    return out


# ── 菜单解析 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MenuItem:
    """门店实时在售条目。价格字段实测是字符串型的「元」。"""

    code: str
    name: str
    price: float | None = None


def parse_menu(raw: Any) -> list[MenuItem]:
    """解析 `query-meals`，返回门店在售条目。"""
    meals = raw.get("meals") if isinstance(raw, dict) else None
    if not isinstance(meals, dict):
        return []

    out: list[MenuItem] = []
    for code, item in meals.items():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            MenuItem(
                code=str(code),
                name=name,
                price=_to_float(item.get("currentPrice")),
            )
        )
    return out


# ── 效率计算 ────────────────────────────────────────────────────────────

# 粗分类，仅用于「同类比较」时的异常标注。不参与排序。
_CATEGORY_HINTS = (
    ("牛堡", ("安格斯", "牛堡", "厚牛", "吉士汉堡包")),
    ("麦满分", ("麦满分",)),
    ("鸡", ("鸡腿", "鸡排", "脆汁鸡", "琵琶腿", "鸡块", "V翅", "鸡翅")),
    ("鱼", ("鱼",)),
    ("饮品", ("美式", "红茶", "茶", "咖啡", "牛奶", "可乐", "橙汁", "柠柠", "纯悦", "雪碧")),
    ("小食", ("薯条", "玉米", "派", "球", "新地", "旋风", "布丁", "苹果片")),
)


def _category(name: str) -> str:
    for label, hints in _CATEGORY_HINTS:
        if any(h in name for h in hints):
            return label
    return "其他"


@dataclass(frozen=True)
class FuelItem:
    """一个同时具备营养值与价格的餐品 —— 能参与排序的最小单位。

    `code` 是菜单里的 productCode：点餐链路（calculate-price）必须靠它
    定位商品 —— 菜单 key 与名称在套餐/规格场景下对不上号。
    """

    name: str
    price: float
    nutrition: Nutrition
    code: str = ""
    coverage_note: str = ""

    # 每元效率：全部为「每 1 元」口径，不做 ×100 之类的缩放
    @property
    def protein_per_yuan(self) -> float | None:
        return _divide(self.nutrition.protein, self.price)

    @property
    def kcal_per_yuan(self) -> float | None:
        return _divide(self.nutrition.energy_kcal, self.price)

    @property
    def calcium_per_yuan(self) -> float | None:
        return _divide(self.nutrition.calcium, self.price)

    @property
    def fat_per_yuan(self) -> float | None:
        return _divide(self.nutrition.fat, self.price)

    @property
    def carb_per_yuan(self) -> float | None:
        return _divide(self.nutrition.carbohydrate, self.price)

    @property
    def carb_to_protein(self) -> float | None:
        """碳水 / 蛋白质 比值 —— 官方营养库**没有糖字段**时的替代视角。

        碳水不等于糖（淀粉也计入），所以这个比值**不是含糖量**。

        但它揭示了一个实测发现：真甜品的比值远高于正餐。

            圆筒冰淇淋   14 ÷ 2 = 7.0    热量几乎全来自碳水
            草莓麦旋风   47 ÷ 6 = 7.8
            双层吉士汉堡 31 ÷ 27 = 1.1   热量主要来自蛋白质
            薄皮焦香V翅  6 ÷ 17 = 0.4    蛋白质密度最高

        因此这个比值是**判定一份餐「是饭还是甜品」的有效信号**。

        重要背景：实测 20 款可推荐餐品里，比值超过 4 的只有 1 款。
        原因不是这条判据不准，而是**19% 的覆盖率已经把绝大多数甜品
        挡在了推荐池之外** —— 朱古力新地、草莓新地、麦旋风、香芋派
        全部因为「菜单有、营养库无」而无法参与计算。

        所以「推荐里看不到甜品」这件事，是数据覆盖率的自然结果，
        不是本工具的过滤功劳。这个区别在对外表述时必须说清。
        """
        carb = self.nutrition.carbohydrate
        protein = self.nutrition.protein
        if carb is None or protein is None or protein <= 0:
            return None
        return carb / protein

    @property
    def sodium_per_yuan(self) -> float | None:
        return _divide(self.nutrition.sodium, self.price)

    @property
    def category(self) -> str:
        return _category(self.name)

    @property
    def kcal(self) -> float | None:
        return self.nutrition.energy_kcal

    @property
    def protein(self) -> float | None:
        return self.nutrition.protein

    @property
    def sodium(self) -> float | None:
        return self.nutrition.sodium

    @property
    def calcium(self) -> float | None:
        return self.nutrition.calcium

    def suspect(self, category_median_kcal: float | None) -> str:
        """标注可疑值，但**不下结论说它错了**。

        两种情况会命中：
        1. 宏量营养素反推的热量与标注热量偏差过大 —— 数据内部不自洽
        2. 热量显著高于同类中位数 —— 官方数据，但同品类里显得突兀

        官方营养库里「芝士双层安格斯厚牛堡 1003 kcal」显著高于同类
        （697~707）。我们没有依据判定它是错的，因此只标注。
        """
        macro = self.nutrition.macro_kcal
        if macro and self.kcal and self.kcal > 50:
            deviation = abs(macro - self.kcal) / self.kcal
            if deviation > 0.35:
                return "官方数据，宏量营养素与热量标注不自洽，建议以实际包装为准"

        if category_median_kcal and self.kcal:
            if self.kcal > category_median_kcal * 1.4:
                return (
                    f"官方数据，热量高于同类中位数"
                    f"（{category_median_kcal:.0f} kcal）较多，建议以实际包装为准"
                )
        return ""

    def metric(self, key: str) -> float | None:
        return getattr(self, key, None)


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class FuelIndex:
    """一次完整的分析结果。"""

    items: tuple[FuelItem, ...]
    menu_total: int
    matched: int
    unmatched_names: tuple[str, ...] = field(default_factory=tuple)
    nutrition_total: int = 0

    @property
    def coverage(self) -> float:
        """营养库覆盖了多少款在售餐品。必须报出来。"""
        if not self.menu_total:
            return 0.0
        return self.matched / self.menu_total * 100

    @property
    def coverage_note(self) -> str:
        return (
            f"{self.menu_total} 款在售餐品中，官方营养库覆盖 {self.matched} 款"
            f"（{self.coverage:.0f}%）"
        )

    def by(self, key: str, desc: bool = True) -> list[FuelItem]:
        """按某个每元指标排序，None 值永远排在最后而不是当作 0。"""
        scored = [i for i in self.items if i.metric(key) is not None]
        missing = [i for i in self.items if i.metric(key) is None]
        scored.sort(key=lambda i: i.metric(key), reverse=desc)
        return scored + missing


def build_index(
    menu_raw: Any, nutrition_raw: Any
) -> FuelIndex:
    """核心：把营养库和菜单接起来，算出每元效率。

    匹配策略：先精确同名，再退到「剥掉规格后缀」的名字。
    仍然匹配不上的，记入未覆盖清单 —— 不猜、不填。
    """
    nutrition = parse_nutrition(nutrition_raw)
    menu = parse_menu(menu_raw)

    by_name = {n.name: n for n in nutrition.values()}
    by_core: dict[str, Nutrition] = {}
    for n in nutrition.values():
        core = _strip_spec(n.name)
        # 空 core 会让所有「整个名字就是一段括号」的条目挤在同一个键上，
        # 互相覆盖、串出别人的营养值。宁可让它们匹配不上（进未覆盖清单），
        # 也不能让它们匹配错。
        if core:
            by_core.setdefault(core, n)

    items: list[FuelItem] = []
    unmatched: list[str] = []

    for entry in menu:
        if entry.price is None or entry.price <= 0:
            unmatched.append(entry.name)
            continue
        nutri = by_name.get(entry.name) or by_core.get(_strip_spec(entry.name))
        if nutri is None or nutri.energy_kcal is None:
            unmatched.append(entry.name)
            continue
        items.append(
            FuelItem(
                name=entry.name, price=entry.price, nutrition=nutri, code=entry.code
            )
        )

    return FuelIndex(
        items=tuple(items),
        menu_total=len(menu),
        matched=len(items),
        unmatched_names=tuple(unmatched),
        nutrition_total=len(nutrition),
    )


def _category_medians(items: Iterable[FuelItem]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for item in items:
        if item.kcal:
            buckets.setdefault(item.category, []).append(item.kcal)
    return {k: statistics.median(v) for k, v in buckets.items() if len(v) >= 2}


# ── 问卷场景 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Metric:
    """一个可排序的效率指标。"""

    key: str
    label: str
    unit: str
    higher_is_better: bool
    tier: str  # base=大众层 / pro=进阶层


METRICS: tuple[Metric, ...] = (
    Metric("protein_per_yuan", "蛋白质", "g/元", True, "base"),
    Metric("kcal_per_yuan", "热量", "kcal/元", False, "base"),
    Metric("calcium_per_yuan", "钙", "mg/元", True, "base"),
    # 碳水/元：越高越好，用于「犒劳自己」。疲惫时要的是**供能**，
    # 碳水是最快的那一份；而低热量会让疲惫更明显，方向反过来就是错的。
    Metric("carb_per_yuan", "碳水", "g/元", True, "base"),
    Metric("sodium_per_yuan", "钠", "mg/元", False, "pro"),
    Metric("fat_per_yuan", "脂肪", "g/元", False, "pro"),
    # 价格（排面）：只用于「请客」。请客的效用函数不是性价比——
    # 是拿得出手。按价格档位从高到低选排面担当，
    # 每元效率降级为参考信息（卡片上照常显示）。
    # 另外「管住嘴」拿脂肪/元 当主指标，所以脂肪也进主表口径。
    Metric("price", "价格", "元", True, "base"),
)


@dataclass(frozen=True)
class Scenario:
    """问卷的一个选项。每个选项都必须绑定一组维度。

    「不许真的脱钩」是硬要求：如果选项和营养数据无关，问卷就退化成
    娱乐小游戏，丢掉整个项目的护城河。

    关键设计：**每个场景至少两个约束**。
    单一指标排序必然推出极端值 —— 只按热量排，冠军是零卡饮料；
    只按钙排，冠军是冰淇淋。那不是「解馋」和「给小孩」的答案。

    约束之间用 `tradeoff` 指明方向：一个主指标（要最优），加上一个
    边界指标（不能超过某个水平），或者两个都要好。
    """

    key: str
    label: str
    prompt: str
    primary: str  # 主指标，按此排序
    guard: str | None = None  # 边界指标，低于门槛的先出局
    guard_min: float | None = None  # 守卫指标的最低门槛
    guard_unit: str = ""  # 门槛的单位，用于文案
    tier: str = "base"

    @property
    def metric(self) -> str:
        """兼容旧接口：主指标即该场景的核心指标。"""
        return self.primary


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="craving",
        label="解馋",
        prompt="今天这顿想干什么？",
        primary="kcal_per_yuan",
        guard="protein_per_yuan",
        guard_min=0.4,
        guard_unit="g/元",
    ),
    Scenario(
        key="discipline",
        label="管住嘴",
        prompt="今天这顿想干什么？",
        # 「少油」是这个场景答案词表里的原话，它的量化就是「每元买到的脂肪
        # 最少」。别再按蛋白质/元 排 —— 那和「今天在练」是**同一条排序**，
        # 两个场景必然推出同一个冠军，问卷就退化成装饰品（铁律⑥）。
        primary="fat_per_yuan",
        guard="protein_per_yuan",
        guard_min=0.5,
        guard_unit="g/元",
    ),
    Scenario(
        key="host",
        label="请客",
        prompt="今天这顿想干什么？",
        # 请客的效用函数不是性价比——是排面。按价格档位从高到低选
        # 「拿得出手」的；守卫仍挡住蛋白过低的（冰淇淋/饮料撑不住场面）。
        # 每元效率在卡片上照常显示，但降级为参考，不作排序依据。
        primary="price",
        guard="protein_per_yuan",
        guard_min=0.8,
        guard_unit="g/元",
    ),
    Scenario(
        key="kid",
        label="给小孩",
        prompt="今天这顿想干什么？",
        primary="calcium_per_yuan",
        guard="protein_per_yuan",
        guard_min=0.5,
        guard_unit="g/元",
    ),
    Scenario(
        key="training",
        label="今天在练",
        prompt="今天这顿想干什么？",
        # 蛋白质/元 是本项目的主论据，所以「练后」独占这条排序。
        # **不设守卫**：这一项的极值本身就是答案（每元蛋白最多），
        # 不存在需要被挡住的极端值。
        # 曾经写死 `guard="sodium_per_yuan", guard_min=0.0` —— 钠/元 不可能为负，
        # 那是一个永远筛不掉任何东西的空守卫，纯装饰代码。删掉。
        primary="protein_per_yuan",
        tier="pro",
    ),
    Scenario(
        key="comfort",
        label="犒劳自己",
        prompt="今天这顿想干什么？",
        # 疲惫时不能按「低热量」排 —— 那会让疲惫更明显。
        # 需要的是**碳水供能 + 蛋白续航**（本场景答案词表里早已写下的营养
        # 依据），所以按碳水/元 排，越高越好，并要求有蛋白兜底。
        # 曾经用 `energy_density`（= 总热量/元）：它和 `kcal_per_yuan` 是
        # 同一个数、相反方向，而它的冠军与「今天在练」撞车（都是那么大鸡排）。
        # 改用碳水后这个重复定义的指标已无消费者，一并删除。
        primary="carb_per_yuan",
        guard="protein_per_yuan",
        guard_min=0.5,
        guard_unit="g/元",
    ),
)


def recommend(
    index: FuelIndex, scenario_key: str, top: int = 5
) -> list[FuelItem]:
    """按场景给出推荐。

    两步：先用 `guard` 门槛筛掉「不该出现在这个场景」的东西，
    再按 `primary` 排序。

    守卫门槛不可达时不返回空 —— 那会让用户以为没得选。此时退化为
    只按主指标排序，并在结果里说明（由render_report 负责措辞）。
    """
    scenario = next((s for s in SCENARIOS if s.key == scenario_key), None)
    if scenario is None or not index.items:
        return []

    metric = next((m for m in METRICS if m.key == scenario.primary), None)
    if metric is None:
        return []

    candidates = list(index.items)

    if scenario.guard is not None and scenario.guard_min is not None:
        kept = [
            i
            for i in candidates
            if i.metric(scenario.guard) is not None
            and i.metric(scenario.guard) >= scenario.guard_min
        ]
        if kept:
            candidates = kept

    scored = [i for i in candidates if i.metric(scenario.primary) is not None]
    missing = [i for i in candidates if i.metric(scenario.primary) is None]
    scored.sort(key=lambda i: i.metric(scenario.primary), reverse=metric.higher_is_better)
    return scored[:top] + missing


# ── 输出 ────────────────────────────────────────────────────────────────


def render_decision_table(
    index: FuelIndex,
    items: list[FuelItem],
    show_pro: bool = False,
    sort_by: str | None = None,
) -> str:
    """决策表：核心列恒定显示，场景指标**追加**而非替换。

    **「蛋白质/元」是本工具的核心卖点，任何场景下都不能消失。**
    早期版本让最后一列跟随排序指标变化，结果「犒劳自己」场景
    把核心列挤成了排序指标本身 —— 用户看到的就是「我的卖点呢？」。

    所以现在的规则：
    - 基础六列恒定：餐品 · 价格 · 热量 · 蛋白质 · 钙 · **蛋白质/元**
    - 场景排序指标若不在基础列里（如碳水/元、脂肪/元），**追加到末尾**
    - `sort_by` 只决定行的**顺序**，不决定显示哪些列
    """
    if not items:
        return "（无可推荐的餐品）"

    # 核心卖点：每元效率的三个基础指标，任何场景都显示
    core = ("protein_per_yuan", "calcium_per_yuan", "kcal_per_yuan")
    metric_map = {m.key: m for m in METRICS}

    extra_key = sort_by if sort_by and sort_by not in core else None
    sort_key = extra_key or "protein_per_yuan"

    headers = ["餐品", "价格", "热量", "蛋白质", "钙", "蛋白质/元"]
    if show_pro:
        headers += ["钠", "脂肪"]
    if extra_key:
        extra_metric = metric_map[extra_key]
        headers.append(f"{extra_metric.label}/{extra_metric.unit}")

    widths = [26, 9, 8, 9, 8, 13]
    if show_pro:
        widths += [8, 8]
    if extra_key:
        widths.append(max(14, len(headers[-1]) + 2))

    lines = [
        "  ".join(
            _pad(h, w, right=(i > 0)) for i, (h, w) in enumerate(zip(headers, widths))
        ),
        "  ".join("─" * w for w in widths),
    ]

    medians = _category_medians(index.items)
    for item in items:
        row = [
            _trunc(item.name, widths[0]),
            f"{item.price:.1f}元",
            _fmt(item.kcal),
            _fmt(item.protein),
            _fmt(item.calcium),
            _fmt(item.metric("protein_per_yuan"), 2),
        ]
        if show_pro:
            row += [_fmt(item.sodium), _fmt(item.nutrition.fat)]
        if extra_key:
            row.append(_fmt(item.metric(extra_key), 2))
        lines.append(
            "  ".join(
                _pad(c, w, right=(i > 0))
                for i, (c, w) in enumerate(zip(row, widths))
            )
        )

    for item in items:
        note = item.suspect(medians.get(item.category))
        if note:
            lines.append(f"  ⚠ {item.name}：{note}")
    return "\n".join(lines)


def _trunc(text: str, width: int) -> str:
    """按显示宽度截断，超出部分用省略号。"""
    if _display_width(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used + w > width - 1:
            return out + "…"
        out += ch
        used += w
    return out


def _fmt(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _display_width(text: str) -> int:
    """字符串在等宽终端里占的列数。

    中文、日文、韩文是**全角**，占 2 列；而Python 的 `len()` 只算1。
    表格对齐必须用这个，否则中文列会整体撑宽 2 格，
    后面每一列都错位 —— 表现为「数字对不上表头」。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    """按显示宽度补齐到指定列数。"""
    gap = max(0, width - _display_width(text))
    return (" " * gap + text) if right else (text + " " * gap)


def render_report(index: FuelIndex, scenario_key: str) -> str:
    """完整报告：先说边界，再给答案。"""
    scenario = next((s for s in SCENARIOS if s.key == scenario_key), None)
    top = recommend(index, scenario_key) if scenario else []

    lines = [index.coverage_note, ""]
    if index.unmatched_names:
        preview = "、".join(index.unmatched_names[:4])
        more = (
            f" 等 {len(index.unmatched_names)} 款"
            if len(index.unmatched_names) > 4
            else ""
        )
        lines.append(f"  未覆盖：{preview}{more}")
        lines.append("  这些餐品官方营养库里查不到，营养标注本身就不完整，")
        lines.append("  不参与推荐 —— 不拿估算值凑数。")
    lines.append("")

    if scenario:
        primary = next((m for m in METRICS if m.key == scenario.primary), None)
        arrow = "↓" if primary and not primary.higher_is_better else "↑"
        lines.append(f"「{scenario.label}」— 按{primary.label} {arrow} 排序")
        if scenario.guard and scenario.guard_min:
            guard = next((m for m in METRICS if m.key == scenario.guard), None)
            if guard:
                lines.append(
                    f"（已滤掉{guard.label}低于 {scenario.guard_min}"
                    f"{scenario.guard_unit} 的：那些不算{scenario.label}）"
                )
        lines.append("")
        lines.append(
            render_decision_table(
                index, top, show_pro=scenario.tier == "pro", sort_by=scenario.primary
            )
        )
    return "\n".join(lines)


def _metric_label(key: str) -> str:
    for m in METRICS:
        if m.key == key:
            return m.label
    return key


# ── 问卷入口 ────────────────────────────────────────────────────────────

# 用户可能怎么回答。键是**用户说的话**，值是场景 key。
# 一个场景可以对应多种说法 —— 用户不会按我们的选项名称作答。
_ANSWER_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "craving",
        (
            "解馋", "馋", "嘴馋", "想吃", "过瘾", "随便吃",
            # 「想吃有肉的」—— 这里的真实意图是蛋白质，不是泛泛的嘴馋。
            # 「想吃」只是描述行为，「有肉 / 好吃 / 满足」才说明要什么。
            #注意：「犒劳」属于 comfort 场景，不放这里 ——
            # 「犒劳自己」是疲惫时想补充能量，与「解馋」是两个需求。
            "有肉", "想吃肉", "好吃", "满足", "放开", "别管了",
        ),
    ),
    (
        "discipline",
        (
            "管住嘴", "克制", "自律", "控制", "减肥", "少油", "要健康",
            "别吃太多", "低热量", "清淡",
        ),
    ),
    (
        "host",
        ("请客", "招待", "客人", "朋友来", "同事", "分享", "聚餐", "体面"),
    ),
    (
        "kid",
        ("小孩", "孩子", "小朋友", "儿子", "女儿", "带娃", "宝宝", "儿童"),
    ),
    (
        "training",
        (
            "今天在练", "健身", "训练", "运动", "增肌", "减脂", "练完", "撸铁",
            "跑了", "游泳", "瑜伽", "举铁", "塑形",
        ),
    ),
    (
        # 疲惫/情绪低落时想要「安慰性食物」——这是真实且高频的需求。
        # 营养依据：这时需要的是碳水供能 + 蛋白续航，
        # 而不是低热量（低热量会让疲惫更明显）。
        "comfort",
        (
            "犒劳", "犒劳自己", "安慰",
            "累", "疲惫", "好累", "累死", "没力气", "撑不住", "加班", "熬夜",
            "没胃口", "焦虑", "烦", "压力大", "难过", "emo", "低落",
            "感冒", "生病", "不舒服", "心情不好",
        ),
    ),
)

# 关键词冲突时的优先级，从高到低。
#
# 这不是随意排序。同一句话常同时命中多个场景：
#「今天刚练完，想吃点东西」既含「训练」也含「想吃」。
#
# 判定原则：**信息量更具体的一方优先。**
# 「刚练完」明确交代了场景，「想吃」只是描述行为 —— 后者可以配任何场景。
# 所以运动词优先于口味词，带娃词优先于运动词（带娃同时约束热量与钠）。
_SCAN_ORDER = ("kid", "training", "comfort", "discipline", "host", "craving")


def resolve_answer(text: str) -> str | None:
    """把一句自然语言回答映射到场景 key。无法判断时返回 None。

    这是「问卷」真正落地的地方 —— `Scenario.prompt` 只是文案，
    提问的动作由调用方（Skill 编排层或 CLI）发出，
    而**回答到场景的映射逻辑在本函数**，保证口径一致。
    """
    if not text:
        return None
    for scenario_key in _SCAN_ORDER:
        for key, patterns in _ANSWER_PATTERNS:
            if key != scenario_key:
                continue
            for pattern in patterns:
                if pattern in text:
                    return key
    return None


def build_question() -> str:
    """生成提问文案 —— **只问，不列选项**。

    只问「今天这顿想干什么？」然后停下来。列选项是兜底行为，
    见 `build_options()`。

    理由：问的是意图，回答空间就该开放。一旦摆出五个标签，
    用户会进入「挑标签」模式 —— 「我今天很累，想吃点有肉的」
    这种回答会被迫映射到「管住嘴」，然后拿到一份健身餐。
    **选项会限制表达。**
    """
    return SCENARIOS[0].prompt if SCENARIOS else "今天这顿想干什么？"


def build_options() -> str:
    """五个选项的兜底文案。

    **只在用户答不上来时使用。** 第一次提问绝不列选项。
    """
    options = " / ".join(
        f"{s.label}{'（进阶层）' if s.tier == 'pro' else ''}" for s in SCENARIOS
    )
    return f"可选：{options}"