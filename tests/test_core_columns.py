"""核心列恒定性测试。

**用户实测发现的回归**：2026-10-12 用户截图反馈
「不同场景，表格内容都不同了？我的卖点蛋白质/元 都没了」。

根因：修复「表头与排序依据不符」那个 bug 时，让最后一列
**跟随排序指标变化** —— 结果「犒劳自己」场景（当时主指标是
`energy_density` 供能密度）把核心列挤掉了。

正确设计：
- **排序依据决定行的顺序，不决定显示哪些列**
- 「蛋白质/元」是核心卖点，任何场景都必须在
- 场景需要额外指标时，**追加**到末尾，而不是替换
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from card import render_card  # noqa: E402
from fuel_index import (  # noqa: E402
    SCENARIOS,
    build_index,
    render_decision_table,
    recommend,
)
from test_fuel_index import REAL_MATCHED, REAL_NUTRITION, menu  # noqa: E402


def build():
    return build_index(menu(REAL_MATCHED), REAL_NUTRITION)


class TestCoreColumnsAlwaysPresent(unittest.TestCase):
    """所有场景下核心列都必须存在。"""

    # 每行榜单必备的信息：价格(¥) · 蛋白 · 钙 · g蛋白/元 徽章
    # （2026-10-12 视觉重设计后表格换成条形榜单，契约不变，载体变了）
    CORE = ["¥", "蛋白", "钙", "g蛋白/元"]

    def setUp(self):
        self.idx = build()

    def test_text_table_has_core_columns_in_all_scenarios(self):
        for s in SCENARIOS:
            table = render_decision_table(
                self.idx, recommend(self.idx, s.key), sort_by=s.primary
            )
            header = table.split("\n")[0]
            for col in ("价格", "蛋白质", "钙", "蛋白质/元"):
                self.assertIn(
                    col, header, f"场景「{s.label}」缺少核心列「{col}」"
                )

    def test_html_has_core_columns_in_all_scenarios(self):
        for s in SCENARIOS:
            html = render_card(self.idx, s.key)
            for col in self.CORE:
                self.assertIn(
                    col, html, f"场景「{s.label}」缺少「{col}」"
                )

    def test_protein_per_yuan_column_present(self):
        """核心卖点单独再守一次。"""
        for s in SCENARIOS:
            table = render_decision_table(
                self.idx, recommend(self.idx, s.key), sort_by=s.primary
            )
            self.assertIn("蛋白质/元", table.split("\n")[0])

    def test_comfort_scenario_keeps_both(self):
        """犒劳场景：既要按碳水/元 排，也不能丢蛋白质/元。"""
        table = render_decision_table(
            self.idx, recommend(self.idx, "comfort"), sort_by="carb_per_yuan"
        )
        header = table.split("\n")[0]
        self.assertIn("蛋白质/元", header)
        self.assertIn("碳水", header)


class TestSortDoesNotChangeColumns(unittest.TestCase):
    """排序依据只影响顺序。"""

    def setUp(self):
        self.idx = build()

    def test_different_sort_same_columns(self):
        """用不同 sort_by 渲染，列集合必须完全一致。"""
        a = render_decision_table(
            self.idx, recommend(self.idx, "discipline"), sort_by="protein_per_yuan"
        )
        b = render_decision_table(
            self.idx, recommend(self.idx, "host"), sort_by="calcium_per_yuan"
        )
        self.assertEqual(a.split("\n")[0], b.split("\n")[0])

    def test_extra_metric_appended_not_substituted(self):
        """额外指标必须排在基础列之后。"""
        table = render_decision_table(
            self.idx, recommend(self.idx, "comfort"), sort_by="carb_per_yuan"
        )
        header = table.split("\n")[0]
        self.assertGreater(
            header.index("碳水"),
            header.index("蛋白质/元"),
            "额外指标应追加在核心列之后，而不是替换它",
        )


class TestColumnOrderConsistency(unittest.TestCase):
    def setUp(self):
        self.idx = build()

    def test_header_and_rows_column_count_match(self):
        """表头列数必须与数据行一致 —— 之前 6 列 vs 7 列的问题。"""
        for s in SCENARIOS:
            table = render_decision_table(
                self.idx, recommend(self.idx, s.key), sort_by=s.primary
            )
            lines = [
                l for l in table.split("\n") if not l.strip().startswith("⚠")
            ]
            header_cols = len(lines[0].split())
            for line in lines[2:]:
                self.assertEqual(
                    len(line.split()),
                    header_cols,
                    f"场景「{s.label}」列数不一致",
                )

    def test_html_row_structure_consistent(self):
        """榜单每行结构一致：5 行 = 5 个蛋白徽章 + 5 根条。

        取代旧表格的「表头列数 = 数据列数」断言 —— 换成条形图后，
        等价的契约是每行都有徽章与条，不能有的行缺。
        """
        for s in SCENARIOS:
            html = render_card(self.idx, s.key)
            rows = html.count('<div class="row"') + html.count(
                '<div class="row gold"'
            )
            self.assertEqual(rows, 5, f"场景「{s.label}」榜单不是 5 行")
            self.assertEqual(html.count('class="sig"'), 5, f"场景「{s.label}」徽章数与行数不符")
            self.assertEqual(html.count('class="fill"'), 5, f"场景「{s.label}」条形数与行数不符")

    def test_pro_tier_adds_sodium_and_fat(self):
        """进阶层场景每行应带钠与脂肪。"""
        html = render_card(self.idx, "training")
        self.assertGreaterEqual(html.count("钠"), 5)
        self.assertGreaterEqual(html.count("脂肪"), 5)


if __name__ == "__main__":
    unittest.main()