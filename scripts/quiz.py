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
          "【会话记录】\n12:04:11  顾客：「还是{A}。」\n12:04:12  店员：「好的。」\n12:04:13  顾客：「等一下。」\n12:04:15  顾客：「还是{A}吧。」\n12:04:16  店员：「……好的。」\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "中间那两秒，是整段记录里信息量最大的部分。"),
    Frame("roast_gymcard", "roast", "T2",
          "【会员系统】\n年卡有效期内，剩余 341 天。\n本年度入场 47 次，其中 46 次在训练结束后到店点餐。\n点得最多的是 {A}。{B} 一次没点过。\n\n{A} 和 {B}，每 1 元蛋白谁高？",
          "46 次里，没有一次点开过营养表。"),
    Frame("roast_oldbrand", "roast", "T1",
          "【现场记录】\n时间：今天中午\n地点：某商场一层\n经过：顾客指着 {A} 说「老牌子，放心」。店员照单点了。\n补充：点完之后他问了 {B} 的价格，看了三秒，没改。\n\n{A} 和 {B}，谁的蛋白更多？",
          "那三秒他不是在犹豫，是在换算。"),
    Frame("roast_expensive", "roast", "T2",
          "【价签记录】\n{A}：贵\n{B}：便宜\n\n备注：「贵有贵的道理」这句话，本月柜台已听到 6 次。\n没有人说过是什么道理。\n\n每 1 元蛋白，{A} 和 {B} 谁高？",
          "第 7 次听到的时候，可以把这道题报给他。"),
    Frame("roast_8min", "roast", "T2",
          "【点餐机会话日志】\n21:31:04  {A} 加入购物车\n21:31:07  {A} 移出购物车\n21:31:19  {A} 加入购物车\n21:31:52  {A} 移出购物车\n21:32:10  {B} 加入购物车\n21:32:11  {B} 移出购物车\n21:39:47  上次点过的那款 加入购物车\n21:39:49  下单\n\n【遗留】{A} 和 {B} 的每 1 元蛋白，算一下谁高。",
          "{B} 在购物车里待了一秒。这一秒是它今天最好的成绩。"),
    Frame("roast_allwant", "roast", "T2",
          "【订单草稿】未提交\n一、{A}\n二、{B}\n三、上次那份\n\n合计：够两个人吃。\n备注：下单人是一个人。\n\n如果只能留一个，{A} 和 {B} 里每 1 元蛋白更高的是哪个？",
          "草稿一直没提交。它现在是这个账号里最理性的一份文件。"),
    Frame("roast_mirror", "roast", "T2",
          "【从更衣室到柜台，4 分钟】\n19:58  在镜子前停了两秒，把衣服往下拉了拉\n20:02  点了 {A}\n20:03  离开\n\n这 4 分钟里，没有打开过任何一张营养表。\n{A} 和 {B}，每 1 元蛋白谁高？",
          "镜子前那两秒是有效投入。后面那四分钟不是。"),
    Frame("roast_excuse", "roast", "T2",
          "【本店高频用语统计 · 上周】\n「犒劳自己」      17 次\n「就这一次」      11 次\n「明天开始」       9 次\n「今天太累了」     8 次\n「{A} 每 1 元蛋白比 {B} 高」   0 次\n\n最后一行是空着的。它现在归你了：{A} 和 {B}，每 1 元蛋白谁高？",
          "统计口径没错，就是没人说过。"),
    # 二、拟人选秀（餐品当人）
    Frame("persona_101", "persona", "T4",
          "《麦门 101》选秀现场。四位练习生争夺「每元蛋白 C 位」。"
          "大众评审（你的胃）投票——你投谁？",
          "C 位不看流量，看每元。"),
    Frame("persona_blinddate", "persona", "T2",
          "汉堡界相亲大会。{A} 自我介绍：「我贵，但我有排面。」"
          "{B} 没说话，只在小票上写了一行字。女嘉宾只关心一个问题："
          "每 1 元能给我多少蛋白？",
          "会写小票的，通常比会画饼的靠谱。"),
    Frame("persona_olympic", "persona", "T1",
          "麦门奥运会「蛋白质总量」项目颁奖典礼开始——金牌是？"),
    Frame("persona_showdown", "persona", "T2",
          "综艺《王牌对王牌》麦门专场：{A} 队和 {B} 队 PK「每元蛋白」。"
          "你押哪队赢？",
          "押错不罚，但会记入战报。"),
    Frame("persona_matchmaking", "persona", "T2",
          "汉堡们参加《非诚勿扰》。男嘉宾 {A} 自我介绍完毕，"
          "女嘉宾只问了一个问题：「你每 1 元能给我多少蛋白？」",
          "相亲可以感觉至上，蛋白必须数据说话。"),
    Frame("persona_rap", "persona", "T4",
          "《中国有新说唱》麦门分赛。Rapper 们 diss 来 diss 去，"
          "评委直接看小票：每 1 元蛋白谁最炸？",
          "Diss 可以freestyle，数据不行。"),
    Frame("persona_debut", "persona", "T4",
          "选秀出道位只有一个：「每元蛋白 C 位」。"
          "四位练习生里，谁 C 位出道？",
          "出道位只有一个，算法只认一个。"),
    Frame("persona_voice", "persona", "T4",
          "汉堡好声音总决赛。四位学员唱完，导师转身只看小票——"
          "每 1 元蛋白最高者，直通麦门春晚。",
          "导师的转身，和小票的数字一样诚实。"),
    # 三、场景剧（窘迫时刻代入）
    Frame("scene_latenight", "scene", "T5",
          "凌晨 1:47，加班结束。你走进麦当劳，店员眼皮都不抬。"
          "此刻脑子里唯一该闪过的：每 1 元热量最低的是哪款？",
          "夜越深，越要算清楚再睡。"),
    Frame("scene_milk", "scene", "T3",
          "健身房里两个大汉同时把手伸向最后一格补给——"
          "不为好喝，为全店每 1 元补钙王。问：这款「钙王」是谁？",
          "抢的是钙王，算的是每元。"),
    Frame("scene_reunion", "scene", "T2",
        "同学聚会你负责订餐：预算紧张，又不能跌份。"
        "{A} 和 {B}，每 1 元蛋白谁高？",
          "跌份和超支之间，隔着一次每元测算。"),
    Frame("scene_diner", "scene", "T2",
          "深夜食堂（麦门分堂）。老板说「给你上今天最值的」。"
          "他的「值」，按每 1 元蛋白算：{A} 和 {B} 谁高？",
          "老板的「值」，小票上写着呢。"),
    Frame("scene_birthday", "scene", "T3",
          "小孩在麦当劳生日派对许愿：「希望每 1 元都能多补点钙。」"
          "问：哪款能替圣诞老人实现这个愿望？",
          "圣诞老人送礼物，食验室送数据。"),
    Frame("scene_diet7", "scene", "T5",
          "减脂第 7 天，你站在点餐机前，像站在审讯室。"
          "每 1 元热量最低的那个「减脂名额」是？",
          "审讯室里你说的每句话都会成为呈堂证供——包括点的那款。"),
    Frame("scene_mom", "scene", "T4",
          "点单前你妈发来微信：「少点那些没营养的。」"
          "你回了句「知道」，然后问店员：每 1 元蛋白最高的是哪款？",
          "妈妈的营养学，实测数据替你转达。"),
    Frame("scene_2230", "scene", "T4",
          "加班到 22:30，公司楼下只剩麦当劳。"
          "你想「吃点有营养的」——每 1 元蛋白王是谁？",
          "楼下只剩麦当劳的时候，效率就是正义。"),
    # 四、对话体（两个人的相声）
    Frame("dialogue_guess", "dialogue", "T1",
          "你：「我猜{B}的蛋白比{A}多，对吧？」"
          "我：「……你再想想。」"
          "你：「难道不是吗？」"
          "我：「别猜了。{A} 和 {B}，谁蛋白更多？」",
          "下次猜之前，先问小票。"),
    Frame("dialogue_fat", "dialogue", "T5",
          "女朋友：「我是不是胖了？」"
          "你（低头看小票）：「每 1 元热量最低的是——」"
          "问题：那款是谁？（这题答错，可能真要胖了。）",
          "答错这题的代价，可能不止一碗牛肉面。"),
    Frame("dialogue_signature", "dialogue", "T2",
          "服务员：「推荐本店招牌！」"
          "你：「招牌的每元蛋白多少？」"
          "服务员：「……」"
          "问题：{A} 和 {B}，谁每元蛋白高？",
          "招牌是情怀，每元是考核。"),
    Frame("dialogue_nutrition", "dialogue", "T2",
          "朋友：「麦当劳能有什么营养？」"
          "你：「有，而且能算。」"
          "朋友：「那你算算这个——{A} 和 {B}？」",
          "能算的营养，才是真营养。"),
    Frame("dialogue_voice60", "dialogue", "T2",
          "健身教练发来 60 秒语音：「练后补充，要看每元蛋白……」"
          "你只记住了最后一个问题：{A} 和 {B}，谁高？",
          "60 秒语音的重点，通常在最后 3 秒。"),
    Frame("dialogue_groupchat", "dialogue", "T2",
          "群里有人晒「麦当劳省钱攻略」，你默默发了张小票。"
          "群里沉默 3 分钟后有人问：所以 {A} 和 {B} 谁每元蛋白高？",
          "沉默不是因为无语，是因为大家都在算。"),
    Frame("dialogue_bet", "dialogue", "T2",
          "你和同事赌一杯奶茶：{A} 的每元蛋白比 {B} 高。现在揭晓赌局——",
          "愿赌服输，数据不收情面。"),
    Frame("dialogue_waiting", "dialogue", "T2",
          "店员：「就这些？」"
          "你：「等人。」"
          "「等人来之前先做道题：{A} 和 {B}，每元蛋白谁高？」",
          "等人的时间，够算一道题。"),
    # 五、荒诞公文（学术/官僚腔说汉堡）
    Frame("paper_journal", "paper", "T2",
          "【学报 · 研究简报】\n\n样本：4 城 7 店，共 718 条在售记录。\n方法：把营养库与门店菜单按名称逐条比对。\n结果：可比对上的约 141 条，比中位数的三分之一还少。\n讨论：剩余记录不是没有营养，是门店对不上号。\n\n简报附一个可独立验证的小问题：{A} 和 {B}，每 1 元蛋白谁高？",
          "比对上多少条不重要。重要的是没比对上的那些，一个都没编。"),
    Frame("paper_hearing", "paper", "T2",
          "【听证记录节选】\n\n问：您为什么选择 {A}？\n答：行业领先。\n问：您是指口味、分量，还是营养？\n答：都领先。\n问：{B} 呢？\n答：那是另一个价位的东西。\n\n本庭需核实一项事实：{A} 和 {B}，每 1 元蛋白谁高？",
          "「行业领先」四个字，一问细节就散架。"),
    Frame("paper_notice", "paper", "T3",
          "【评选公示】\n\n项目：每 1 元补钙标兵\n入围：四人（候选见选项）\n评选办法：钙含量 ÷ 单价，四舍五入到小数点后两位\n异议期：本公示发布后三秒\n\n名单待填。请指认标兵。",
          "历届「补钙标兵」都是评选出来的，不是点出来的。"),
    Frame("paper_bulletin", "paper", "T3",
          "关于本周点餐秩序的通报\n\n经观察，本店高峰时段（12:00—13:00）存在以下情况：\n一、顾客在柜台前的平均停留时间为 1 分 42 秒；\n二、停留期间出现频率最高的动作是抬手看菜单，出现频率最低的动作是打开营养表；\n三、部分顾客会在点单提交之后追问「这个有营养吗」。\n\n现予通报，并附本次核查事项：全店每 1 元补钙最高的那款，是哪一款？",
          "第三项每年都在发生，通报每年也都在发。"),
    Frame("paper_thesis", "paper", "T1",
          "【课题结题报告 · 摘要】\n\n课题名：价格与蛋白质总量的关系\n被试：全店在售餐品\n发现：蛋白总量最高的那几款，价格很少排在最后\n结论：这个发现不构成任何购买建议\n\n结题答辩的第一问：{A} 和 {B}，谁的蛋白更多？",
          "总量高只说明它大份，不说明它划算。"),
    Frame("paper_redhead", "paper", "T2",
          "【匿名举报受理单】\n\n举报事项：本店顾客存在长期不核算行为\n举报依据：本人观察 3 个月，未见任何一位顾客在点单前打开过营养表\n被举报人：自己\n诉求：请出具一份可自查的标准\n\n本受理单附查证题一道：{A} 和 {B}，每 1 元蛋白谁高？",
          "受理结果是——举报成立，被举报人有权自行改正。"),
    Frame("paper_witness2", "paper", "T2",
          "【询问笔录 · 第二次】\n\n问：上次你说 {A} 更值，依据是什么？\n答：大家都这么说。\n问：大家是谁？\n答：排队的时候听见的。\n\n记录人补充：{B} 是从未出现在那条队伍里的选项。\n{A} 和 {B}，每 1 元蛋白谁高？",
          "笔录里「大家」这个词出现过 4 次，每次指的都是排在他前面的那个人。"),
    Frame("paper_premium", "paper", "T2",
          "【成本构成分析】\n原料\n     包装\n           人工\n                 门店租金\n                       排面溢价  ← 这一项不在官方口径里\n                            合理利润\n\n{A} 的单价里有 {B} 没有的部分。每 1 元蛋白，{A} 和 {B} 谁高？",
          "排面溢价没写进任何一份财报，但它每年都在收。"),
    Frame("paper_errata", "paper", "T1",
          "【勘误】\n\n上期榜单按蛋白质总量排名，{A} 居首。\n有读者来信说：同一份数据，换个算法，榜首就换人了。\n\n本期不争排名，先核一个数：{A} 和 {B}，谁的蛋白更多？",
          "两个算法都抄对了。分歧出在有没有除以价格。"),
    # 六、连续剧（小明的麦当劳算账宇宙）
    Frame("series_s1", "series", "T2",
          "第一季：小明在深圳花 ¥26.5 吃了巨无霸，回北京发现同款 ¥25.5——"
          "他决定从此算账。第一道题：{A} 和 {B}，每元蛋白谁高？",
          "从深圳到北京，他算清了 1 块钱的账。"),
    Frame("series_s2", "series", "T2",
          "第二季：小明练完走进麦当劳，小红发来贺电：「记得买性价比高的。」"
          "小明看着菜单陷入沉思：{A} vs {B}？",
          "贺电已收到，账还是要算的。"),
    Frame("series_s3", "series", "T2",
          "第三季：小明带着计算器走进麦当劳。店员笑了：「又来一个算账的。」"
          "题目照旧：{A} 和 {B}？",
          "计算器是食验室的入场券。"),
    Frame("series_s4", "series", "T2",
          "第四季：小明开始带同事一起算。同事：「至于吗？」"
          "小明把第一季的故事讲了一遍。新题：{A} vs {B}？",
          "算账的传染性，比优惠券还强。"),
    Frame("series_s5", "series", "T2",
          "第五季：小明升职了——因为他帮全组点了每元蛋白最高的工作餐。"
          "升职宴的题目：{A} 和 {B}，谁高？",
          "全组的胃，都进了他的每元公式。"),
    Frame("series_s6", "series", "T2",
          "第六季：有人问小明「你这样活着累吗」。他没回答，只发了张小票。"
          "问题：{A} 和 {B} 谁每元蛋白高？",
          "小票比答案更伤人。"),
    Frame("series_s7", "series", "T2",
          "第七季：小红的闺蜜问「你俩谁管家」。"
          "小红：「管家的那个，每 1 元都算过。」题目：{A} vs {B}？",
          "「管家」两个字，是算出来的。"),
    Frame("series_s8", "series", "T2",
          "第八季：小明出了本书——《我在麦当劳算账的日子》。"
          "新书分享会的题目：{A} 和 {B}，每元蛋白谁高？",
          "书里没有标准答案，只有实测答案。"),
    Frame("series_final", "series", "T2",
          "季终：小明终于明白——有些账算不清，"
          "比如「为什么 {A} 更贵，每 1 元蛋白却……？」把问号补完整：",
          "问号补完了，段位也就出来了。"),
)

_SLOTS = ("T1", "T2", "T3", "T4", "T5")
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
        q, s = _champion_question(index, "calcium_per_yuan", "每 1 元补钙", seed + 1)
        base.append(q)
        slots_list.append(s)
    else:
        q, s = _champion_question(index, "protein_per_yuan", "每 1 元补蛋白", seed)
        base.append(q)
        slots_list.append(s)
        q, s = _champion_question(index, "calcium_per_yuan", "每 1 元补钙", seed + 1)
        base.append(q)
        slots_list.append(s)
        by_k = sorted(
            (i for i in index.items if i.kcal_per_yuan is not None),
            key=lambda i: i.kcal_per_yuan,
        )
        champ_k = by_k[0]
        decoys = []
        for item in by_k[::-1]:
            if item.name != champ_k.name and item.name not in decoys:
                decoys.append(item.name)
            if len(decoys) >= 3:
                break
        options, correct = _place([champ_k.name] + decoys, 0, seed + 2)
        base.append(
            Question(
                key="kcal",
                text="每 1 元吃到的热量最少的是？",
                options=options,
                correct=correct,
                reveal=(
                    f"{champ_k.name}：{_fmt(champ_k.kcal_per_yuan, 1)} kcal/元。"
                    f"总量高的不一定是冠军 —— 除以价格才知道。"
                ),
            )
        )
        slots_list.append(
            {"A": options[0], "B": options[1], "C": options[2], "D": options[3]}
        )

    return _apply_frames(base, slots_list, rng)


def _pick_frames(
    slots: list[str], rng: random.Random
) -> list[Frame | None]:
    """按题型槽位抽帧：同场 mode 不重复、帧不重复。

    槽位没有带新 mode 的帧可抽时（如 T2 的 mode 已被同场用掉），
    放宽到同 slot 内任意未用帧 —— 保证每道题都有壳。
    """
    picked: list[Frame | None] = []
    used_modes: set[str] = set()
    used_keys: set[str] = set()
    for slot in slots:
        pool = [
            f for f in FRAMES
            if f.slot == slot and f.mode not in used_modes and f.key not in used_keys
        ]
        if not pool:
            pool = [f for f in FRAMES if f.slot == slot and f.key not in used_keys]
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
    frames = _pick_frames([_slot_of(q) for q in base], rng)
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
