"""fuel_index.py 单元测试。

fixture 分两类：
1. **真实样本** —— 2026-10-12 对 mcp.mcd.cn 的实际响应（营养库文本截取、
   门店菜单字段结构）
2. **构造样本** —— 专门构造边界情形（缺失值、脏数据、零价格）

菜单部分刻意用构造数据：真实菜单含 104 项且随门店变动，
构造一个可控的小菜单才能对排序结果做精确断言。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fuel_index import (  # noqa: E402
    METRICS,
    SCENARIOS,
    FuelIndex,
    Nutrition,
    _strip_spec,
    build_index,
    parse_menu,
    parse_nutrition,
    recommend,
    render_decision_table,
    render_report,
)

# 演示页用的那份真实门店快照 —— 冻结在仓库里，零网络可复现
SNAPSHOT = Path(__file__).resolve().parent.parent / "assets" / "snapshot.json"


def load_snapshot_index() -> FuelIndex:
    """加载 `assets/snapshot.json` 构建索引。"""
    import json

    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return build_index(raw["menu"], raw["nutrition"])

# ── 真实营养库样本（从 tools/list 实测响应截取，格式逐字保留）──────────

REAL_NUTRITION = (
    "[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,"
    "carbohydrate,sodium,calcium}:\n"
    "猪柳麦满分,null,1288,308,16,16,24,781,213\n"
    "双层吉士汉堡,null,1796,429,27,22,31,1017,232\n"
    "巨无霸,null,2151,513,27,25,43,961,171\n"
    "板烧鸡腿堡,null,1637,391,23,18,34,1041,120\n"
    "那么大鸡排（椒盐风味）,null,1611,385,24,17,31,996,60\n"
    "麦辣鸡腿汉堡,null,2033,485,24,23,42,1208,90\n"
    "芝士安格斯厚牛堡,null,2917,696,32,42,44,897,150\n"
    "培根安格斯厚牛堡,null,2961,707,34,44,42,1037,161\n"
    "双层深海鳕鱼堡,null,2032,485,28,21,40,917,140\n"
    "纯牛奶（盒装）,null,540,129,7,7,10,73,231\n"
    "冰美式小杯,null,42,10,1,0,1,0,0\n"
    "锡兰红茶,null,8,2,0,0,0,0,0\n"
    "麦香鸡,null,1546,369,15,17,39,731,73\n"
    "薄皮焦香V翅,null,805,192,17,11,6,594,15\n"
    "圆筒冰淇淋,null,391,93,2,3,14,36,77\n"
    "脆薯饼,null,0,null,null,null,null,null,null\n"
)


def menu(items):
    """构造菜单响应：items 为 (code, name, price) 三元组列表。"""
    return {
        "meals": {
            code: {"name": name, "currentPrice": price, "tags": []}
            for code, name, price in items
        }
    }


# 真实门店（建外SOHO）实测可匹配的那几款，名称与价格逐字照抄
REAL_MATCHED = [
    ("M1", "那么大鸡排（椒盐风味）", "14"),
    ("M2", "双层吉士汉堡", "23"),
    ("M3", "双层深海鳕鱼堡", "24"),
    ("M4", "麦辣鸡腿汉堡", "22.5"),
    ("M5", "巨无霸", "25.5"),
    ("M6", "芝士安格斯厚牛堡", "31.5"),
    ("M7", "培根安格斯厚牛堡", "34.5"),
    ("M8", "纯牛奶(盒装)", "10.5"),
    ("M9", "冰美式小杯", "5"),
    ("M10", "锡兰红茶", "11.5"),
    # 菜单有、营养库没有的（真实情况：覆盖率约 18%）
    ("M11", "麦辣鸡翅", "19.5"),
    ("M12", "心形薯饼5块", "9"),
    # 用于测试碳水/蛋白比判定甜食型
    ("M13", "圆筒冰淇淋", "5"),
    ("M14", "薄皮焦香V翅", "16"),
]


# ── 营养库解析 ──────────────────────────────────────────────────────────


class TestParseNutrition(unittest.TestCase):
    def setUp(self):
        self.n = parse_nutrition(REAL_NUTRITION)

    def test_all_rows_parsed(self):
        self.assertEqual(len(self.n), 16)

    def test_numeric_fields(self):
        d = self.n["巨无霸"]
        self.assertEqual(d.energy_kcal, 513)
        self.assertEqual(d.protein, 27)
        self.assertEqual(d.sodium, 961)
        self.assertEqual(d.calcium, 171)

    def test_name_kept_verbatim_including_suffix(self):
        # 营养库侧保留全名，带规格后缀
        self.assertIn("那么大鸡排（椒盐风味）", self.n)

    def test_null_fields_become_none_not_zero(self):
        d = self.n["脆薯饼"]
        self.assertIsNone(d.energy_kcal)
        self.assertIsNone(d.protein)

    def test_macro_kcal_backcalculation(self):
        d = self.n["冰美式小杯"]
        # 4*1(蛋白) + 4*0(脂肪) + 4*1(碳水) = 8 kcal，与标注 10 差 25%，属正常范围
        self.assertEqual(d.macro_kcal, 8)

    def test_macro_kcal_none_when_incomplete(self):
        self.assertIsNone(self.n["脆薯饼"].macro_kcal)

    def test_bad_format_raises(self):
        with self.assertRaises(ValueError):
            parse_nutrition("这不是营养数据")

    def test_ragged_rows_skipped_not_misaligned(self):
        broken = (
            "[2]{a,b,c}:\n"
            "只有两个字段\n"
            "完整行,1,2\n"
        )
        got = parse_nutrition(broken)
        self.assertEqual(len(got), 0)

    def test_empty_body_returns_empty(self):
        self.assertEqual(parse_nutrition("[0]{a,b}:\n"), {})


# ── 菜单解析 ────────────────────────────────────────────────────────────


class TestParseMenu(unittest.TestCase):
    def test_real_matched_items(self):
        m = parse_menu(menu(REAL_MATCHED))
        self.assertEqual(len(m), 14)
        by_name = {i.name: i for i in m}
        self.assertEqual(by_name["巨无霸"].price, 25.5)

    def test_price_string_converted_to_float(self):
        m = parse_menu(menu([("X", "某堡", "22.5")]))
        self.assertIsInstance(m[0].price, float)

    def test_missing_price_is_none(self):
        m = parse_menu(menu([("X", "某堡", "")]))
        self.assertIsNone(m[0].price)

    def test_malformed_meals_returns_empty(self):
        self.assertEqual(parse_menu({"meals": None}), [])
        self.assertEqual(parse_menu("nope"), [])


# ── 索引构建 ────────────────────────────────────────────────────────────


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.idx = build_index(menu(REAL_MATCHED), REAL_NUTRITION)

    def test_matches_by_exact_name(self):
        names = {i.name for i in self.idx.items}
        self.assertIn("巨无霸", names)

    def test_matches_by_stripped_spec(self):
        # 菜单「纯牛奶(盒装)」vs 营养库「纯牛奶（盒装）」—— 括号全半角不同
        self.assertIn("纯牛奶(盒装)", {i.name for i in self.idx.items})

    def test_matches_full_name_with_suffix(self):
        self.assertIn("那么大鸡排（椒盐风味）", {i.name for i in self.idx.items})

    def test_unmatched_recorded_not_dropped_silently(self):
        self.assertIn("麦辣鸡翅", self.idx.unmatched_names)
        self.assertIn("心形薯饼5块", self.idx.unmatched_names)

    def test_coverage_is_reported(self):
        # 14 款菜单，12 款可匹配（麦辣鸡翅、心形薯饼 未命中）
        self.assertEqual(self.idx.matched, 12)
        self.assertEqual(self.idx.menu_total, 14)
        self.assertAlmostEqual(self.idx.coverage, 12 / 14 * 100, places=3)

    def test_zero_price_excluded_not_crashed(self):
        idx = build_index(menu([("A", "巨无霸", "0"), ("B", "麦香鸡", "17")]), REAL_NUTRITION)
        self.assertEqual(len(idx.items), 1)
        self.assertIn("巨无霸", idx.unmatched_names)

    def test_nutrition_without_energy_excluded(self):
        # 脆薯饼营养全为 null，即便在菜单上也不该参与
        idx = build_index(menu([("A", "脆薯饼", "6")]), REAL_NUTRITION)
        self.assertEqual(len(idx.items), 0)


# ── 每元指标 ────────────────────────────────────────────────────────────


class TestPerYuanMetrics(unittest.TestCase):
    def setUp(self):
        self.idx = build_index(menu(REAL_MATCHED), REAL_NUTRITION)
        self.by_name = {i.name: i for i in self.idx.items}

    def test_protein_per_yuan_matches_real_computation(self):
        # 实测：那么大鸡排 24g / ¥14 = 1.71
        item = self.by_name["那么大鸡排（椒盐风味）"]
        self.assertAlmostEqual(item.protein_per_yuan, 24 / 14, places=6)

    def test_protein_ranking_leader(self):
        top = self.idx.by("protein_per_yuan")[0]
        self.assertEqual(top.name, "那么大鸡排（椒盐风味）")

    def test_chicken_beats_big_mac_on_protein_per_yuan(self):
        """核心传播点：14 元的鸡排比25.5 元的巨无霸蛋白密度高。"""
        chicken = self.by_name["那么大鸡排（椒盐风味）"]
        bigmac = self.by_name["巨无霸"]
        self.assertGreater(
            chicken.protein_per_yuan / bigmac.protein_per_yuan, 1.5
        )
        self.assertLess(chicken.price, bigmac.price)

    def test_calcium_per_yuan(self):
        milk = self.by_name["纯牛奶(盒装)"]
        # 实测 231mg / ¥10.5 = 22 mg/元，全场最高
        self.assertAlmostEqual(milk.calcium_per_yuan, 231 / 10.5, places=3)

    def test_kcal_per_yuan_leader_is_drink(self):
        """反直觉点：热量/元最低的是饮料，不是主餐。"""
        top = self.idx.by("kcal_per_yuan", desc=False)[0]
        self.assertIn(top.name, {"锡兰红茶", "冰美式小杯"})

    def test_none_values_never_treated_as_zero(self):
        idx = build_index(
            menu([("A", "巨无霸", "25.5")]),
            # 只有热量没有钠钙 —— 效率指标必须为 None 而不是 0
            "[1]{productName,energyKcal,protein,sodium,calcium}:\n巨无霸,513,27,,",
        )
        item = idx.items[0]
        self.assertIsNone(item.calcium_per_yuan)
        self.assertIsNone(item.sodium_per_yuan)
        self.assertIsNotNone(item.protein_per_yuan)

    def test_by_sorts_none_last(self):
        idx = build_index(
            menu([("A", "甲", "10"), ("B", "乙", "10")]),
            "[2]{productName,energyKcal,protein,sodium,calcium}:\n甲,500,10,,\n乙,100,1,100,100",
        )
        order = [i.name for i in idx.by("calcium_per_yuan")]
        self.assertEqual(order[0], "乙")
        self.assertEqual(order[-1], "甲")  # 缺钙的排最后，不是 0


# ── 异常标注 ────────────────────────────────────────────────────────────


class TestSuspectFlags(unittest.TestCase):
    def test_macro_inconsistency_flagged(self):
        n = Nutrition("测试", energy_kcal=1000, protein=10, fat=10, carbohydrate=10)
        item = FuelItemFactory(n)
        note = item.suspect(None)
        self.assertIn("不自洽", note)

    def test_self_consistent_not_flagged(self):
        n = Nutrition("测试", energy_kcal=100, protein=10, fat=10, carbohydrate=5)
        item = FuelItemFactory(n)
        self.assertEqual(item.suspect(None), "")

    def test_outlier_above_category_median_flagged(self):
        # 构造「宏量自洽但同类离群」：4×(20+20+350)=1560 kcal，标注与反推一致
        n = Nutrition("测试", energy_kcal=1560, protein=20, fat=20, carbohydrate=350)
        item = FuelItemFactory(n)
        self.assertAlmostEqual(n.macro_kcal, 1560, places=6)  # 先确认自洽
        note = item.suspect(500)
        self.assertIn("同类中位数", note)

    def test_macro_check_takes_precedence_over_outlier(self):
        """自洽性检查优先：既不自洽又离群时，报不自洽。"""
        n = Nutrition("测试", energy_kcal=1400, protein=20, fat=20, carbohydrate=30)
        item = FuelItemFactory(n)
        self.assertIn("不自洽", item.suspect(500))

    def test_never_declares_data_wrong(self):
        """边界：只标注，不替官方判断对错。"""
        n = Nutrition("测试", energy_kcal=1003, protein=34, fat=44, carbohydrate=42)
        item = FuelItemFactory(n)
        note = item.suspect(700)
        self.assertNotIn("错误", note)
        self.assertNotIn("错", note.replace("建议以实际包装为准", ""))

    def test_real_outlier_value_annotated_not_removed(self):
        """实测：芝士双层安格斯厚牛堡 1003 kcal，必须原样出现在结果里。"""
        text = (
            "[3]{productName,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
            "芝士双层安格斯厚牛堡,1003,34,44,42,1500,150\n"
            "双层吉士汉堡,429,27,22,31,1017,232\n"
            "巨无霸,513,27,25,43,961,171\n"
        )
        idx = build_index(
            menu([("A", "芝士双层安格斯厚牛堡", "31.5"), ("B", "双层吉士汉堡", "23"),
                  ("C", "巨无霸", "25.5")]),
            text,
        )
        out = render_decision_table(idx, list(idx.items))
        self.assertIn("芝士双层安格斯厚牛堡", out)  # 还在表里
        self.assertIn("⚠", out)                    # 且被标注
        self.assertIn("建议以实际包装为准", out)


def FuelItemFactory(nutrition: Nutrition):
    from fuel_index import FuelItem
    return FuelItem(name=nutrition.name, price=25.0, nutrition=nutrition)


class TestCarbToProtein(unittest.TestCase):
    """碳水/蛋白比 —— 官方库没有糖字段时的替代判断。

    实测数据：甜品区间 7~9，正餐区间 1~2.2。
    """

    def setUp(self):
        self.idx = build_index(menu(REAL_MATCHED), REAL_NUTRITION)
        self.by_name = {i.name: i for i in self.idx.items}

    def test_dessert_ratio_is_extreme(self):
        # 圆筒冰淇淋：碳水14 / 蛋白2 = 7.0，远高于正餐
        self.assertAlmostEqual(
            self.by_name["圆筒冰淇淋"].carb_to_protein, 7.0, places=2
        )

    def test_meal_ratio_is_much_lower(self):
        # 薄皮焦香V翅：碳水6 / 蛋白17 = 0.35，全场最低
        item = self.by_name["薄皮焦香V翅"]
        self.assertAlmostEqual(item.carb_to_protein, 6 / 17, places=6)

    def test_burger_ratio_near_one(self):
        # 双层吉士汉堡 31/27 ≈ 1.15
        self.assertAlmostEqual(
            self.by_name["双层吉士汉堡"].carb_to_protein, 31 / 27, places=2
        )

    def test_ratio_separates_dessert_from_meal_by_large_margin(self):
        """实测：甜品 7.0 vs 正餐 1.15 —— 差6 倍以上。"""
        dessert = self.by_name["圆筒冰淇淋"].carb_to_protein
        meal = self.by_name["双层吉士汉堡"].carb_to_protein
        self.assertGreater(dessert / meal, 5)

    def test_zero_protein_yields_none_not_infinite(self):
        """零蛋白饮品不能被算成「比值无穷大」，也不能算成 0。"""
        idx = build_index(
            menu([("A", "纯悦", "7.5"), ("B", "巨无霸", "25.5")]),
            "[2]{productName,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
            "纯悦,0,0,0,0,0,0\n巨无霸,513,27,26,42,961,171\n",
        )
        by = {i.name: i for i in idx.items}
        self.assertIsNone(by["纯悦"].carb_to_protein)

    def test_kid_scenario_leader_is_milk(self):
        """实测：纯牛奶钙/元 22.00 全场最高，是「给小孩」的正确冠军。"""
        top = recommend(self.idx, "kid", top=1)
        self.assertEqual(top[0].name, "纯牛奶(盒装)")

    def test_kid_excludes_low_protein_items(self):
        """「给小孩」要有蛋白门槛 —— 冰淇淋钙高但蛋白只有 2g。"""
        top = recommend(self.idx, "kid", top=5)
        for item in top:
            self.assertGreaterEqual(
                item.protein_per_yuan, 0.5, f"{item.name} 蛋白过低"
            )


# ── 场景与推荐 ──────────────────────────────────────────────────────────


class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.idx = build_index(menu(REAL_MATCHED), REAL_NUTRITION)

    def test_all_scenarios_bound_to_a_real_metric(self):
        keys = {m.key for m in METRICS}
        for s in SCENARIOS:
            self.assertIn(s.metric, keys, f"{s.label} 未绑定有效指标")

    def test_no_scenario_is_pure_entertainment(self):
        """边界：每个场景都必须真的连着营养数据。"""
        keys = {m.key for m in METRICS}
        for s in SCENARIOS:
            self.assertIn(s.primary, keys, f"{s.label} 未绑定有效主指标")
            if s.guard:
                self.assertIn(s.guard, keys, f"{s.label} 的守卫指标无效")

    def test_scenarios_with_guard_have_threshold(self):
        """有守卫就必须有门槛，否则守卫等于没设。"""
        for s in SCENARIOS:
            if s.guard:
                self.assertIsNotNone(s.guard_min, f"{s.label} 守卫缺门槛")

    def test_craving_excludes_zero_protein_items(self):
        """「解馋」不能推零蛋白饮料 —— 单指标排序的必然结果，要用守卫挡住。"""
        top = recommend(self.idx, "craving", top=5)
        for item in top:
            self.assertGreaterEqual(
                item.protein_per_yuan, 0.4, f"{item.name} 蛋白密度过低不该解馋"
            )

    def test_host_prefers_prestige(self):
        """「请客」不为性价比买单——按价格档位选排面担当。

        2026-10-13 用户指出：请客未必选性价比最高的。
        旧逻辑按钙/元推双层吉士汉堡（¥23 的效率王），
        新逻辑按价格降序，推 ¥34.5 的培根安格斯厚牛堡（安格斯系 = 排面）。
        """
        top = recommend(self.idx, "host", top=1)
        self.assertEqual(top[0].name, "培根安格斯厚牛堡")
        # 每元效率仍然是真实的——只是不作排序依据
        self.assertAlmostEqual(top[0].protein_per_yuan, 34 / 34.5, places=2)

    def test_host_excludes_low_protein_items(self):
        """「请客」不能推冰淇淋 —— 钙高但蛋白极低，撑不住场面。"""
        top = recommend(self.idx, "host", top=5)
        for item in top:
            self.assertGreaterEqual(
                item.protein_per_yuan, 0.8, f"{item.name} 蛋白过低不该请客"
            )

    def test_discipline_prefers_low_fat(self):
        """「管住嘴」= 少油，所以按脂肪/元 升序 —— 冠军是候选里脂肪效率最低的。

        2026-10-16：主指标由蛋白质/元 改为脂肪/元。原来它和「今天在练」
        是同一条排序，两个场景必然推同一个冠军（那么大鸡排），
        问卷退化成装饰品 —— 直接违反 SKILL.md 铁律⑥。
        """
        s = next(s for s in SCENARIOS if s.key == "discipline")
        self.assertEqual(s.primary, "fat_per_yuan")
        top = recommend(self.idx, "discipline")
        pool = [
            i
            for i in self.idx.items
            if i.fat_per_yuan is not None
            and (i.protein_per_yuan or 0) >= (s.guard_min or 0)
        ]
        self.assertAlmostEqual(
            top[0].fat_per_yuan, min(i.fat_per_yuan for i in pool), places=6
        )
        # 与「今天在练」必须分开 —— 这是本测试真正的目的
        self.assertNotEqual(
            top[0].name, recommend(self.idx, "training", top=1)[0].name
        )

    def test_training_is_pro_tier(self):
        s = next(s for s in SCENARIOS if s.key == "training")
        self.assertEqual(s.tier, "pro")

    def test_kid_uses_guard_constraint(self):
        s = next(s for s in SCENARIOS if s.key == "kid")
        self.assertIsNotNone(s.guard)
        self.assertIsNotNone(s.guard_min)

    def test_kid_leader_is_milk(self):
        """实测：纯牛奶钙/元 22.00 全场最高，是「给小孩」的正确冠军。"""
        top = recommend(self.idx, "kid", top=1)
        self.assertEqual(top[0].name, "纯牛奶(盒装)")

    def test_unknown_scenario_returns_empty(self):
        self.assertEqual(recommend(self.idx, "不存在"), [])

    def test_each_scenario_can_yield_different_winner(self):
        """问卷的价值：不同状态给出不同冠军，否则问卷是装饰品。"""
        winners = {k: recommend(self.idx, k, top=1)[0].name for k in
                   ("craving", "discipline", "host")}
        self.assertGreaterEqual(len(set(winners.values())), 2)


# ── 输出 ────────────────────────────────────────────────────────────────


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.idx = build_index(menu(REAL_MATCHED), REAL_NUTRITION)

    def test_base_table_has_no_sodium(self):
        out = render_decision_table(self.idx, recommend(self.idx, "craving"))
        self.assertNotIn("钠", out)

    def test_pro_table_shows_sodium(self):
        out = render_decision_table(
            self.idx, recommend(self.idx, "training"), show_pro=True
        )
        self.assertIn("钠", out)

    def test_coverage_always_leads_report(self):
        out = render_report(self.idx, "discipline")
        self.assertIn("覆盖", out.split("\n")[0])

    def test_uncovered_listed_with_explanation(self):
        out = render_report(self.idx, "discipline")
        self.assertIn("麦辣鸡翅", out)
        self.assertIn("不参与推荐", out)

    def test_empty_index_renders_without_crash(self):
        empty = FuelIndex(items=(), menu_total=0, matched=0)
        self.assertIn("0 款在售餐品", render_report(empty, "discipline"))


# ── 规格后缀剥离（回归：跨单品营养污染）──────────────────────────────────


class TestStripSpec(unittest.TestCase):
    """`_strip_spec` 只准剥**末尾**的成对括号段。

    2026-10-16 修复：旧正则 `[（(【\\[(（].*` 既没有锚定、`.*` 又贪婪，
    会把以方括号开头的名字从**第一个** 【 一路吃到行尾 ——
    「【美汁源】“多汁柠柠”」塌成空串，于是在 `by_core` 里与
    「【美汁源】“黄金橙橙”」互相覆盖，柠柠吃到了橙橙的 165 kcal。
    """

    def test_strips_trailing_spec(self):
        self.assertEqual(_strip_spec("那么大鸡排（椒盐风味）"), "那么大鸡排")

    def test_normalizes_halfwidth_brackets(self):
        # 菜单写半角、营养库写全角，剥掉后缀后两边必须对得上
        self.assertEqual(_strip_spec("纯牛奶(盒装)"), "纯牛奶")
        self.assertEqual(_strip_spec("纯牛奶（盒装）"), "纯牛奶")

    def test_keeps_leading_brand_bracket(self):
        """品牌方括号在名字**开头**，它不是规格后缀 —— 必须原样保留。"""
        name = "【美汁源】“多汁柠柠”"
        self.assertEqual(_strip_spec(name), name)

    def test_two_brand_flavors_keep_distinct_cores(self):
        """边界：同品牌不同口味的两款饮品不能塌成同一个 core。"""
        orange = _strip_spec("【美汁源】“黄金橙橙”")
        lemon = _strip_spec("【美汁源】“多汁柠柠”")
        self.assertNotEqual(orange, lemon)
        self.assertTrue(orange and lemon, "core 不能是空串")

    def test_bracket_only_name_returned_as_is(self):
        """整个名字就是一段括号时原样返回 —— 空 core 会去撞上别人。"""
        self.assertEqual(_strip_spec("（椒盐风味）"), "（椒盐风味）")

    def test_no_empty_core_for_any_real_name(self):
        for name in parse_nutrition(REAL_NUTRITION):
            self.assertTrue(_strip_spec(name), f"「{name}」的 core 是空串")


class TestNoCrossItemPollution(unittest.TestCase):
    """回归：一个单品不得拿到另一个单品的营养值（真实快照）。"""

    def setUp(self):
        self.idx = load_snapshot_index()
        self.by_name = {i.name: i for i in self.idx.items}

    def test_every_match_is_same_origin(self):
        """任何被匹配上的餐品，其营养记录名必须与原菜单名同源。"""
        for item in self.idx.items:
            self.assertEqual(
                _strip_spec(item.nutrition.name),
                _strip_spec(item.name),
                f"「{item.name}」匹配到了「{item.nutrition.name}」的营养值",
            )

    def test_orange_keeps_its_own_nutrition(self):
        self.assertIn("【美汁源】“黄金橙橙”", self.by_name)
        self.assertEqual(
            self.by_name["【美汁源】“黄金橙橙”"].nutrition.name,
            "【美汁源】“黄金橙橙”",
        )

    def test_lemon_not_matched_to_orange(self):
        """柠柠在营养库里没有记录，就必须落进未覆盖清单 —— 不能借橙橙的。"""
        self.assertNotIn(
            "【美汁源】“多汁柠柠”",
            self.by_name,
            "「多汁柠柠」不该被匹配上：它吃到了别的单品的营养值",
        )
        self.assertIn("【美汁源】“多汁柠柠”", self.idx.unmatched_names)

    def test_coverage_is_what_it_says(self):
        """快照冻结在这里，匹配数就必须是一个确定的真值。

        修复前虚高 1 款（20/100 = 20%），修复后 19/100 = 19%。
        宁可数字变小，也不能拿一个借来的营养值充数。
        """
        self.assertEqual(self.idx.menu_total, 100)
        self.assertEqual(self.idx.matched, len(self.idx.items))
        self.assertEqual(self.idx.matched, 19)
        self.assertAlmostEqual(self.idx.coverage, 19.0, places=1)


# ── 场景排序必须互不相同（SKILL.md 铁律⑥）──────────────────────────────


class TestScenarioChampionsAreDistinct(unittest.TestCase):
    """铁律⑥：每个场景必须有各自的冠军。

    README 把「六个场景冠军各不相同」当卖点写在首页，而实测只有 4/6 ——
    「管住嘴」「今天在练」「犒劳自己」三个场景都推那么大鸡排。
    **这条铁律此前没有任何测试挡住**，所以它在纸面上成立、在数据上是假的。
    """

    def setUp(self):
        self.idx = load_snapshot_index()

    def test_six_distinct_champions(self):
        champs = {}
        for s in SCENARIOS:
            top = recommend(self.idx, s.key, top=1)
            self.assertTrue(top, f"「{s.label}」一个都推不出来")
            champs[s.label] = top[0].name
        names = list(champs.values())
        dup = {n for n in names if names.count(n) > 1}
        self.assertEqual(
            len(set(names)),
            len(SCENARIOS),
            f"冠军重复：{dup}（各场景冠军：{champs}）",
        )

    def test_primaries_are_distinct(self):
        """两个场景共用主指标，必然推出同一个冠军 —— 从配置层就掐掉。"""
        primaries = [s.primary for s in SCENARIOS]
        self.assertEqual(
            len(set(primaries)), len(primaries), f"主指标重复：{primaries}"
        )

    def test_every_guard_actually_rejects_something(self):
        """守卫必须真的在筛，不能是空转。

        「今天在练」曾写死 `sodium_per_yuan >= 0.0` —— 钠/元 不可能为负，
        那个守卫永远筛不掉任何东西，是纯装饰代码。
        """
        for s in SCENARIOS:
            if not s.guard or s.guard_min is None:
                continue
            guard = next(m for m in METRICS if m.key == s.guard)
            self.assertTrue(
                guard.higher_is_better,
                f"「{s.label}」的门槛写的是下限，守卫指标就得是越大越好",
            )
            kept = [
                i
                for i in self.idx.items
                if i.metric(s.guard) is not None
                and i.metric(s.guard) >= s.guard_min
            ]
            self.assertLess(
                len(kept),
                len(self.idx.items),
                f"「{s.label}」的守卫永远筛不掉任何东西（空转）",
            )


if __name__ == "__main__":
    unittest.main()