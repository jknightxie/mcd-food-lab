"""演示页构建冒烟测试。

`demo/index.html` 现在是项目的对外门面（README 首屏就指向它），
而它是 `tools/build_demo.py` 用 card.py 现渲出来的 —— 所以 card.py 或
快照一变，演示页就可能悄悄构建不出来。这里跑一次真实构建并验关键内容。
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo/index.html"
BUILD = ROOT / "tools/build_demo.py"
SNAPSHOT = ROOT / "assets/snapshot.json"


class TestDemoBuild(unittest.TestCase):
    def test_snapshot_present(self):
        """演示页的数据来源必须随仓库走（否则构建需要 Token）。"""
        self.assertTrue(SNAPSHOT.exists(), "缺 assets/snapshot.json")
        self.assertGreater(SNAPSHOT.stat().st_size, 1000)

    def test_build_and_content(self):
        result = subprocess.run(
            [sys.executable, str(BUILD)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=120,
        )
        self.assertEqual(result.returncode, 0, f"构建失败：{result.stdout}{result.stderr}")
        self.assertTrue(DEMO.exists())

        html = DEMO.read_text(encoding="utf-8")
        # 三个标签页
        for tab in ("quiz", "scenes", "order"):
            self.assertIn(f'data-tab="{tab}"', html)
        # 冻结题库：题目与选项都在页内
        self.assertGreaterEqual(len(re.findall(r'"correct":\s*\d', html)), 3)
        # 8 版战报卡 + 6 张场景卡（用占位符计数校验，不依赖具体文案）
        for qi in range(3):
            self.assertIn(f"{{{{Q{qi}}}}}", html, f"战报卡缺 Q{qi} 的答案占位符")
        # 落款与隐私边界必须还在
        self.assertIn("非麦当劳官方产品", html)
        self.assertIn("不是实时查询", html)
        # 页面自带脚本不能被卡片里的 </script> 截断
        self.assertEqual(html.count("</script>"), 1)

    def test_no_img_tags(self):
        """演示页零外链图片 —— 资料库导入的硬门禁。"""
        html = DEMO.read_text(encoding="utf-8")
        self.assertNotIn("<img", html)

    def test_social_preview_meta(self):
        """社交分享卡片必须在，且是 <meta> 而不是 <img>。

        分享到掘金/微信/X 时，没有 og 标签就只是一条灰链接。这里同时守住两件事：
        ① 标签齐全（title/description/image/url）；
        ② 走的是 meta，所以不会碰到上面那条"零 <img>"的门禁。
        og:image 必须是绝对地址 —— 相对路径在第三方抓取时解析不出主机名。
        """
        html = DEMO.read_text(encoding="utf-8")
        for tag in ("og:title", "og:description", "og:image", "og:url", "twitter:card"):
            self.assertIn(f'property="{tag}"' if tag.startswith("og:") else f'name="{tag}"',
                          html, f"缺社交分享标签 {tag}")
        self.assertRegex(
            html, r'property="og:image" content="https://[^"]+/og\.png"',
            "og:image 不是绝对 https 地址",
        )
        self.assertRegex(
            html, r'property="og:image:width" content="1200"',
            "og:image 尺寸与实际产物（1200x630）不一致",
        )

    def test_long_question_text_keeps_line_breaks(self):
        """长题面的换行必须真能渲染出来。

        梗壳重写后题面从平均 45 字涨到 100~160 字：日志体的时间列
        （「21:31:04  加入购物车」）和公文体的「问：/答：」逐行，全靠换行。
        CSS 少了 pre-wrap，浏览器会把 \\n 折叠成空格，整段糊成一坨 —— 而且不报错。
        """
        html = DEMO.read_text(encoding="utf-8")
        self.assertIn("white-space:pre-wrap", html, "题面缺 pre-wrap，换行会被吃掉")
        self.assertIn("function askHtml", html, "缺题面渲染函数（铺垫/问句分级）")
        self.assertIn('class="q-ask"', html, "缺问句加粗的样式钩子")

    def test_sample_cards_in_sync_with_card_source(self):
        """三张示例卡必须与卡片源同步（README 直接引用它们）。

        它们曾是手工复制的产物，卡片改版后就悄悄过期过（水印图章/主题钩子都缺）——
        现在由 `build_demo.py` 顺手产出，这里锁住"确实是最新形态"：
        独立的完整 HTML、带主题钩子、没有页内共享 CSS 的槽位残留。
        """
        sys.path.insert(0, str(ROOT / "tools"))
        from build_demo import CARD_CSS_SENTINEL

        samples = sorted((ROOT / "assets").glob("demo-*.html"))
        self.assertEqual(len(samples), 3, f"示例卡应有 3 张，实际 {len(samples)} 张")
        for path in samples:
            with self.subTest(sample=path.name):
                html = path.read_text(encoding="utf-8")
                self.assertTrue(html.startswith("<!DOCTYPE html>"), "不是完整 HTML")
                self.assertIn("__cardSetStyle", html, "缺最新主题钩子 —— 示例卡过期了")
                self.assertNotIn(CARD_CSS_SENTINEL, html, "CSS 槽位没展开（那是页内用的）")
                self.assertIn("非麦当劳官方产品", html, "落款丢了")
        # 战报卡示例应当是「全对」那版：不能带 `{{Qn}}` 占位符（那是页内替换用的）
        quiz = (ROOT / "assets/demo-quiz.html").read_text(encoding="utf-8")
        self.assertNotIn("{{Q", quiz, "示例战报卡带了占位符，打开会看到 {{Q0}}")
        self.assertIn("qz-ok", quiz, "示例战报卡不是全对版（应盖「对」印）")

    def test_card_iframes_auto_fit_safely(self):
        """卡片 iframe 的自动高度必须防两个坑（2026-10-14 用户报「点餐单空白」）。

        坑一：面板初始 display:none，隐藏容器里量不到高度（body.scrollHeight≈0），
              写进 style.height 会把卡片压成 0px —— 切过去一片空白。
              所以量到可疑高度必须**跳过**，不能覆盖 HTML 上的默认 height。
        坑二：量高度不能读 documentElement.scrollHeight —— 它被 iframe **自身**
              高度撑大（卡 774px、iframe 1000px 时它报 1000），永远量不准。要读 body。
        """
        html = DEMO.read_text(encoding="utf-8")
        # 读的是 body，不是 documentElement
        self.assertIn("d.body.scrollHeight", html, "量高度没用 body.scrollHeight")
        self.assertNotIn(
            "documentElement.scrollHeight", html,
            "量高度读了 documentElement.scrollHeight —— 会被 iframe 自身高度撑大",
        )
        # 隐藏时量到的高度必须被丢弃，且有默认高度兜底
        self.assertRegex(
            html, r"h\s*<\s*60\)\s*return", "缺少「隐藏时量不到高度就跳过」的守卫"
        )
        for fid, default_h in (("quizCard", 1200), ("sceneCard", 1200), ("orderCard", 1000)):
            self.assertRegex(
                html, rf'id="{fid}"[^>]*height="{default_h}"',
                f"{fid} 缺默认 height 兜底（量不到高度时至少还能看见卡）",
            )
        # 三条补量保险：切页签补量、ResizeObserver 跟卡内变化、低速定时兜底
        self.assertIn("refit(panel)", html, "切页签时没有补量")
        self.assertIn("ResizeObserver", html, "没有跟卡片自身变高的观察器")
        self.assertRegex(html, r"setInterval\(.*?forEach\(fit\)", "没有低速定时兜底补量")

    def test_report_card_hidden_until_quiz_done(self):
        """战报卡答完才出现 —— 否则答题前它会占着默认 1200px，看着像"坏了一块"。"""
        html = DEMO.read_text(encoding="utf-8")
        self.assertIn('id="quizCardBox" hidden', html, "战报卡容器没有初始隐藏")
        self.assertIn(
            'getElementById("quizCardBox").hidden = false', html,
            "答完后没有把战报卡露出来",
        )

    def test_card_css_is_shared_once(self):
        """四十多张卡共用一份 CSS（2026-10-14 优化）——不去重是多几百 KB 的纯重复。

        每张卡都内嵌整份卡片 CSS（基础 + 四套主题，约 16KB），41 张就是 600+ KB。
        构建时抽出来放 `cardCss`，卡片里留槽位标记，运行时才展开。
        判据用「卡片 CSS 独有的选择器在整页只出现一次」——直接量重复比数体积靠谱。
        """
        sys.path.insert(0, str(ROOT / "tools"))
        from build_demo import CARD_CSS_SENTINEL

        html = DEMO.read_text(encoding="utf-8")
        # 只用「唯一的整条规则」做判据：像 `.t-midnight {` 会被
        # `body.t-midnight {` 匹配到，那是同一个 CSS 里的另一条规则，会误报
        for marker in (
            ".style-switch {",             # 切换器样式（卡片独有）
            "--red: #da291c;",             # 卡片主题变量
            "max-width: 400px; margin: 0 auto;",  # 卡片主体规则
        ):
            self.assertEqual(
                html.count(marker), 1, f"「{marker}」出现多次 —— CSS 没有共享"
            )
        # 每张卡都留了槽位（41 张卡 + 1 处 JS 常量声明）
        self.assertGreaterEqual(
            html.count(CARD_CSS_SENTINEL), 40, "有卡片还自带整份 CSS"
        )
        # 主题由卡片自己的切换器代码应用，宿主不复制一份主题逻辑
        self.assertIn("__cardSetStyle", html)

    def test_every_play_is_randomised(self):
        """每次打开随机一份：一套题 / 一个默认场景 / 一单点餐单 / 一种主题。

        页面是**冻结快照**（运行时不碰 MCP），所以随机只决定"先给你看哪一面"，
        数字永远来自实测 —— 四种可能都必须预置在页内，随机才有东西可抽。
        """
        sys.path.insert(0, str(ROOT / "tools"))
        from build_demo import ORDER_SPECS, QUIZ_SEEDS

        html = DEMO.read_text(encoding="utf-8")
        self.assertEqual(
            html.count('"seed"'), len(QUIZ_SEEDS), f"冻结题库不是 {len(QUIZ_SEEDS)} 套"
        )
        self.assertGreaterEqual(
            len(re.findall(r'"spec":\s*"', html)), len(ORDER_SPECS), "点餐单候选少了"
        )
        self.assertIn('"styles":', html, "页内没有可选主题清单")
        for expr in (
            "pickOne(DATA.quizSets)",
            "pickOne(DATA.sceneOrder)",
            "pickOne(DATA.orderCards)",
            "pickOne(DATA.styles)",
        ):
            self.assertIn(expr, html, f"缺少随机选择：{expr}")


if __name__ == "__main__":
    unittest.main()
