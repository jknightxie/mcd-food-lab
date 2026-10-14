"""SKILL.md 的一致性测试。

这不是文档洁癖 —— agent 完全按 SKILL.md 的指令行事。
**指令写错，agent 就会做错**，而且用户会以为是产品的问题。

2026-10-12 实际事故：用户说「帮我推荐一款今日午餐麦当劳」，
agent 只问了门店就直接给了「解馋」推荐。原因有二：

1. 执行流程里只写了「问店」，没写「问今天想干什么」
2. 示例表里写着「今天中午吃麦当劳，帮我挑一款 → 解馋」
   —— 这等于在教 agent 把含糊请求默认成解馋

本文件守住这两点不再退化。
"""

import re
import sys
import unittest
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def read_skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


class TestExecutionFlow(unittest.TestCase):
    """执行流程必须同时包含「问场景」和「问门店」。"""

    def setUp(self):
        self.text = read_skill()

    def test_flow_requires_both_questions(self):
        flow = self._flow_section()
        self.assertIn("今天这顿想干什么", flow)
        self.assertIn("店", flow)

    def test_flow_forbids_guessing(self):
        flow = self._flow_section()
        self.assertIn("不许猜", flow)

    def test_explicitly_cites_the_incident(self):
        """必须写清为什么不能默认 —— 不写清，agent 下次还会猜。"""
        flow = self._flow_section()
        self.assertIn("192", flow, "应说明猜错的实际后果")

    def _flow_section(self) -> str:
        text = read_skill()
        start = text.find("执行流程")
        self.assertNotEqual(start, -1, "SKILL.md 必须有执行流程章节")
        return text[start : start + 1200]


class TestAmbiguousRequestsMustAsk(unittest.TestCase):
    """含糊请求必须追问，不许映射。"""

    VAGUE = ["随便", "推荐一款", "今天吃麦当劳", "帮我挑一个", "随便来一个"]

    def setUp(self):
        self.text = read_skill()

    def _example_table(self) -> str:
        start = self.text.find("用户会说的原话")
        self.assertNotEqual(start, -1)
        return self.text[start : start + 800]

    def test_vague_phrases_absent_from_mapping_table(self):
        """回归防护：这些词绝不能再出现在「用户说 → 映射」表里。"""
        table = self._example_table()
        for phrase in self.VAGUE:
            row = f"|{phrase}"
            self.assertNotIn(
                row, table.replace(" ", ""),
                f"「{phrase}」被列为可直接映射，agent 会据此跳过追问",
            )

    def test_vague_phrases_marked_as_needing_followup(self):
        text = self.text
        self.assertTrue(
            "追问" in text or "必须问" in text,
            "必须明确写出含糊请求要追问",
        )

    def test_specific_phrases_still_mapped(self):
        """不能为了防止乱猜，把正常映射也删了。"""
        table = self._example_table()
        for phrase in ("刚练完", "带小孩", "招待朋友", "下班了好累"):
            self.assertIn(phrase, table, f"「{phrase}」应保留映射")


class TestMealScenarioFitness(unittest.TestCase):
    """午餐/晚餐这类正餐请求，不该用解馋场景。"""

    def setUp(self):
        self.text = read_skill()

    def test_meal_terms_trigger_warning(self):
        for term in ("午餐", "晚餐", "正餐"):
            self.assertIn(term, self.text, f"未覆盖正餐场景「{term}」")

    def test_craving_marked_as_not_meal(self):
        self.assertIn("不要用解馋场景", self.text)

    def test_meal_scenarios_recommended(self):
        """必须给出正餐该用哪几个场景。"""
        section_start = self.text.find("正餐请求要加一道下限")
        self.assertNotEqual(section_start, -1)
        section = self.text[section_start : section_start + 700]
        for scene in ("管住嘴", "请客", "今天在练"):
            self.assertIn(scene, section, f"未指出正餐可用「{scene}」")


class TestNoCommandLineForUsers(unittest.TestCase):
    """用户不该被要求碰命令行。"""

    def setUp(self):
        self.text = read_skill()

    def test_forbids_python_invocation(self):
        self.assertIn("不要让用户执行", self.text)

    def test_agent_must_resolve_store(self):
        """门店必须有 —— 但优先用收藏门店，不该逼用户打字报位置。"""
        self.assertIn("定门店", self.text)
        self.assertIn("收藏", self.text)


class TestNoFrontmatterBreakage(unittest.TestCase):
    """SKILL.md 的 frontmatter 必须能被解析，否则 Skill 根本加载不了。"""

    def test_frontmatter_present(self):
        text = read_skill()
        self.assertTrue(text.startswith("---\n"), "缺少 frontmatter 起始")
        self.assertIn("\nname:", text)
        self.assertIn("\ndescription:", text)

    def test_frontmatter_single_block(self):
        """只看 frontmatter 段内。正文里本来就有多处--- 分隔线。"""
        text = read_skill()
        end = text.find("\n---\n", 4)
        self.assertNotEqual(end, -1, "frontmatter 未闭合")
        frontmatter = text[4:end]
        self.assertNotIn("\n---\n", frontmatter, "frontmatter 段内不应再出现分隔符")

    def test_name_matches_directory(self):
        text = read_skill()
        m = re.search(r"^name:\s*(\S+)", text, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), SKILL_MD.parent.name)


class TestCardStyleGuidance(unittest.TestCase):
    """SKILL.md 必须写清风格怎么选 —— 不追问、能映射、有默认。"""

    def setUp(self):
        self.text = read_skill()

    def test_style_mapping_table_present(self):
        for word in ("深夜", "小票", "复古", "经典"):
            self.assertIn(word, self.text, f"风格词「{word}」缺少映射")

    def test_resolves_style_referenced(self):
        """映射必须指向 resolve_style，不许 agent 另写一套。"""
        self.assertIn("resolve_style", self.text)

    def test_no_extra_question_for_style(self):
        """不许为选风格打断主流程 —— 这条规则必须写出来。"""
        self.assertIn("不追问", self.text)

    def test_smart_default_present(self):
        """没提风格时必须有场景智能默认。"""
        self.assertIn("智能默认", self.text)
        self.assertIn("midnight", self.text)
        self.assertIn("retro", self.text)


if __name__ == "__main__":
    unittest.main()