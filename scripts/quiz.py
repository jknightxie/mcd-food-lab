"""麦门战力测试 —— 把「每元效率」变成一场 3 题小测。

同赛道已验证「玩起来」的东西才能拿星（人格测试 35★、求签 29★），
但人格和运势都已被占位，而且都与营养数据脱钩。没人做过的：
**用官方实测数据考用户** —— 并且这套题自带反转：

    巨无霸蛋白质总量更多（27g > 鸡排 24g），
    但每 1 元买到的蛋白反而更少（1.06 < 1.71 g/元）。

第 1 题答「巨无霸」的人，第 2 题多半翻车 —— **反转就是传播钩子**。
答完出段位（麦门路人 → 麦门战神），段位卡天生适合晒图。

三层结构（数字纪律自上而下收紧）：

    数据层   build_quiz：题目/选项/正确答案全部由当前门店实时数据生成，
             模板里没有任何硬编码的示例数字；门店撑不起反转时自动换
             「找冠军」型题，绝不硬凑
    帧层     FRAMES：50 个梗壳（六种喜感来源混编），只换题面外壳与
             加一句调味揭示 —— 选项、正确答案、真实数字一个都不碰
    装配层  build_quiz 按题型槽位随机套帧，同场 3 题 mode 不重复、
             帧不重复；角色敏感的帧用固定槽位语义（A=贵的知名款，
             B=效率冠军），保证「我贵但我有排面」的永远是贵的那位
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from fuel_index import FuelIndex, FuelItem, _fmt

__all__ = [
    "Question",
    "Frame",
    "FRAMES",
    "build_quiz",
    "score_quiz",
    "rank_for",
    "reversal_pair",
    "RANKS",
]

# 被公认为「麦当劳正餐代表」的那些名字 —— 出题时当诱饵/反转对象用
_FAMOUS_HINTS = ("巨无霸", "板烧", "麦辣", "吉士", "鳕鱼", "麦香")


def is_famous(name: str) -> bool:
    return any(h in name for h in _FAMOUS_HINTS)


@dataclass(frozen=True)
class Question:
    """一道题。text/options/reveal 里的每个数字都来自实时数据。"""

    key: str  # 'protein_total' | 'per_yuan' | 'calcium' | 'kcal'
    text: str
    options: tuple[str, ...]
    correct: int  # 正确选项下标
    reveal: str  # 揭示语：反转由真实数字自己讲

    def is_correct(self, answer: int | None) -> bool:
        return answer is not None and answer == self.correct


@dataclass(frozen=True)
class Frame:
    """一个梗壳。只提供题面模板与调味揭示，不碰数据与选项。

    `text` 模板允许的占位符：{A} {B} {C} {D}（餐品名，语义见 _slots）
    与 {价格A} {价格B}（情境数字）。**禁止出现任何写死的数字**——
    梗里的数字（凌晨 1:47、¥26.5）只允许作为引用事实存在，不进模板。
    """

    key: str
    mode: str  # roast 毒舌 / persona 拟人 / scene 场景 / dialogue 对话 /
    #            paper 公文 / series 连续剧
    slot: str  # T1 总量陷阱 / T2 每元 / T3 补钙王 / T4 蛋白王 / T5 省热王
    text: str
    flavor: str = ""  # 调味揭示：接在真实数字揭示后面的一句损赞


# ── 梗壳注册表（50 帧 · 六来源混编）────────────────────────────────────

FRAMES: tuple[Frame, ...] = (
    # 一、毒舌吐槽（主持人有脾气）
    Frame("roast_again", "roast", "T2",
          "「还是{A}吧。」\n同一个人今天说了两遍，中间隔了四秒。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "那四秒里他没在比较。"),
    Frame("roast_gymcard", "roast", "T2",
          "年卡剩 341 天，他去了 47 次。\n46 次点的是 {A}。{B} 一次没点过。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "47 次里，没一次点开过营养表。"),
    Frame("roast_oldbrand", "roast", "T1",
          "「{A}，老牌子，放心。」\n——他说这句话的时候，没看过 {B} 的价签。\n\n{A} 和 {B}，谁的蛋白更多？",
          "那三秒他在换算，不是在犹豫。"),
    Frame("roast_expensive", "roast", "T2",
          "「贵有贵的道理。」\n这句话柜台这周听了 6 次。没人说过是什么道理。\n\n每 1 元蛋白，{A} 和 {B} 谁高？",
          "第 7 次听到时，可以把这题报给他。"),
    Frame("roast_8min", "roast", "T2",
          "点餐机前站八分钟，{A} 加了又退、退了又加。\n最后点的是上次那款。{B} 只露过一秒的脸。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "那一秒是 {B} 今天最好的成绩。"),
    Frame("roast_allwant", "roast", "T2",
          "「小孩子才做选择，大人全都要。」\n购物车里三样，预算是两个人的。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "那份草稿一直没提交，它比人清醒。"),
    Frame("roast_mirror", "roast", "T2",
          "镜子前停了两秒，柜台前停了四分钟。\n四分钟里，他从没想过这个问题：\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "镜子管不了这个。"),
    Frame("roast_excuse", "roast", "T2",
          "上周「犒劳自己」17 次，「明天开始」9 次。\n「{A} 每 1 元蛋白比 {B} 高」——0 次。\n\n{A} 和 {B}，谁高？",
          "统计口径没错，就是没人说过。"),
    # 二、拟人选秀（餐品当人）
    Frame("persona_101", "persona", "T3",
          "《麦门 101》决赛，四位练习生争一个 C 位。\n你的胃先投了票，营养表的票随后才开。\n\n全店每 1 元补钙最高的那款，是哪个？",
          "胃不参与计票，它只负责举手。"),
    Frame("persona_blinddate", "persona", "T2",
          "汉堡界相亲大会。{A} 一坐下就自我介绍：「我贵，但我有排面。」\n女嘉宾没接话，低头翻了一张表。\n\n全店每 1 元蛋白最高的那款，是哪个？",
          "「排面」没写在那张表的任何一栏里。"),
    Frame("persona_olympic", "persona", "T1",
          "麦门奥运会决赛，只剩两位选手：{A} 和 {B}。\n颁奖台搭好了，主持人手卡上写着「蛋白质总量」。\n\n{A} 和 {B}，谁的蛋白更多？",
          "台下有人举着「每元」的牌子，被保安请出去了。"),
    Frame("persona_showdown", "persona", "T2",
          "《王牌对王牌》麦门专场，A 队先出场，掌声很响。\n节目组把两队的小票都收上来，说要现场核对一个数字。\n\n每 1 元蛋白最高的那队，是哪一款？",
          "掌声不计分，小票计。"),
    Frame("persona_matchmaking", "persona", "T5",
          "汉堡们参加《非诚勿扰》，第一位男嘉宾介绍完毕。\n女嘉宾只提了一个要求：「我要每 1 元热量最低的那种。」灯灭了七盏。\n\n全店每 1 元热量最低的那款，是哪个？",
          "灯灭得快，说明这个要求不常见。"),
    Frame("persona_rap", "persona", "T5",
          "《中国有新说唱》麦门分赛。第一位选手用 freestyle 讲完了自己的配料。\n评委没点评，低头算了三秒。\n\n每 1 元热量最低的那款，是哪个？",
          "Flow 可以 freestyle，热量不行。"),
    Frame("persona_debut", "persona", "T3",
          "出道夜。四个名字念完，灯光打在最贵的那位身上。\n台下没人喊他的名字——几个人在低声问「这个多少钱来着」。\n\n每 1 元补钙最高的那款，是哪个？",
          "灯光跟着价钱走，跟钙没关系。"),
    Frame("persona_voice", "persona", "T3",
          "汉堡好声音总决赛。四位学员唱完，导师问的不是音准。\n「你每 1 元能给多少毫克钙？」\n\n每 1 元补钙最高的那款，是哪个？",
          "转身的和没转身的，都在等这个数。"),
    # 三、场景剧（窘迫时刻代入）
    Frame("scene_latenight", "scene", "T5",
          "凌晨一点四十七分，加班结束。他走进麦当劳，店员眼皮都没抬。\n这个点还愿意算账的人不多，他是其中一个。\n\n全店每 1 元热量最低的那款，是哪个？",
          "夜越深，越要算清楚再睡。"),
    Frame("scene_milk", "scene", "T3",
          "健身房里两个大汉同时把手伸向冷藏柜最后一格。\n一个说「我先看见的」，另一个说「我先练完的」。店员没插话。\n\n全店每 1 元补钙最狠的是哪款？",
          "抢了一分钟，谁也没算过这一格值多少。"),
    Frame("scene_reunion", "scene", "T1",
          "同学聚会轮到他点餐。预算紧张，又不能跌份。\n他把菜单翻了两遍，最后问了句「{A} 和 {B} 哪个蛋白多」——没人接。\n\n{A} 和 {B}，谁的蛋白更多？",
          "没人接得住，但数据接得住。"),
    Frame("scene_diner", "scene", "T2",
          "深夜食堂（麦门分堂），老板说他今天会给最值的那份。\n{A} 被端了上来。\n但老板的「最值」是他自己的标准，不是这张表的标准。\n\n全店每 1 元蛋白最高的是哪款？",
          "老板的标准很好，只是没法复核。"),
    Frame("scene_birthday", "scene", "T3",
          "小孩在麦当劳过生日，许愿说「希望每 1 元都能多补点钙」。\n他妈妈愣了一下，问服务员：你们这有没有那种表？\n\n每 1 元补钙最高的那款，是哪个？",
          "生日愿望可以随便许，营养表不行。"),
    Frame("scene_diet7", "scene", "T5",
          "减脂第七天，他站在点餐机前，像站在审讯室。\n屏幕上每一款都在问他同一个问题：你确定？\n\n全店每 1 元热量最低的那款，是哪个？",
          "审查他的人是他自己，但数据比他冷静。"),
    Frame("scene_mom", "scene", "T1",
          "他妈发来微信：「少点那些没营养的。」\n他回了个「知道」，然后在 {A} 和 {B} 之间选了整整四分钟。\n四分钟里他没查过任何一个数。\n\n{A} 和 {B}，谁的蛋白更多？",
          "「知道」这两个字，覆盖不了任何东西。"),
    Frame("scene_2230", "scene", "T5",
          "加班到二十二点半，公司楼下只剩这一家。\n他想吃点有营养的，又想少吃点热量——这两个要求第一次打起来。\n\n每 1 元热量最低的那款，是哪个？",
          "楼下只剩一家的时候，效率就是正义。"),
    # 四、对话体（两个人的相声）
    Frame("dialogue_guess", "dialogue", "T1",
          "「我猜 {B} 的蛋白比 {A} 多。」\n「为什么？」\n「因为它贵。」\n\n{A} 和 {B}，谁的蛋白更多？",
          "贵和多是两件事，只是经常被放在一起猜。"),
    Frame("dialogue_fat", "dialogue", "T5",
          "女朋友：「我是不是胖了？」\n他：「……」\n女朋友：「你盯着手机干什么？」\n他：「没干什么。」\n\n全店每 1 元热量最低的那款，是哪个？",
          "屏幕上那行按热量升序排着，他没敢说自己在看什么。"),
    Frame("dialogue_signature", "dialogue", "T2",
          "「推荐本店招牌！」\n「招牌的每元蛋白多少？」\n「……招牌就是招牌。」\n\n全店每 1 元蛋白最高的那款，是哪个？",
          "招牌是销量说的，不是每元说的。"),
    Frame("dialogue_nutrition", "dialogue", "T3",
          "「这款有营养吗？」\n「哪方面？」\n「就……营养啊。」\n\n每 1 元补钙最高的那款，是哪个？",
          "「营养」得先拆成一个能算的东西。"),
    Frame("dialogue_voice60", "dialogue", "T5",
          "六十秒的语音，他听了三遍。\n前五十七秒在讲今天遇到了谁，最后三秒说「帮我看看哪款热量低」。\n\n每 1 元热量最低的那款，是哪个？",
          "重点永远在最后三秒。"),
    Frame("dialogue_groupchat", "dialogue", "T3",
          "群里问「今天吃什么」，二十条消息里十九条在报菜名。\n第二十条是他发的一张营养表截图。\n然后群就安静了。\n\n全店每 1 元补钙最高的那款，是哪个？",
          "沉默不是因为无语，是因为大家都在看那张表。"),
    Frame("dialogue_bet", "dialogue", "T2",
          "「我押 {A}，每元蛋白肯定它最高。」\n「赌什么？」\n「赌这顿饭。」\n——这顿饭的价钱，正好是这道题要用的分母。\n\n全店每 1 元蛋白最高的是哪款？",
          "赌饭可以，赌数据不行。"),
    Frame("dialogue_waiting", "dialogue", "T1",
          "「就这些？」\n「等人。」\n「等人来之前，先想一个数：{A} 和 {B} 谁的蛋白更多？」\n「……你先算吧。」\n\n{A} 和 {B}，谁的蛋白更多？",
          "他最后也没算。人倒是等来了。"),
    # 五、荒诞公文（学术/官僚腔说汉堡）
    Frame("paper_journal", "paper", "T2",
          "简报：718 条在售记录，能对上营养的约 141 条。\n剩下的不是没营养，是对不上号。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "对不上号的那些，我们一个都没编。"),
    Frame("paper_hearing", "paper", "T2",
          "问：您为什么选 {A}？\n答：行业领先。\n问：{B} 呢？答：那是另一个价位的东西。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "「行业领先」四个字，一问细节就散架。"),
    Frame("paper_notice", "paper", "T3",
          "评选公示：每 1 元补钙标兵。\n办法：钙含量 ÷ 单价，四舍五入到两位。异议期：三秒。\n\n名单空着，请指认。",
          "历届标兵都是评出来的，不是点出来的。"),
    Frame("paper_bulletin", "paper", "T3",
          "通报：柜台前平均停留 1 分 42 秒，\n最常见的是看菜单，最少见的是打开营养表。\n\n全店每 1 元补钙最高的是哪款？",
          "这两句放在一起，就是全部内容。"),
    Frame("paper_thesis", "paper", "T1",
          "结题摘要：蛋白总量最高的那几款，价格很少排在最后。\n结论：这个发现不构成任何购买建议。\n\n{A} 和 {B}，谁的蛋白更多？",
          "总量高只说明它大份，不说明它划算。"),
    Frame("paper_redhead", "paper", "T2",
          "举报事项：本人观察三个月，未见任何顾客在点单前打开营养表。\n被举报人：自己。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "举报成立，被举报人有权自行改正。"),
    Frame("paper_witness2", "paper", "T2",
          "问：你说 {A} 更值，凭什么？\n答：排队的时候听见的。\n记录人：{B} 从没出现在那条队伍里。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "「大家」这个词，指的都是排在他前面的那个人。"),
    Frame("paper_premium", "paper", "T2",
          "成本的最后一项不在官方口径里，叫排面溢价。\n{A} 的单价里有，{B} 没有。\n\n每 1 元蛋白，{A} 和 {B} 谁高？",
          "它没写进任何一份财报，但每年都在收。"),
    Frame("paper_errata", "paper", "T1",
          "勘误：上期按蛋白总量排名，{A} 居首。\n有读者来信：换个算法，榜首就换人了。\n\n先核一个数：{A} 和 {B}，谁的蛋白更多？",
          "两种算法都抄对了，分歧在有没有除以价格。"),
    # 六、连续剧（小明的麦当劳算账宇宙）
    Frame("series_s1", "series", "T1",
          "第一季。小明第一次想知道 {A} 和 {B} 的区别。\n他问了店员，店员说「都好吃」。\n他信了。\n\n{A} 和 {B}，谁的蛋白更多？",
          "「都好吃」是真的，但答的不是这个问题。"),
    Frame("series_s2", "series", "T1",
          "第二季。小明把 {A} 和 {B} 摆在一起拍了张照。\n评论区说「左边那个看着实在」。\n\n{A} 和 {B}，谁的蛋白更多？",
          "照片看得出大小，看不出蛋白。"),
    Frame("series_s3", "series", "T2",
          "第三季。小明开始留意小票了，但他只看最下面那个数。\n看了七次，他仍然不知道那是这一单的、不是这一口的。\n\n全店每 1 元蛋白最高的是哪款？",
          "小票最下面那个数，是这一单的，不是这一口的。"),
    Frame("series_s4", "series", "T3",
          "第四季。小明开始给别人推荐了，理由是「这个我常点」。\n「常点」和「划算」之间，隔着一个除法。\n\n每 1 元补钙最高的那款，是哪个？",
          "常点只能说明习惯，不能说明效率。"),
    Frame("series_s5", "series", "T5",
          "第五季。小明刷到一条帖子说「吃这个不会胖」。\n他转给了三个人。三个人都信了。\n\n全店每 1 元热量最低的那款，是哪个？",
          "「不会胖」和「热量低」之间隔着一整个数量级。"),
    Frame("series_s6", "series", "T3",
          "第六季。小明给怀孕的姐姐点餐，第一次主动问「哪个补钙」。\n这是他全剧唯一一次主动问对的。\n\n每 1 元补钙最高的那款，是哪个？",
          "问对了，是因为这次他不敢猜。"),
    Frame("series_s7", "series", "T5",
          "第七季。小明的体重没变，他只做了一件事：把小票留下来了。\n小票上唯一能算的，是每元。\n\n每 1 元热量最低的那款，是哪个？",
          "他没少吃，他只是开始算了。"),
    Frame("series_s8", "series", "T3",
          "第八季。小明成了「麦门管家」，别人问他秘诀。\n他说：我每次都先看一栏，那一栏叫每元。\n\n每 1 元补钙最高的那款，是哪个？",
          "秘决是四个字：先看那一栏。"),
    Frame("series_final", "series", "T5",
          "季终。小明终于明白有些账算不清——比如「为什么它更贵、每 1 元热量却更低」。\n\n每 1 元热量最低的那款，是哪个？",
          "他把问号留在了最后一格。"),
)

# 有帧的槽位。T4 已于梗壳第二批清零 —— `_slot_of` 仍留它当"未知题型"的兜底，
# 但那意味着这道题拿不到壳、会退回裸数据句式；谁再写出一个没人抽的槽位，
# tests/test_quiz.py::test_dead_slots_are_explicit 会立刻红。
_SLOTS = ("T1", "T2", "T3", "T5")
_MODES = ("roast", "persona", "scene", "dialogue", "paper", "series")


# ── 出题 ────────────────────────────────────────────────────────────────

def _place(options: list[str], correct_idx: int, seed: int) -> tuple[tuple[str, ...], int]:
    """把正确选项轮转到 seed 决定的位置。

    不用 random：同一个门店每次生成的题面必须一致（可测试、可复现），
    但不同门店之间位置会错开，不至于「正确答案永远在 B」。
    """
    n = len(options)
    pos = seed % n
    rotated = options.copy()
    rotated.insert(0, rotated.pop(correct_idx))
    for _ in range(pos):
        rotated.insert(0, rotated.pop())
    return tuple(rotated), rotated.index(options[correct_idx])


def reversal_pair(index: FuelIndex) -> tuple[FuelItem, FuelItem] | None:
    """找「总量更多但每元更亏」的知名款反转对。

    反转必须同时满足两个条件才成立：
    1. 知名款蛋白质**总量**多于每元冠军
    2. 知名款的每元蛋白**低于**冠军

    候选不止一个时选**价差最大**的 —— 贵得最离谱的那个反转故事最强，
    这条规则完全由数据决定，不偏爱任何具体品名。
    战报卡的反差贴纸也用它 —— 同一个事实，出题和揭示共用。
    """
    champ = index.by("protein_per_yuan")[0]
    if champ.protein is None or champ.protein_per_yuan is None:
        return None
    candidates = []
    for item in index.by("protein_per_yuan")[1:]:
        if not is_famous(item.name):
            continue
        if item.protein is None or item.protein_per_yuan is None:
            continue
        if item.protein > champ.protein and item.protein_per_yuan < champ.protein_per_yuan:
            candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda i: i.price - champ.price), champ


def _champion_question(
    index: FuelIndex,
    key: str,
    lead: str,
    seed: int,
) -> tuple[Question, dict[str, str]]:
    """「找冠军」型题：从知名款+高价款里设诱饵，问全场每元冠军。"""
    champ = index.by(key)[0]
    champ_value = champ.metric(key)
    by_total = "calcium" if key == "calcium_per_yuan" else "protein"
    decoys: list[str] = []
    for item in index.by(by_total):
        if item.name != champ.name and item.name not in decoys:
            decoys.append(item.name)
        if len(decoys) >= 3:
            break
    if len(decoys) < 3:
        for item in index.by(key)[1:]:
            if item.name not in decoys:
                decoys.append(item.name)
            if len(decoys) >= 3:
                break
    options, correct = _place([champ.name] + decoys, 0, seed)
    unit = "mg/元" if key == "calcium_per_yuan" else "g/元"
    value_label = "毫克钙" if key == "calcium_per_yuan" else "克蛋白"
    reveal = (
        f"{champ.name}：每 1 元 = {_fmt(champ_value, 2)} {value_label}。"
        f"总量高的不一定是冠军 —— 除以价格才知道。"
    )
    question = Question(
        key=key,
        text=f"全店{lead}冠军是？",
        options=options,
        correct=correct,
        reveal=reveal,
    )
    slots = {
        "A": options[0],
        "B": options[1],
        "C": options[2],
        "D": options[3],
    }
    return question, slots


def _kcal_question(
    index: FuelIndex, seed: int
) -> tuple[Question, dict[str, str]]:
    """「每 1 元热量最低」找冠军题：诱饵从热量最高的几款里挑。"""
    by_k = sorted(
        (i for i in index.items if i.kcal_per_yuan is not None),
        key=lambda i: i.kcal_per_yuan,
    )
    champ_k = by_k[0]
    decoys: list[str] = []
    for item in by_k[::-1]:
        if item.name != champ_k.name and item.name not in decoys:
            decoys.append(item.name)
        if len(decoys) >= 3:
            break
    options, correct = _place([champ_k.name] + decoys, 0, seed + 2)
    question = Question(
        key="kcal",
        text="每 1 元吃到的热量最少的是？",
        options=options,
        correct=correct,
        reveal=(
            f"{champ_k.name}：{_fmt(champ_k.kcal_per_yuan, 1)} kcal/元。"
            f"总量高的不一定是冠军 —— 除以价格才知道。"
        ),
    )
    slots = {"A": options[0], "B": options[1], "C": options[2], "D": options[3]}
    return question, slots


def build_quiz(index: FuelIndex, rng: random.Random | None = None) -> tuple[Question, ...]:
    """从当前门店实时数据生成 3 道题，并套上随机梗壳。

    有反转对时：总量陷阱 → 每元反转 → 补钙王。
    没有时：三道「找冠军」型。题目顺序与内容完全由数据决定。

    帧层只换题面外壳 + 加一句调味揭示；选项、正确答案、真实数字
    一个都不碰。同场 3 题 mode 不重复、帧不重复。
    """
    if not index.items:
        return ()
    if rng is None:
        rng = random.Random()

    base: list[Question] = []
    slots_list: list[dict[str, str]] = []
    seed = len(index.items)

    pair = reversal_pair(index)
    if pair:
        famous, champ = pair
        pair_slots = {"A": famous.name, "B": champ.name}
        options, correct = _place([famous.name, champ.name, "一样多"], 0, seed)
        base.append(
            Question(
                key="protein_total",
                text=(
                    f"花 {_fmt(famous.price, 1)} 元的{famous.name}"
                    f" 和 {_fmt(champ.price, 1)} 元的{champ.name}，"
                    f"谁的蛋白质更多？"
                ),
                options=options,
                correct=correct,
                reveal=(
                    f"{famous.name} {_fmt(famous.protein)}g "
                    f"> {champ.name} {_fmt(champ.protein)}g。"
                    f"总量这一局，{famous.name}赢。"
                ),
            )
        )
        slots_list.append(pair_slots)
        ratio = champ.protein_per_yuan / famous.protein_per_yuan
        saved = famous.price - champ.price
        price_part = f"，还便宜 {_fmt(saved, 1)} 元" if saved >= 0.5 else ""
        base.append(
            Question(
                key="per_yuan",
                text="那每花 1 元，谁的蛋白质回报更高？",
                options=options,
                correct=options.index(champ.name),
                reveal=(
                    f"{champ.name} {_fmt(champ.protein_per_yuan, 2)} g/元 vs "
                    f"{famous.name} {_fmt(famous.protein_per_yuan, 2)} g/元 —— "
                    f"每元高 {(ratio - 1) * 100:.0f}%{price_part}。"
                    f"这就是「每元效率」存在的意义。"
                ),
            )
        )
        slots_list.append(pair_slots)
        # 第三题在「每元补钙」和「每元热量」之间轮换，各占一半。
        # 原来固定是补钙，图的是「总量陷阱 → 每元反转 → 补钙王」的收尾叙事；
        # 用户明确说不需要那个叙事，改成轮换 —— 好处是 T3 / T5 两个池子都能上桌，
        # 刷出来的题型也不再永远是那三种。
        # 用 rng 而不是 seed 掷币：seed 是门店餐品数，同一门店恒定，
        # 按它轮换等于不轮换，12 套题库会全部落到同一边。
        if rng.random() < 0.5:
            q, s = _champion_question(index, "calcium_per_yuan", "每 1 元补钙", seed + 1)
        else:
            q, s = _kcal_question(index, seed + 2)
        base.append(q)
        slots_list.append(s)
    else:
        q, s = _champion_question(index, "protein_per_yuan", "每 1 元补蛋白", seed)
        base.append(q)
        slots_list.append(s)
        q, s = _champion_question(index, "calcium_per_yuan", "每 1 元补钙", seed + 1)
        base.append(q)
        slots_list.append(s)
        q, s = _kcal_question(index, seed + 2)
        base.append(q)
        slots_list.append(s)

    return _apply_frames(base, slots_list, rng)


def _names_candidate(frame: Frame) -> bool:
    """壳里有没有点名某个候选（出现 {A}–{D} 任一）。

    **找冠军型题（4 选项）最怕这个**：题面里出现一个候选名，读者会把它当成
    "被隆重介绍的那个"，而它有可能就是正确答案 —— 等于泄题。
    配对题（3 选项）没这个问题：题面点名两个候选本身就是题目的一部分。

    tests/test_quiz.py::test_champion_questions_hide_the_answer 扫 30 个 seed 抓这个。
    """
    return any(ph in frame.text for ph in ("{A}", "{B}", "{C}", "{D}"))


def _pair_ask(frame: Frame) -> bool:
    """这个壳的问句是不是「点名的两人对比」（末行同时出现 {A} 和 {B}）。

    比 _names_candidate 更窄：只在末行出现两个占位符才算。
    留作独立判据是为了能单独断言"配对式问句可以留在 T2 给配对题用"。
    """
    ask = frame.text.strip().split("\n")[-1]
    return "{A}" in ask and "{B}" in ask


def _pick_frames(
    base: list[Question], rng: random.Random
) -> list[Frame | None]:
    """按题型槽位抽帧：同场 mode 不重复、帧不重复。

    槽位没有带新 mode 的帧可抽时（如 T2 的 mode 已被同场用掉），
    放宽到同 slot 内任意未用帧 —— 保证每道题都有壳。
    多选项题（>2 选项）额外跳过"点名两人对比"式的壳，见 _pair_ask。
    """
    slots = [_slot_of(q) for q in base]
    # 阈值是 4，不是 2：**配对题恒为 3 个选项**（两个餐品 + 「一样多」），
    # 而「找冠军」题恒为 4 个选项（冠军 + 3 个诱饵）。用 >2 当判据会把
    # 配对题也当成多选，把 T1 的壳全部跳过、题面退回裸数据句式。
    wide = [len(q.options) >= 4 for q in base]
    picked: list[Frame | None] = []
    used_modes: set[str] = set()
    used_keys: set[str] = set()
    for slot, is_wide in zip(slots, wide):
        ok = lambda f: not (is_wide and _names_candidate(f))  # noqa: E731
        pool = [
            f for f in FRAMES
            if f.slot == slot and f.mode not in used_modes and f.key not in used_keys and ok(f)
        ]
        if not pool:
            pool = [f for f in FRAMES if f.slot == slot and f.key not in used_keys and ok(f)]
        if not pool:
            picked.append(None)
            continue
        frame = rng.choice(pool)
        picked.append(frame)
        used_modes.add(frame.mode)
        used_keys.add(frame.key)
    return picked


def _apply_frames(
    base: list[Question],
    slots_list: list[dict[str, str]],
    rng: random.Random,
) -> tuple[Question, ...]:
    """套帧：换题面外壳 + 在真实揭示后接一句调味。数据与选项不动。"""
    frames = _pick_frames(base, rng)
    out = []
    for q, frame, slots in zip(base, frames, slots_list):
        if frame is None:
            out.append(q)
            continue
        text = frame.text.format(**slots)
        reveal = q.reveal
        if frame.flavor:
            reveal = f"{reveal}{frame.flavor}"
        out.append(
            Question(key=q.key, text=text, options=q.options, correct=q.correct, reveal=reveal)
        )
    return tuple(out)


def _slot_of(q: Question) -> str:
    """题目 key → 题型槽位。"""
    return {
        "protein_total": "T1",
        "per_yuan": "T2",
        "calcium_per_yuan": "T3",
        "kcal": "T5",
    }.get(q.key, "T4")


# ── 计分与段位 ──────────────────────────────────────────────────────────

def score_quiz(quiz: Iterable[Question], answers: Iterable[int | None]) -> int:
    """答对题数。没答（None）按错算 —— 不猜。"""
    return sum(1 for q, a in zip(quiz, answers) if q.is_correct(a))


# 段位：答对比例越高段位越高。标题玩「麦门」梗，副句只有幽默没有断言。
RANKS: tuple[tuple[float, str, str], ...] = (
    (1.0, "麦门战神", "官方营养库在你面前裸奔"),
    (2 / 3, "麦门百晓生", "每元意识已经觉醒"),
    (1 / 3, "麦门学徒", "巨无霸滤镜正在消退"),
    (0.0, "麦门路人", "你对麦当劳的力量一无所知"),
)


def rank_for(score: int, total: int) -> tuple[str, str]:
    """按答对比例定段位。"""
    if total <= 0:
        return RANKS[-1][1], RANKS[-1][2]
    ratio = score / total
    for threshold, title, tagline in RANKS:
        if ratio >= threshold:
            return title, tagline
    return RANKS[-1][1], RANKS[-1][2]
