"""表格渲染的对齐测试。

**为什么值得单独测**：2026-10-12 用户实际使用时反馈
「结论里提到钙，但表格里看不到」。

根因：中文是**全角字符**（占 2 列），而 Python 的 `len()` 只算 1。
`"餐品".ljust(8)` 补到 8 个字符，但终端显示是 10 格——
于是「钙」列宽多出 2 格，后面每列全部错位，
表现为「数字对不上表头」。

这类bug 肉眼容易忽略，但用户会直接得出
「这个工具的数据不可信」的错误结论。
"""

import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fuel_index import (  # noqa: E402
    _display_width,
    _fmt,
    _pad,
    _trunc,
    build_index,
    render_decision_table,
    recommend,
)
from test_fuel_index import REAL_MATCHED, REAL_NUTRITION, menu  # noqa: E402


def dw(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def build():
    return build_index(menu(REAL_MATCHED), REAL_NUTRITION)


class TestDisplayWidth(unittest.TestCase):
    def test_cjk_counts_as_two(self):
        self.assertEqual(_display_width("餐品"), 4)
        self.assertEqual(_display_width("abc"), 3)
        self.assertEqual(_display_width("钙"), 2)

    def test_mixed_text(self):
        self.assertEqual(_display_width("那么大鸡排"), 10)
        self.assertEqual(_display_width("A钙"), 3)

    def test_ljust_would_be_wrong(self):
        """回归防护：记住为什么不能用 ljust。"""
        self.assertNotEqual(_display_width("餐品".ljust(8)), 8)


class TestPad(unittest.TestCase):
    def test_pad_reaches_target_display_width(self):
        for text in ("餐品", "abc", "钙", "", "那么大鸡排"):
            for width in (8, 12, 20):
                if dw(text) > width:
                    continue  # 超宽时不截断，_pad 会补 0 格
                self.assertEqual(_display_width(_pad(text, width)), width)

    def test_pad_right_aligns(self):
        padded = _pad("385", 10, right=True)
        self.assertTrue(padded.startswith("       "))

    def test_pad_left_aligns(self):
        padded = _pad("385", 10)
        self.assertTrue(padded.endswith("       "))

    def test_pad_never_truncates(self):
        """内容超宽时原样返回，不能截掉数据。"""
        self.assertEqual(_pad("很长很长很长的名字", 4), "很长很长很长的名字")


class TestTrunc(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(_trunc("巨无霸", 10), "巨无霸")

    def test_long_text_fits_width(self):
        out = _trunc("那么大鸡排（椒盐风味）很长", 12)
        self.assertLessEqual(_display_width(out), 12)
        self.assertTrue(out.endswith("…"))

    def test_trunc_respects_cjk_width(self):
        """截断必须按显示宽度，不能按字符数。"""
        out = _trunc("餐品名称很长", 5)
        self.assertLessEqual(_display_width(out), 5)


class TestTableAlignment(unittest.TestCase):
    """核心断言：表格每一行的显示宽度必须相同。"""

    def setUp(self):
        self.idx = build()

    def _rows(self, show_pro=False, key="discipline"):
        table = render_decision_table(self.idx, recommend(self.idx, key), show_pro)
        return [line for line in table.split("\n") if not line.strip().startswith("⚠")]

    def test_all_rows_same_display_width(self):
        for show_pro in (False, True):
            rows = self._rows(show_pro)
            widths = {dw(r) for r in rows}
            self.assertEqual(
                len(widths), 1, f"列宽不一致：{widths}（show_pro={show_pro}）"
            )

    def test_header_and_data_align(self):
        """表头与数据行宽度一致 —— 这是「数字对不上表头」的根因。"""
        rows = self._rows(True)
        self.assertEqual(dw(rows[0]), dw(rows[2]))

    def test_calcium_column_visible_and_aligned(self):
        """用户反馈的具体问题：钙列必须对得上。

        钙值取自该行餐品的真实营养值（不绑定特定冠军——
        请客场景 2026-10-13 改为排面排序后，榜首换成了培根安格斯）。
        """
        idx = build()
        top = recommend(idx, "host", top=5)
        rows = self._rows(False, "host")
        header = rows[0]
        self.assertIn("钙", header)
        self.assertGreater(header.index("钙"), 0)
        # 每个数据行的钙值必须与其餐品一一对应，且落在数据行里
        for i, item in enumerate(top):
            row = rows[2 + i]
            self.assertIn(_fmt(item.calcium), row,
                          f"{item.name} 的钙值 {_fmt(item.calcium)} 不在行内")

    def test_pro_columns_also_aligned(self):
        rows = self._rows(True)
        self.assertEqual(dw(rows[0]), dw(rows[3]))


class TestFmt(unittest.TestCase):
    def test_none_is_dash(self):
        self.assertEqual(_fmt(None), "—")

    def test_numbers(self):
        self.assertEqual(_fmt(385), "385")
        self.assertEqual(_fmt(1.714, 2), "1.71")

    def test_dash_width_is_one(self):
        self.assertEqual(_display_width(_fmt(None)), 1)


if __name__ == "__main__":
    unittest.main()