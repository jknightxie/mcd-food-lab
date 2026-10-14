"""问卷映射逻辑的单元测试。

这一层之前根本不存在 —— 提问只写在文档里，没有代码。
现在 `resolve_answer()` 是「问卷落地」的唯一口径，必须守住：

1. 用户用日常说法回答，不能只认选项名
2. 一句话命中多个关键词时，**更具体的场景优先**
3. 听不懂就返回 None，绝不猜
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fuel_index import (  # noqa: E402
    METRICS,
    SCENARIOS,
    build_options,
    build_question,
    resolve_answer,
)


class TestResolveAnswer(unittest.TestCase):
    def test_exact_option_label(self):
        for s in SCENARIOS:
            self.assertEqual(resolve_answer(s.label), s.key, f"{s.label} 映射失败")

    def test_colloquial_phrasings(self):
        cases = [
            ("嘴馋了", "craving"),
            ("随便吃点", "craving"),
            ("今天想控制一下饮食", "discipline"),
            ("招待几个朋友", "host"),
            ("带娃来吃饭", "kid"),
            ("今天刚练完，想吃点东西", "training"),
            ("增肌期该吃什么", "training"),
        ]
        for text, expected in cases:
            self.assertEqual(resolve_answer(text), expected, f"「{text}」判错")

    def test_specific_beats_generic(self):
        """核心边界：更具体的关键词优先于泛化描述。

        「今天刚练完，想吃点东西」同时含「训练」「想吃」，
        必须判为 training —— 否则等于没听懂用户说了什么。
        """
        self.assertEqual(resolve_answer("今天刚练完，想吃点东西"), "training")

    def test_kid_beats_training(self):
        """带娃同时约束热量与钠，比运动信息量更大。"""
        self.assertEqual(resolve_answer("练完带娃吃饭"), "kid")

    def test_comfort_catches_daily_states(self):
        """疲惫/情绪类状态必须能识别 —— 这是高频真实需求，不是边缘情况。"""
        for text in ("累死了", "下班了好累", "今天没胃口", "有点焦虑", "感冒了"):
            self.assertEqual(resolve_answer(text), "comfort", f"「{text}」判错")

    def test_comfort_beats_craving(self):
        """「很累，想吃点有肉的」含「想吃」，但真实意图是疲惫。"""
        self.assertEqual(resolve_answer("今天很累，想吃点有肉的"), "comfort")

    def test_comfort_direction_is_positive(self):
        """边界：犒劳场景必须「热量越高越好」。

        用 kcal_per_yuan（越低越好）会把低热量餐品推给疲惫的人 ——
        那会让疲惫更明显，是反的。
        """
        s = next(s for s in SCENARIOS if s.key == "comfort")
        metric = next(m for m in METRICS if m.key == s.primary)
        self.assertTrue(metric.higher_is_better, "犒劳场景不应偏好低热量")

    def test_two_kcal_metrics_opposite(self):
        """kcal_per_yuan 与 energy_density 是同一份数据、相反方向。"""
        low = next(m for m in METRICS if m.key == "kcal_per_yuan")
        high = next(m for m in METRICS if m.key == "energy_density")
        self.assertFalse(low.higher_is_better)
        self.assertTrue(high.higher_is_better)

    def test_comfort_still_requires_protein(self):
        """犒劳也要有蛋白 —— 否则全是零蛋白饮料。"""
        s = next(s for s in SCENARIOS if s.key == "comfort")
        self.assertIsNotNone(s.guard)
        self.assertIsNotNone(s.guard_min)

    def test_unrecognized_returns_none(self):
        for text in ("今天天气不错", "", "随便", "嗯"):
            self.assertIsNone(resolve_answer(text), f"「{text}」不该被强行匹配")

    def test_never_invents_scenario(self):
        """返回值必须是真实存在的场景 key。"""
        valid = {s.key for s in SCENARIOS}
        for text in ("解馋", "带小孩", "刚练完", "请客", "天气好", "随便"):
            got = resolve_answer(text)
            if got is not None:
                self.assertIn(got, valid)

    def test_none_input_safe(self):
        self.assertIsNone(resolve_answer(None))


class TestBuildQuestion(unittest.TestCase):
    def test_question_is_just_the_question(self):
        """核心边界：第一句只问问题，**不列选项**。

        列选项会把用户推进「挑标签」模式 ——
        「今天很累，想吃点有肉的」会被迫映射到某个标签，
        而不是被理解成「疲惫 + 想要蛋白质」。
        """
        q = build_question()
        self.assertIn("今天这顿想干什么", q)
        self.assertNotIn("解馋", q)
        self.assertNotIn("可选", q)

    def test_question_is_single_line(self):
        self.assertEqual(len(build_question().splitlines()), 1)

    def test_options_separate_from_question(self):
        """选项是独立函数，供答不上来时兜底。"""
        opts = build_options()
        for s in SCENARIOS:
            self.assertIn(s.label, opts)

    def test_pro_tier_marked_in_options(self):
        self.assertIn("进阶层", build_options())

    def test_prompt_field_actually_used(self):
        """回归防护：Scenario.prompt 不能再是无人读取的死字段。"""
        prompts = {s.prompt for s in SCENARIOS if s.prompt}
        self.assertTrue(prompts)
        self.assertIn(next(iter(prompts)), build_question())


class TestScenarioIntegrity(unittest.TestCase):
    """场景必须真的绑定数据，否则问卷会退化成娱乐小游戏。"""

    def test_every_scenario_binds_metrics(self):
        for s in SCENARIOS:
            self.assertTrue(s.primary, f"{s.label} 没有主指标")

    def test_pro_scenarios_exist(self):
        pro = [s for s in SCENARIOS if s.tier == "pro"]
        self.assertTrue(pro, "进阶层场景不应为空")

    def test_labels_unique(self):
        labels = [s.label for s in SCENARIOS]
        self.assertEqual(len(labels), len(set(labels)))

    def test_keys_unique(self):
        keys = [s.key for s in SCENARIOS]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()