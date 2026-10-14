"""card.py 单元测试。

核心边界：**卡片里不能出现任何硬编码的营销结论或示例数字。**
所有数字必须来自 FuelIndex，页脚保持中性。

2026-10-12 卡片视觉重设计（麦当劳品牌色 + 条形图）后，
表格 DOM 换成了条形榜单 DOM，但行为契约不变：
核心卖点 g蛋白/元 任何场景都在、推荐恒为 5 行、覆盖率必须披露。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from card import (  # noqa: E402
    STYLES,
    card_filename,
    render_card,
    resolve_style,
    style_options,
)
from fuel_index import build_index, recommend  # noqa: E402
from test_fuel_index import REAL_MATCHED, REAL_NUTRITION, menu  # noqa: E402

# 绝不允许出现在卡片里的断言 —— 它们依赖特定门店的价格，不能泛化
# （「1.71」是真实计算结果，由 test_values_come_from_index 单独断言存在）
FORBIDDEN = [
    "巨无霸不是",
    "性价比最高",
    "最划算",
]

ALL_SCENARIOS = ("craving", "discipline", "host", "kid", "training", "comfort")


def build():
    return build_index(menu(REAL_MATCHED), REAL_NUTRITION)


class TestCardRender(unittest.TestCase):
    def setUp(self):
        self.idx = build()
        self.html = render_card(self.idx, "discipline")

    def test_produces_complete_html(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", self.html)
        self.assertIn("<meta charset", self.html)

    def test_title_uses_scenario_label(self):
        html = render_card(self.idx, "kid")
        self.assertIn("给小孩", html)

    def test_signature_metric_always_visible(self):
        """核心卖点恒定 —— 任何场景下「每元蛋白」都不能消失。

        2026-10-13 调整：大字签名条改为显示**该场景自己的排序标准**
        （用户指出「别的情况的最优解未必是蛋白质含量的」），
        蛋白质/元的保证转移到：每行黑底徽章（g蛋白/元）+ 非蛋白场景
        的冠军副行（蛋白效率 X g/元）。两者任何场景都必须在。
        """
        for key in ALL_SCENARIOS:
            html = render_card(self.idx, key)
            self.assertIn("g蛋白/元", html, f"场景 {key} 丢了每行蛋白徽章")
            self.assertIn("最优解：", html, f"场景 {key} 眉题没说清按什么判")

    def test_signature_matches_scenario_criterion(self):
        """大字签名条必须是该场景自己的标准，不许冒充。"""
        cases = {
            "discipline": "克蛋白质",
            "training": "克蛋白质",
            "host": "排面担当",
            "kid": "毫克钙",
            "craving": "大卡",
            "comfort": "大卡",
        }
        for key, fragment in cases.items():
            html = render_card(self.idx, key)
            self.assertIn(fragment, html, f"场景 {key} 签名条不是自己的标准")
        # 请客签名条带价格——「拿得出手」要有数字
        self.assertIn("¥34.5", render_card(self.idx, "host"))

    def test_protein_efficiency_kept_in_hero_for_non_protein_scenarios(self):
        """非蛋白场景的冠军副行必须带蛋白效率 —— 核心卖点不在首屏消失。"""
        for key in ("host", "kid", "craving", "comfort"):
            html = render_card(self.idx, key)
            self.assertIn("蛋白效率", html, f"场景 {key} 冠军副行丢了蛋白效率")

    def test_champion_row_marked(self):
        self.assertIn('class="row gold"', self.html)

    def test_only_recommended_items_in_race(self):
        """条形榜单只含被推荐的 5 款，不是全部 20 款。

        注意不能数 '<div class="row' —— row-top 也会命中前缀。
        """
        rows = self.html.count('<div class="row"') + self.html.count(
            '<div class="row gold"'
        )
        self.assertEqual(rows, 5)

    def test_coverage_disclosure_present(self):
        self.assertIn("款在售", self.html)
        self.assertIn("有营养数据", self.html)
        self.assertIn("不参与推荐", self.html)

    def test_uncovered_items_listed(self):
        self.assertIn("麦辣鸡翅", self.html)

    def test_values_come_from_index(self):
        """数字必须与索引一致，不能是写死的示例。"""
        self.assertIn("14.0", self.html)  # 那么大鸡排真实价格
        self.assertIn("1.71", self.html)  # 24g / ¥14 的每元蛋白

    def test_calcium_visible_per_row(self):
        """用户实测反馈过「结论里有钙、表格里看不到钙」—— 钙必须每行可见。"""
        self.assertGreaterEqual(self.html.count("钙"), 5)  # 5 行榜单每行都有


class TestNoHardcodedClaims(unittest.TestCase):
    """边界：卡片里不能出现依赖特定门店的断言。"""

    def setUp(self):
        self.idx = build()

    def test_forbidden_phrases_absent(self):
        for key in ALL_SCENARIOS:
            html = render_card(self.idx, key)
            for phrase in FORBIDDEN:
                self.assertNotIn(phrase, html, f"场景 {key} 含硬编码断言：{phrase}")

    def test_no_bigmac_specific_claim(self):
        """「巨无霸不是…」依赖具体门店价格，换店可能为假。"""
        for key in ALL_SCENARIOS:
            html = render_card(self.idx, key)
            self.assertNotIn("巨无霸不是", html)

    def test_prices_traceable_to_index(self):
        """榜单里每个价格都必须能在索引里找到对应。"""
        html = render_card(self.idx, "discipline")
        top = recommend(self.idx, "discipline")
        for item in top:
            self.assertIn(f"¥{item.price:.1f}", html, f"{item.name} 的价格不在卡片里")

    def test_signature_values_traceable_to_index(self):
        """每行徽章的 g蛋白/元 数值必须来自索引，不能是编的。"""
        html = render_card(self.idx, "discipline")
        top = recommend(self.idx, "discipline")
        for item in top:
            self.assertIn(f"{item.protein_per_yuan:.2f}", html)

    def test_footer_neutral(self):
        html = render_card(self.idx, "discipline")
        self.assertIn("非麦当劳官方产品", html)

    def test_footer_always_carries_repo_link(self):
        """落款恒定带开源链接（用户拍板「所有页面落款…给出具体链接」）。

        调用方没传 project_url → 兜底 PROJECT_URL；传了合法 URL → 用它。
        """
        from card import PROJECT_URL

        without = render_card(self.idx, "discipline")
        self.assertIn(PROJECT_URL, without, "落款里没有具体开源链接")
        with_url = render_card(
            self.idx, "discipline", project_url="https://example.com/x"
        )
        self.assertIn("https://example.com/x", with_url)

    def test_store_name_escaped(self):
        """门店名是用户输入，必须转义，否则可注入。"""
        html = render_card(self.idx, "discipline", store_name='<script>x</script>')
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_store_name_pretty(self):
        """门店显示名字而不是官方全称，更不是 code。

        用户反馈：「餐厅需要名字，不是代码。」
        「麦当劳北京建外SOHO(A座)餐厅」→「北京建外SOHO(A座)」。
        """
        html = render_card(
            self.idx, "discipline", store_name="麦当劳北京建外SOHO(A座)餐厅"
        )
        self.assertIn("北京建外SOHO(A座)", html)
        self.assertNotIn("麦当劳北京", html)
        self.assertNotIn("餐厅</div>", html)

    def test_store_code_not_used_as_name(self):
        """传 code 进来也不该把它显示成店名 —— 宁可没有。"""
        html = render_card(self.idx, "discipline", store_name="1950564")
        self.assertNotIn("1950564", html)


class TestCardStyles(unittest.TestCase):
    """四套视觉风格：DOM 与内容契约完全一致，只换皮肤。"""

    def setUp(self):
        self.idx = build()

    def test_all_styles_render_with_full_contract(self):
        """任何风格都必须守住全部内容契约。"""
        for style in STYLES:
            html = render_card(self.idx, "discipline", style=style)
            self.assertIn(f't-{style}"', html, f"{style} 主题类缺失")
            self.assertIn("克蛋白质", html, f"{style} 丢了签名条")
            self.assertIn("g蛋白/元", html, f"{style} 丢了蛋白徽章")
            self.assertIn("款在售", html, f"{style} 丢了覆盖率")
            self.assertIn("非麦当劳官方产品", html, f"{style} 丢了页脚")
            rows = html.count('<div class="row"') + html.count('<div class="row gold"')
            self.assertEqual(rows, 5, f"{style} 榜单不是 5 行")

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            render_card(self.idx, "discipline", style="赛博朋克")

    def test_default_is_classic(self):
        html = render_card(self.idx, "discipline")
        self.assertIn('t-classic', html)

    def test_styles_registry(self):
        self.assertEqual(
            STYLES, ("classic", "midnight", "receipt", "retro")
        )


class TestStyleResolution(unittest.TestCase):
    """风格词解析 —— 用户说「黑金」不说「midnight」。"""

    def test_common_words(self):
        cases = {
            "黑金": "midnight",
            "深夜款": "midnight",
            "做成小票那样": "receipt",
            "来张复古海报": "retro",
            "经典就好": "classic",
            "默认": "classic",
        }
        for text, expected in cases.items():
            self.assertEqual(resolve_style(text), expected, f"「{text}」应映射到 {expected}")

    def test_unknown_returns_none(self):
        """听不懂必须返回 None，绝不猜。"""
        self.assertIsNone(resolve_style("赛博朋克"))
        self.assertIsNone(resolve_style(""))
        self.assertIsNone(resolve_style(None))

    def test_options_mention_all_labels(self):
        text = style_options()
        for label in ("经典黄黑", "深夜黑金", "营养小票", "复古海报"):
            self.assertIn(label, text)


class TestCardErrors(unittest.TestCase):
    def setUp(self):
        self.idx = build()

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            render_card(self.idx, "不存在的场景")

    def test_filename_pattern(self):
        self.assertEqual(card_filename("kid"), "mcd-food-lab-kid.html")

    def test_empty_index_still_renders(self):
        from fuel_index import FuelIndex

        empty = FuelIndex(items=(), menu_total=0, matched=0)
        html = render_card(empty, "discipline")
        self.assertIn("<html", html)
        self.assertNotIn('<div class="row', html)  # 没有数据就没有榜单行


if __name__ == "__main__":
    unittest.main()


class TestThemeContrast(unittest.TestCase):
    """主题根规则的文字/背景对比度 —— 「黑底黑字」事故的回归防线。

    真实事故（2026-10-14 用户报 bug）：黑金主题把所有背景改深了，
    但根规则没立文字色 —— 题干（.qz-q）、揭示（.qz-reveal）、
    标题（.qz-title/.od-title）、价格（.od-price）全靠继承，
    继承到的是 body 的深墨色 #1a1a1a，落在 #1b1b1e 的深卡片上。
    肉眼不可读，而所有既有测试只断言「文字存在」，不断言「可读」。

    防线：直接解析每套主题的根 (背景, 文字) 算 WCAG 对比度，
    深色主题必须在根上显式立浅色文字。
    """

    @staticmethod
    def _card_css() -> str:
        from card import _CARD_CSS

        return _CARD_CSS

    @staticmethod
    def _root_vars(css: str) -> dict:
        import re

        block = re.search(r":root\s*\{([^}]*)\}", css)
        if not block:
            return {}
        return dict(
            re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", block.group(1))
        )

    @staticmethod
    def _rule(css: str, selector: str) -> str:
        import re

        # 负向回顾排除 body.t-midnight 这类前缀选择器，只取元素根规则
        m = re.search(r"(?<![\w-])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
        return m.group(1) if m else ""

    @classmethod
    def _decl(cls, rule: str, prop: str, vars_map: dict) -> str | None:
        import re

        m = re.search(rf"(?<![\w-]){prop}\s*:\s*([^;}}]+)", rule)
        if not m:
            return None
        value = m.group(1).strip()
        for _ in range(3):  # var() 最多嵌套解析三层
            vm = re.fullmatch(r"var\((--[\w-]+)\)", value)
            if not vm:
                break
            value = vars_map.get(vm.group(1), "").strip()
        return value or None

    @staticmethod
    def _rgb(value: str | None):
        if not value:
            return None
        value = value.strip()
        if value.startswith("#"):
            hexpart = value[1:]
            if len(hexpart) == 3:  # #fff 缩写展开
                hexpart = "".join(c * 2 for c in hexpart)
            if len(hexpart) == 6:
                try:
                    return tuple(int(hexpart[i : i + 2], 16) for i in (0, 2, 4))
                except ValueError:
                    return None
        return None

    @classmethod
    def _luminance(cls, value: str | None) -> float | None:
        rgb = cls._rgb(value)
        if rgb is None:
            return None

        def channel(c: int) -> float:
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(x) for x in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @classmethod
    def _contrast(cls, fg: str | None, bg: str | None) -> float | None:
        lf, lb = cls._luminance(fg), cls._luminance(bg)
        if lf is None or lb is None:
            return None
        hi, lo = max(lf, lb), min(lf, lb)
        return (hi + 0.05) / (lo + 0.05)

    def test_midnight_root_declares_light_text(self):
        """黑金是唯一的深色主题：根规则必须显式立浅色文字。

        这一条就是事故本身的回归：少了根 color，
        题干/揭示/标题/价格全部继承深墨色 = 黑底黑字。
        """
        css = self._card_css()
        vars_map = self._root_vars(css)
        root = self._rule(css, ".t-midnight")
        self.assertTrue(root, "找不到 .t-midnight 根规则")
        color = self._decl(root, "color", vars_map)
        self.assertIsNotNone(color, "黑金根规则没有声明 color —— 会继承深墨色")
        lum = self._luminance(color)
        self.assertIsNotNone(lum, f"color 无法解析为十六进制：{color}")
        self.assertGreater(lum, 0.5, f"黑金根文字不是浅色：{color}")

    def test_every_theme_root_contrast(self):
        """四套主题的根 (背景, 文字) 对比度全部 ≥ 4.5:1。

        浅色主题文字继承 body 深墨色（合法）；
        深色主题文字必须在根上显式声明（见上一条）。
        """
        css = self._card_css()
        vars_map = self._root_vars(css)
        body_rule = self._rule(css, "body")
        inherited = self._decl(body_rule, "color", vars_map)
        for style in STYLES:
            with self.subTest(style=style):
                # classic 是默认主题，没有 t-classic 规则，根在基础 .card 上
                root = self._rule(css, f".t-{style}") or self._rule(css, ".card")
                bg = self._decl(root, "background", vars_map)
                color = self._decl(root, "color", vars_map) or inherited
                ratio = self._contrast(color, bg)
                self.assertIsNotNone(
                    ratio,
                    f"{style} 根背景/文字无法解析（bg={bg}, color={color}）",
                )
                self.assertGreaterEqual(
                    ratio,
                    4.5,
                    f"{style} 根文字对比度不足：{color} on {bg} = {ratio:.2f}:1",
                )


class TestSealStamp(unittest.TestCase):
    """战绩水印图章契约：对/错是盖在答案区上的水印大印，不是小图标。

    设计演进（用户三轮反馈）：
    1. 「打勾打叉不够」→ 换成印章字符对/错（2026-10-14 凌晨）
    2. 「做成两个水印图章，盖在答案上面」→ 印从题头挪进答案区，
       绝对定位 + 低透明度 + 不拦截指针（本轮）

    最终形态：朱砂色、双边框（外粗 3.5px + outline 负偏移内细边）、
    宋体 46px 大字、答案区正中（left/top 50% + translate 居中）、
    微旋（对 -13° / 错 +11°）、opacity .38 的水印。
    答对 = 白文印（实线框），答错 = 朱文印（虚线框），一实一虚分胜负。
    浓度教训：.2 被用户实测判「太浅」——测试锁死区间 [.3, .5]。
    """

    def setUp(self):
        self.idx = build()

    def test_marks_are_seal_characters_not_glyphs(self):
        """印章里刻的是「对/错」两个印章字，不是 ✓/✗ 字符。"""
        from quiz import build_quiz
        from test_quiz import correct_answers

        from card import render_quiz_card

        quiz = build_quiz(self.idx)
        html_right = render_quiz_card(self.idx, tuple(correct_answers(quiz)))
        self.assertIn(">对</span>", html_right)
        self.assertNotIn("✓", html_right)

        html_wrong = render_quiz_card(self.idx, tuple(None for _ in quiz))
        self.assertIn(">错</span>", html_wrong)
        self.assertNotIn("✗", html_wrong)

    def test_seal_stamped_over_answer_block(self):
        """印必须盖在答案区里：HTML 上位于 qz-body 内、答案与揭示之后。"""
        import re

        from quiz import build_quiz
        from test_quiz import correct_answers

        from card import render_quiz_card

        quiz = build_quiz(self.idx)
        html = render_quiz_card(self.idx, tuple(correct_answers(quiz)))
        m = re.search(
            r'<div class="qz-body">.*?<span class="qz-seal qz-ok">对</span>',
            html,
            re.S,
        )
        self.assertIsNotNone(m, "印章不在答案区里 —— 没有盖在答案上")
        block = m.group(0)
        self.assertIn("qz-ans", block, "印前面没有答案行")
        self.assertIn("qz-reveal", block, "印前面没有揭示行")

    def test_seal_is_watermark_not_icon(self):
        """水印契约：绝对定位、答案区正中、大尺寸、够浓、不拦截指针、双边框。"""
        import re

        css = TestThemeContrast._card_css()
        rule = TestThemeContrast._rule(css, ".qz-seal")
        self.assertIn("position: absolute", rule, "印不是绝对定位 —— 盖不到答案上")
        self.assertIn("left: 50%", rule, "印没有水平居中")
        self.assertIn("top: 50%", rule, "印没有垂直居中")
        self.assertIn(
            "translate(-50%, -50%)",
            rule,
            "印没用 translate 居中 —— 会偏出答案区",
        )
        self.assertIn("width: 92px", rule, "印不够大 —— 突出效果出不来")
        # 浓度：用户实测 .38 仍判「透明度很低，要强烈对比」—— 下限提到 .5；
        # 上限 .75 防止盖住答案的字读不出来
        m = re.search(r"opacity: (\.\d+)", rule)
        self.assertIsNotNone(m, "印没有透明度声明")
        self.assertGreaterEqual(
            float(m.group(1)), 0.5, "印泥太浅 —— 用户两次实测反馈过要强烈对比"
        )
        self.assertLessEqual(float(m.group(1)), 0.75, "印泥太浓 —— 会盖住答案的字")
        self.assertIn("pointer-events: none", rule, "印会挡住选中/点击")
        self.assertIn("border: 4px solid currentColor", rule, "印没有双边框的外框")
        self.assertIn("outline", rule, "印没有内细边 —— 双边框印章感少一半")

    def test_seal_pair_differentiated_by_border(self):
        """一对印靠边框虚实区分：对=实线，错=虚线；两印同色（都是朱砂）。"""
        css = TestThemeContrast._card_css()
        base = TestThemeContrast._rule(css, ".qz-seal")
        self.assertIn("border: 4px solid currentColor", base, "对印不是实线框")
        bad = TestThemeContrast._rule(css, ".qz-seal.qz-bad")
        self.assertIn("border-style: dashed", bad, "错印不是虚线框")
        self.assertIn("outline-style: dashed", bad, "错印的内细边不是虚线")
        self.assertIn("rotate(11deg)", bad, "错印没有反旋 —— 两印姿态一样分不出")
        self.assertIn("rotate(-13deg)", base, "对印没有微旋")

    def test_seal_contrast_all_themes(self):
        """每套主题的印泥（水印本色）对卡纸对比度 ≥4.5:1。

        水印靠 opacity 淡化，但**本色必须先立得住**：0.2 透明度下
        4.5:1 的本色才剩下可辨的水印痕。深色主题单独提亮
        （midnight 用 #ff6a52），这里逐套验。
        """
        css = TestThemeContrast._card_css()
        vars_map = TestThemeContrast._root_vars(css)
        for style in STYLES:
            with self.subTest(style=style):
                root = (
                    TestThemeContrast._rule(css, f".t-{style}")
                    or TestThemeContrast._rule(css, ".card")
                )
                card_bg = TestThemeContrast._decl(root, "background", vars_map)
                # 水印没有底色，两印都落在卡纸上；颜色声明在 .qz-seal 上
                decls = self._merged(
                    css,
                    vars_map,
                    [".qz-seal", f".t-{style} .qz-seal", ".qz-bad"],
                )
                ratio = TestThemeContrast._contrast(decls.get("color"), card_bg)
                self.assertIsNotNone(
                    ratio,
                    f"{style} 印泥颜色无法解析（fg={decls.get('color')}, bg={card_bg}）",
                )
                self.assertGreaterEqual(
                    ratio, 4.5, f"{style} 印泥对比度不足：{decls.get('color')} on {card_bg}"
                )

    @staticmethod
    def _merged(css: str, vars_map: dict, selectors: list) -> dict:
        """按选择器顺序合并声明（后者覆盖前者），并解析 var()。"""
        import re

        out: dict = {}
        for sel in selectors:
            m = re.search(r"(?<![\w-])" + re.escape(sel) + r"\s*\{([^}]*)\}", css)
            if not m:
                continue
            for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;}]+)", m.group(1)):
                value = value.strip()
                for _ in range(3):
                    vm = re.fullmatch(r"var\((--[\w-]+)\)", value)
                    if not vm:
                        break
                    value = vars_map.get(vm.group(1), "").strip()
                out[prop] = value
        return out


class TestStyleSwitcher(unittest.TestCase):
    """四风格切换器契约。

    设计：四套主题的 CSS 本来就在同一张样式表里（t-xxx 类），
    切换只是在 body/.card 上换类 + 一小段原生 JS —— 零 CSS 重复。

    2026-10-14 用户拍板「html 都直接合成 4 套版本可以切换的模式」：
    **switchable 成为默认形态** —— 所有生成的卡默认带切换器；
    只有明确要一张干净的单风格卡（纯分享、不想让看的人乱点）
    才 switchable=False / CLI --single-style。
    """

    def setUp(self):
        self.idx = build()

    def test_switcher_is_default_not_opt_in(self):
        """新契约（用户拍板「都直接合成四套可切换」）：默认就带切换器。

        只有明确要一张干净的单风格卡（纯分享）才 switchable=False。
        """
        from card import render_quiz_card

        default = render_quiz_card(self.idx, (0, 0, 0))
        self.assertIn("style-switch", default, "默认卡没有切换器")
        self.assertIn("<script>", default)

        clean = render_quiz_card(self.idx, (0, 0, 0), switchable=False)
        self.assertNotIn("style-switch", clean, "单风格卡不该带切换器")
        self.assertNotIn("<script>", clean)

    def test_switcher_covers_all_four_styles(self):
        """四个按钮一个不少，文案用 STYLE_LABELS，初始高亮 = 传入风格。"""
        from card import STYLE_LABELS, render_card

        html = render_card(self.idx, "discipline", style="midnight", switchable=True)
        for key, label in STYLE_LABELS.items():
            self.assertIn(f'data-style="{key}"', html)
            self.assertIn(f">{label}</button>", html)
        self.assertIn('<button data-style="midnight" class="on">', html)

    def test_switcher_js_toggles_every_theme(self):
        """JS 必须覆盖全部四个 key —— 少一个就有一套切不过去。"""
        from card import _SWITCH_JS

        for key in STYLES:
            self.assertIn(f'"{key}"', _SWITCH_JS)

    def test_switcher_exposes_style_hook_for_host(self):
        """切换器要暴露 `__cardSetStyle` —— 宿主页（演示页）靠它给卡片定随机初始主题。

        宿主只调用、不复制主题逻辑；否则"四套主题"会有两份实现，迟早漂掉。
        """
        from card import render_card

        html = render_card(self.idx, "discipline", style="classic", switchable=True)
        self.assertIn("window.__cardSetStyle = apply", html)
        # 不带切换器时不该有这段脚本
        plain = render_card(self.idx, "discipline", switchable=False)
        self.assertNotIn("__cardSetStyle", plain)

    def test_switchable_card_keeps_initial_theme_class(self):
        """带切换器的卡初始仍是传入风格（分享出去第一眼不变）。"""
        from card import render_card

        html = render_card(self.idx, "discipline", style="retro", switchable=True)
        self.assertIn('<body class="t-retro">', html)
        self.assertIn('<div class="card t-retro">', html)

    def test_empty_card_switchable(self):
        """无数据的诚实卡也支持切换器（预览时不落空）。"""
        from fuel_index import FuelIndex

        from card import _empty_card

        empty = FuelIndex(items=(), menu_total=0, matched=0)
        html = _empty_card(empty, "推荐", "classic", switchable=True)
        self.assertIn("style-switch", html)


class TestRandomStyle(unittest.TestCase):
    """场景权重随机契约（用户拍板：「默认是根据场景随机来的，不是默认不变」）。

    同一场景连开两次，初始风格不重样；氛围亲和保留为权重而非定论。
    """

    def test_returns_valid_style(self):
        import random

        from card import random_style

        for scene in (None, "comfort", "host", "order", "quiz", "不存在的场景"):
            for seed in range(20):
                s = random_style(scene, random.Random(seed))
                self.assertIn(s, STYLES, f"场景 {scene} 抽出了非法风格 {s}")

    def test_no_scenario_covers_all_four(self):
        """无场景（均权）：200 次抽取四套都出现 —— 真的在随机。"""
        import random

        from card import random_style

        draws = [random_style(None, random.Random(s)) for s in range(200)]
        self.assertEqual(set(draws), set(STYLES))

    def test_same_scene_not_fixed(self):
        """同一场景 10 个 seed 至少出 2 种 —— 「不是默认不变」的回归。"""
        import random

        from card import random_style

        for scene in ("comfort", "host", "discipline", "quiz"):
            draws = {random_style(scene, random.Random(s)) for s in range(10)}
            self.assertGreaterEqual(
                len(draws), 2, f"场景 {scene} 的默认风格是固定的"
            )

    def test_affinity_is_weight_not_certainty(self):
        """氛围亲和是偏心不是命中：comfort 出 midnight 显著多于 classic，
        但 classic 也必须出得来（权重 3:1，不是 1:0）。"""
        import random

        from card import random_style

        comfort = [random_style("comfort", random.Random(s)) for s in range(200)]
        self.assertGreater(comfort.count("midnight"), comfort.count("classic") * 2)
        self.assertGreater(comfort.count("classic"), 0, "亲和变成命中了 —— 权重写死了")

        order = [random_style("order", random.Random(s)) for s in range(200)]
        self.assertGreater(order.count("receipt"), order.count("classic") * 2)
        self.assertGreater(order.count("classic"), 0)

    def test_reproducible_with_rng(self):
        """传 rng 可复现（测试与调试需要）。"""
        import random

        from card import random_style

        self.assertEqual(
            random_style("host", random.Random(42)),
            random_style("host", random.Random(42)),
        )
