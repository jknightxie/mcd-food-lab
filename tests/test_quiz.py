"""quiz.py + 战报卡单元测试。

数字纪律：题目、选项、揭示语全部来自 fixture 的真实数据，
门店撑不起反转时自动换题 —— 绝不硬凑。
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from card import STYLES, render_quiz_card  # noqa: E402
from fuel_index import build_index  # noqa: E402
from quiz import (  # noqa: E402
    FRAMES,
    RANKS,
    Question,
    _pair_ask,
    _pick_frames,
    build_quiz,
    rank_for,
    reversal_pair,
    score_quiz,
)
from test_fuel_index import REAL_MATCHED, REAL_NUTRITION, menu  # noqa: E402


def build():
    return build_index(menu(REAL_MATCHED), REAL_NUTRITION)


def correct_answers(quiz):
    return tuple(q.correct for q in quiz)


class TestBuildQuiz(unittest.TestCase):
    def setUp(self):
        self.idx = build()
        self.quiz = build_quiz(self.idx)

    def test_three_questions(self):
        self.assertEqual(len(self.quiz), 3)

    def test_reversal_pair_exists_in_fixture(self):
        """fixture 里巨无霸总量(27g) > 鸡排(24g)，但每元更低 —— 反转成立。"""
        pair = reversal_pair(self.idx)
        self.assertIsNotNone(pair)
        famous, champ = pair
        self.assertEqual(champ.name, "那么大鸡排（椒盐风味）")
        self.assertEqual(famous.name, "巨无霸")
        self.assertGreater(famous.protein, champ.protein)
        self.assertLess(famous.protein_per_yuan, champ.protein_per_yuan)

    def test_q1_is_total_trap(self):
        """第 1 题的正确答案是总量更多的巨无霸 —— 陷阱成立。"""
        q = self.quiz[0]
        self.assertEqual(q.key, "protein_total")
        self.assertEqual(q.options[q.correct], "巨无霸")
        self.assertIn("27", q.reveal)  # 巨无霸真实蛋白量
        self.assertIn("24", q.reveal)  # 鸡排真实蛋白量

    def test_q2_is_reversal(self):
        """第 2 题正确答案是鸡排 —— 除以价格，结论翻转。"""
        q = self.quiz[1]
        self.assertEqual(q.key, "per_yuan")
        self.assertEqual(q.options[q.correct], "那么大鸡排（椒盐风味）")
        self.assertIn("1.71", q.reveal)
        self.assertIn("1.06", q.reveal)

    def test_q3_is_calcium(self):
        """第 3 题是补钙王 —— 纯牛奶（231mg / ¥10.5）。"""
        q = self.quiz[2]
        self.assertEqual(q.key, "calcium_per_yuan")
        self.assertEqual(q.options[q.correct], "纯牛奶(盒装)")

    # 题面允许出现的「引用事实」价格（README 记录的四城实测，非本店数据）
    CITED_FACTS = {"25.5", "26.5"}

    def test_questions_use_real_prices(self):
        """题面里的价格必须来自索引或已记录的引用事实，不许编。"""
        prices_in_index = {f"{i.price:.1f}" for i in self.idx.items}
        for q in self.quiz:
            for token in q.text.replace("元", " ").split():
                if token.replace(".", "").isdigit() and "." in token:
                    self.assertIn(token, prices_in_index | self.CITED_FACTS)

    def test_options_unique(self):
        for q in self.quiz:
            self.assertEqual(len(set(q.options)), len(q.options))
            self.assertTrue(0 <= q.correct < len(q.options))

    def test_all_data_driven_no_hardcoded_copy(self):
        """换一组价格，揭示里的数字必须跟着变 —— 证明没有硬编码。

        题面被随机帧替换后不含价格（帧模板禁止写死数字），
        所以断言落在揭示层：鸡排 vs 巨无霸的价差 11.5 元，
        价格翻倍后必须变成 23.0 元。
        """
        idx2 = build_index(
            menu([(m[0], m[1], str(float(m[2]) * 2)) for m in REAL_MATCHED]),
            REAL_NUTRITION,
        )
        quiz2 = build_quiz(idx2)
        self.assertIn("11.5 元", self.quiz[1].reveal)
        self.assertIn("23.0 元", quiz2[1].reveal)


class TestScoreAndRank(unittest.TestCase):
    def setUp(self):
        self.idx = build()
        self.quiz = build_quiz(self.idx)

    def test_all_correct(self):
        self.assertEqual(
            score_quiz(self.quiz, correct_answers(self.quiz)), 3
        )

    def test_all_wrong_and_skip(self):
        wrong = tuple(
            (q.correct + 1) % len(q.options) for q in self.quiz
        )
        self.assertEqual(score_quiz(self.quiz, wrong), 0)
        # 没答（None）按错算 —— 不猜
        self.assertEqual(score_quiz(self.quiz, (None, None, None)), 0)

    def test_partial(self):
        answers = list(correct_answers(self.quiz))
        answers[0] = (answers[0] + 1) % len(self.quiz[0].options)
        self.assertEqual(score_quiz(self.quiz, tuple(answers)), 2)

    def test_ranks(self):
        self.assertEqual(rank_for(3, 3)[0], "麦门战神")
        self.assertEqual(rank_for(2, 3)[0], "麦门百晓生")
        self.assertEqual(rank_for(1, 3)[0], "麦门学徒")
        self.assertEqual(rank_for(0, 3)[0], "麦门路人")
        # 没答题数异常时也不崩
        self.assertEqual(rank_for(0, 0)[0], "麦门路人")

    def test_ranks_ordered(self):
        thresholds = [r[0] for r in RANKS]
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))


class TestQuizCard(unittest.TestCase):
    def setUp(self):
        self.idx = build()
        self.quiz = build_quiz(self.idx)
        self.answers = correct_answers(self.quiz)

    def test_produces_complete_html(self):
        html = render_quiz_card(self.idx, self.answers)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        self.assertIn("<meta charset", html)

    def test_rank_title_in_hero(self):
        html = render_quiz_card(self.idx, self.answers)
        self.assertIn("麦门战神", html)
        self.assertIn("答对", html)
        self.assertIn("3</b> / 3", html)

    def test_reveals_present_with_real_numbers(self):
        html = render_quiz_card(self.idx, self.answers)
        self.assertIn("逐题复盘", html)
        self.assertIn("1.71", html)   # 鸡排每元蛋白
        self.assertIn("27", html)     # 巨无霸总量
        self.assertIn("纯牛奶(盒装)", html)

    def test_wrong_answers_marked(self):
        wrong = tuple((q.correct + 1) % len(q.options) for q in self.quiz)
        html = render_quiz_card(self.idx, wrong)
        self.assertIn("qz-bad", html)
        self.assertIn("麦门路人", html)
        self.assertIn("你答了", html)

    def test_sticker_only_with_reversal(self):
        html = render_quiz_card(self.idx, self.answers)
        self.assertIn("每元蛋白王", html)  # fixture 反转成立，贴纸必须出现

    def test_coverage_disclosure_present(self):
        html = render_quiz_card(self.idx, self.answers)
        self.assertIn("款在售", html)
        self.assertIn("不参与推荐", html)

    def test_store_name_escaped(self):
        html = render_quiz_card(
            self.idx, self.answers, store_name="<script>x</script>"
        )
        self.assertNotIn("<script>x</script>", html)

    def test_footer_always_carries_repo_link(self):
        """落款恒定带开源链接（没传 project_url 兜底 PROJECT_URL）。"""
        from card import PROJECT_URL

        without = render_quiz_card(self.idx, self.answers)
        self.assertIn(PROJECT_URL, without)
        with_url = render_quiz_card(
            self.idx, self.answers, project_url="https://example.com/x"
        )
        self.assertIn("https://example.com/x", with_url)

    def test_all_styles_render(self):
        for style in STYLES:
            html = render_quiz_card(self.idx, self.answers, style=style)
            self.assertIn(f't-{style}"', html)
            self.assertIn("麦门战神", html)
            self.assertIn("逐题复盘", html)

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            render_quiz_card(self.idx, self.answers, style="赛博")

    def test_answer_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            render_quiz_card(self.idx, (0, 0))

    def test_empty_index_renders_honest(self):
        from fuel_index import FuelIndex

        empty = FuelIndex(items=(), menu_total=0, matched=0)
        html = render_quiz_card(empty, ())
        self.assertIn("<html", html)
        self.assertIn("战力测试", html)
        self.assertIn("不拿估算值凑数", html)


if __name__ == "__main__":
    unittest.main()


class TestFrameRegistry(unittest.TestCase):
    """梗壳注册表的完整性：50 帧、六来源、槽位合法、可安全格式化。"""

    # T4 已从名单里去掉：梗壳第二批把它清空了（原来挂着 6 个永远不会被抽到的壳）。
    # 现在任何落在 T4 的帧都会被 test_allowed_slots_and_modes 拦下。
    ALLOWED_SLOTS = {"T1", "T2", "T3", "T5"}
    ALLOWED_MODES = {"roast", "persona", "scene", "dialogue", "paper", "series"}
    # 帧模板允许的占位符（语义：A=贵的知名款 B=效率冠军 C/D=干扰款）
    ALLOWED_PLACEHOLDERS = {"{A}", "{B}", "{C}", "{D}", "{价格A}", "{价格B}"}

    def test_fifty_frames(self):
        self.assertEqual(len(FRAMES), 50)

    def test_keys_unique(self):
        keys = [f.key for f in FRAMES]
        self.assertEqual(len(set(keys)), len(keys))

    def test_slots_and_modes_valid(self):
        for f in FRAMES:
            self.assertIn(f.slot, self.ALLOWED_SLOTS, f"{f.key} 槽位非法")
            self.assertIn(f.mode, self.ALLOWED_MODES, f"{f.key} mode 非法")

    def test_every_slot_covered(self):
        for slot in self.ALLOWED_SLOTS:
            self.assertTrue(
                any(f.slot == slot for f in FRAMES), f"槽位 {slot} 没有帧"
            )

    def test_every_mode_has_multiple_frames(self):
        for mode in self.ALLOWED_MODES:
            n = sum(1 for f in FRAMES if f.mode == mode)
            self.assertGreaterEqual(n, 5, f"mode {mode} 帧数太少，抽不出多样性")

    # 能被 build_quiz 真正生产出来的槽位（即 _slot_of 的映射目标）
    LIVE_SLOTS = ("T1", "T2", "T3", "T5")
    # 死槽位已清零：梗壳第二批把原来挂在 T4（永远不会被抽到）的 6 个壳
    # 全部重写并搬进了活槽位。这里留空列表而不是删掉断言 ——
    # 下次谁再写出一个没人抽的槽位，test_dead_slots_are_explicit 会立刻红。
    KNOWN_DEAD_SLOTS: tuple[str, ...] = ()

    def test_every_live_slot_has_enough_frames(self):
        """活槽位每档至少 3 帧 —— 否则同一门店连开两次就会撞上同一套题面。"""
        for slot in self.LIVE_SLOTS:
            n = sum(1 for f in FRAMES if f.slot == slot)
            self.assertGreaterEqual(n, 3, f"槽位 {slot} 只有 {n} 帧，太容易重复")

    def test_dead_slots_are_explicit(self):
        """死槽位只能是已知的那几个（现在是零个）。

        这条防的是"悄悄写了一批永远不会被抽到的壳"：新增槽位忘了配 _slot_of 映射，
        或者写壳时把 slot 拼错，这里都会红。
        """
        for f in FRAMES:
            if f.slot not in self.LIVE_SLOTS:
                self.assertIn(
                    f.slot,
                    self.KNOWN_DEAD_SLOTS,
                    f"{f.key} 落在没人会抽的槽位 {f.slot}",
                )

    def test_wide_questions_never_get_pair_ask_frames(self):
        """四选一的题不许配「{A} 和 {B} 谁高」式的壳。

        这是本次补的一个真实缺陷：T2（每元蛋白）在「反转对」分支是 2 选项、
        在「找冠军」分支是 4 选项。点名比两个的壳一旦配到 4 选项题上，
        正确答案可能是第三个 —— 题面就成了错题。守卫在 _pick_frames 里，
        这里用一道假的四选一题反复抽，断言抽到的壳都不是点名对比式。
        """
        wide = Question(
            key="per_yuan",
            text="x",
            options=("甲", "乙", "丙", "丁"),
            correct=0,
            reveal="",
        )
        picked = [f for f in (_pick_frames([wide], random.Random(s))[0] for s in range(300)) if f]
        self.assertTrue(picked, "四选一题一个壳都抽不到")
        for f in picked:
            self.assertFalse(
                _pair_ask(f), f"四选一题配到了点名对比式的壳：{f.key}"
            )
        # 配对题（3 选项）仍然应该能抽到点名对比式的壳（否则那群壳就白写了）
        narrow = Question(
            key="per_yuan",
            text="x",
            options=("甲", "乙", "一样多"),
            correct=0,
            reveal="",
        )
        got = {_pick_frames([narrow], random.Random(s))[0].key for s in range(300)}
        self.assertTrue(
            any(_pair_ask(f) for f in FRAMES if f.key in got),
            "两选一的题抽不到任何点名对比式的壳，T2 的 pair 壳等于被废了",
        )

    def test_question_text_has_no_reporting_label(self):
        """题面不许贴「问题：」这类报题标签 —— 那是第一轮被砍掉的病。

        有意豁免：「问：」在询问笔录 / 听证记录里是文体自带的记录格式，不禁；
        「…小问题：」「…第一问：」出现在句中，也不禁。只禁行首的「问题：」。
        """
        import re as _re

        for f in FRAMES:
            self.assertIsNone(
                _re.search(r"^\s*问题：", f.text, _re.M),
                f"{f.key} 的行首出现报题标签「问题：」",
            )
            for bad in ("先算笔账", "别猜了，做题"):
                self.assertNotIn(bad, f.text, f"{f.key} 含报题标签「{bad}」")

    def test_templates_format_safely(self):
        """所有帧模板用完整槽位字典格式化，不抛 KeyError。"""
        slots = {"A": "甲", "B": "乙", "C": "丙", "D": "丁", "价格A": "1", "价格B": "2"}
        for f in FRAMES:
            try:
                f.text.format(**slots)
            except (KeyError, IndexError, ValueError) as exc:
                self.fail(f"{f.key} 格式化失败：{exc}")

    def test_no_stray_placeholders(self):
        """只允许 {A}{B}{C}{D}{价格A}{价格B} —— 禁止把答案数字写进模板。"""
        import re

        for f in FRAMES:
            found = set(re.findall(r"\{[^}]*\}", f.text))
            self.assertTrue(
                found <= self.ALLOWED_PLACEHOLDERS,
                f"{f.key} 含非法占位符：{found - self.ALLOWED_PLACEHOLDERS}",
            )

    def test_role_semantics_are_stable(self):
        """角色敏感帧用 A=贵/B=冠军 的固定语义（相亲大会的排面话术）。

        锁的是**语义**不是原句：A 必须说「我贵」，这样它才只能配到
        「贵的那个当诱饵」的题上。措辞改过（第二批把「自我介绍」改成了
        「一坐下就自我介绍」），语义没动，所以断言跟着放松到那一句。
        """
        text = next(f.text for f in FRAMES if f.key == "persona_blinddate")
        self.assertIn("自我介绍：「我贵，但我有排面。」", text)
        self.assertIn("{A}", text.split("自我介绍")[0], "说「我贵」的必须是 {A}")


class TestFramedQuiz(unittest.TestCase):
    """帧只换壳：选项、正确答案、真实数字一个都不碰。"""

    def setUp(self):
        import random

        self.idx = build()
        self.rng = random.Random(42)
        self.quiz = build_quiz(self.idx, rng=self.rng)

    def test_framed_texts_differ_from_base(self):
        """题面必须是梗壳文本，不再是裸数据句式。"""
        for q in self.quiz:
            self.assertNotIn("谁的蛋白质更多？", q.text)
            self.assertTrue(len(q.text) > 10)

    def test_correct_answers_unchanged_by_framing(self):
        """套帧不影响答案：按 correct 作答必须满分。"""
        self.assertEqual(score_quiz(self.quiz, correct_answers(self.quiz)), 3)

    def test_modes_and_frames_not_repeated_in_one_session(self):
        """同场 3 题 mode 不重复、帧不重复。"""
        import random

        from quiz import _pick_frames

        # 直接验证 _pick_frames 的约束。选项数按真实分支给：
        # 配对题 3 个（两个餐品 + 「一样多」）、找冠军题 4 个。
        def q(key, n, opts):
            return Question(key=key, text="x", options=opts, correct=0, reveal="")

        picked = _pick_frames(
            [
                q("protein_total", 3, ("甲", "乙", "一样多")),
                q("per_yuan", 3, ("甲", "乙", "一样多")),
                q("calcium_per_yuan", 4, ("甲", "乙", "丙", "丁")),
            ],
            random.Random(7),
        )
        self.assertEqual(len(picked), 3)
        self.assertTrue(all(p is not None for p in picked))
        self.assertEqual(len({p.mode for p in picked}), 3)
        self.assertEqual(len({p.key for p in picked}), 3)

    def test_reveal_keeps_real_numbers(self):
        """揭示层必须保留真实数据揭示（帧只往后面接调味句）。"""
        for q in self.quiz:
            self.assertRegex(q.reveal, r"\d")

    def test_same_store_same_frame_with_seed(self):
        """同门店同 seed → 同题面（可复现，可测试）。"""
        import random

        q1 = build_quiz(self.idx, rng=random.Random(42))
        q2 = build_quiz(self.idx, rng=random.Random(42))
        self.assertEqual([q.text for q in q1], [q.text for q in q2])

    def test_different_seed_can_change_frame(self):
        """不同 seed 有机会抽到不同帧（10 个 seed 里至少出现 2 种题面）。"""
        import random

        texts = set()
        for seed in range(10):
            quiz = build_quiz(self.idx, rng=random.Random(seed))
            texts.add(quiz[0].text)
        self.assertGreaterEqual(len(texts), 2)

    def test_empty_index_no_frames(self):
        from fuel_index import FuelIndex

        empty = FuelIndex(items=(), menu_total=0, matched=0)
        self.assertEqual(build_quiz(empty), ())


class TestFramesNoSpoiler(unittest.TestCase):
    """帧面纪律：不许把答案写进题干，不许假设数据结果。

    两次真实事故（用户实测 README 样本时发现）：
    1. Q3 帧面写「两个大汉抢最后一盒纯牛奶」——钙王恰好是牛奶时题干即答案；
       换个门店钙王变了，帧还变成错误陈述
    2. Q1 揭示写「但先别急——看下一题」——帧是随机套的，没有确定的下一题
    """

    # 故事为「引用的实测事实」的帧（四城七店真实记录，README 有据）——唯一豁免
    CITED_FACT_FRAMES = {"series_s1"}
    # 已知餐品名：帧模板硬编码任何一个，都是在假设数据结果
    KNOWN_ITEMS = (
        "巨无霸", "鸡排", "吉士", "麦辣", "板烧", "安格斯", "牛奶", "薯条",
        "可乐", "新地", "麦旋风", "香芋", "菠萝派", "鳕鱼", "鸡翅", "蛋挞",
    )

    def setUp(self):
        self.idx = build()

    def test_no_hardcoded_items_in_frame_templates(self):
        """帧模板（题面 + 调味句）不许出现真实餐品名。"""
        for f in FRAMES:
            if f.key in self.CITED_FACT_FRAMES:
                continue
            for part in (f.text, f.flavor or ""):
                for item in self.KNOWN_ITEMS:
                    self.assertNotIn(
                        item, part,
                        f"帧 {f.key} 硬编码了「{item}」——帧不能假设数据结果",
                    )

    def test_champion_questions_hide_the_answer(self):
        """找冠军型题（T3/T4/T5）：题干不得包含正确答案的核心名。

        核心名 = 去掉括号规格的名字（「纯牛奶(盒装)」→「纯牛奶」）——
        防的是「题干写牛奶、答案是纯牛奶(盒装)」这类子串泄题。
        """
        import random
        import re

        for seed in range(30):
            quiz = build_quiz(self.idx, rng=random.Random(seed))
            for q in quiz:
                if q.key not in ("calcium_per_yuan", "protein_per_yuan", "kcal"):
                    continue
                answer = q.options[q.correct]
                core = re.sub(r"[（(].*?[）)]", "", answer)
                self.assertNotIn(
                    core, q.text,
                    f"题干泄题：正确答案「{core}」出现在题面里",
                )

    def test_reveals_never_promise_a_next_question(self):
        """揭示不许拿「下一题」当承诺——帧随机，没有确定的下一题。"""
        import random

        for seed in range(30):
            quiz = build_quiz(self.idx, rng=random.Random(seed))
            for q in quiz:
                self.assertNotIn("下一题", q.reveal, f"{q.key} 的揭示在承诺下一题")
