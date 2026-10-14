"""order.py + 点餐单卡测试。

边界核心：**点餐链路到「实时计价」为止都是只读**；
计价失败退回菜单标价合计必须如实标注，绝不冒充接口价。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from card import STYLES, render_order_card, render_quiz_card  # noqa: E402
from fuel_index import build_index  # noqa: E402
from order import (  # noqa: E402
    OrderQuote,
    format_receipt,
    order_items_payload,
    parse_cancel_response,
    parse_create_response,
    parse_quote,
    resolve_picks,
    summarize_order,
)
from test_fuel_index import REAL_MATCHED, REAL_NUTRITION, menu  # noqa: E402

# 真实 calculate-price 响应结构（2026-10-13 门店 1950564 实测截取，价格单位分）
REAL_QUOTE = {
    "productOriginalPrice": 3500,
    "productPrice": 3500,
    "originalPrice": 3500,
    "discount": 0,
    "price": 3500,
    "productList": [
        {
            "productCode": "521156",
            "productName": "那么大鸡排（椒盐风味）",
            "quantity": 1,
            "originalSubtotal": 1400,
            "subtotal": 1400,
        },
        {
            "productCode": "3755",
            "productName": "纯牛奶",
            "quantity": 2,
            "originalSubtotal": 2100,
            "subtotal": 2100,
        },
    ],
}


def build():
    return build_index(menu(REAL_MATCHED), REAL_NUTRITION)


class TestResolvePicks(unittest.TestCase):
    def setUp(self):
        self.idx = build()

    def test_exact_name(self):
        picks = resolve_picks(self.idx, "那么大鸡排（椒盐风味）")
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0][0].name, "那么大鸡排（椒盐风味）")
        self.assertEqual(picks[0][1], 1)

    def test_fuzzy_substring(self):
        picks = resolve_picks(self.idx, "鸡排")
        self.assertEqual(picks[0][0].name, "那么大鸡排（椒盐风味）")

    def test_quantity_suffix(self):
        picks = resolve_picks(self.idx, "鸡排x2")
        self.assertEqual(picks[0][1], 2)

    def test_multiple_items_and_merge(self):
        picks = resolve_picks(self.idx, "鸡排、纯牛奶, 鸡排x2")
        by_name = {i.name: q for i, q in picks}
        self.assertEqual(by_name["那么大鸡排（椒盐风味）"], 3)
        self.assertEqual(by_name["纯牛奶(盒装)"], 1)

    def test_missing_item_raises(self):
        with self.assertRaises(ValueError):
            resolve_picks(self.idx, "不存在的汉堡")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            resolve_picks(self.idx, "")

    def test_item_carries_product_code(self):
        """点餐链路必须拿得到 productCode —— 没它算不了价。"""
        picks = resolve_picks(self.idx, "鸡排")
        self.assertTrue(picks[0][0].code)

    def test_name_only_raises(self):
        """「x2」后面没写名字 —— 不许猜。"""
        with self.assertRaises(ValueError):
            resolve_picks(self.idx, "x2")


class TestParseQuote(unittest.TestCase):
    def test_cents_to_yuan(self):
        picks = resolve_picks(build(), "鸡排, 牛奶")
        quote = parse_quote(REAL_QUOTE, picks)
        self.assertEqual(quote.total, 35.0)  # 3500 分
        self.assertEqual(quote.source, "calculate-price")
        self.assertEqual(quote.lines[0].unit_price, 14.0)  # 1400 分 / 1
        self.assertEqual(quote.lines[1].unit_price, 10.5)  # 2100 分 / 2

    def test_none_response_falls_back_to_menu_price(self):
        """接口失败退回菜单标价合计 —— 来路必须标注，不冒充。"""
        picks = resolve_picks(build(), "鸡排, 牛奶")
        quote = parse_quote(None, picks)
        self.assertEqual(quote.source, "menu-price")
        self.assertEqual(quote.total, 14.0 + 10.5)
        self.assertIn("菜单标价", quote.note)

    def test_malformed_response_falls_back(self):
        picks = resolve_picks(build(), "鸡排")
        quote = parse_quote({"error": "x"}, picks)
        self.assertEqual(quote.source, "menu-price")


class TestSummarize(unittest.TestCase):
    def test_fuel_totals(self):
        idx = build()
        picks = resolve_picks(idx, "鸡排, 牛奶x2")  # 与 REAL_QUOTE 对应：鸡排1+牛奶2
        quote = parse_quote(REAL_QUOTE, picks)
        s = summarize_order(idx, picks, quote)
        self.assertEqual(s["protein"], 38.0)  # 24g + 7g × 2
        self.assertEqual(s["protein_per_yuan"], round(38 / 35.0, 2))
        self.assertEqual(s["kcal"], 385 + 129 * 2)

    def test_no_fake_fields_when_missing(self):
        idx = build()
        picks = resolve_picks(idx, "鸡排")
        quote = parse_quote(None, picks)
        s = summarize_order(idx, picks, quote)
        self.assertIn("total", s)
        self.assertTrue(s.get("protein") or "protein" not in s)


class TestOrderCard(unittest.TestCase):
    def setUp(self):
        self.idx = build()
        self.picks = resolve_picks(self.idx, "鸡排, 牛奶")
        self.summary = summarize_order(
            self.idx, self.picks, parse_quote(REAL_QUOTE, self.picks)
        )

    def test_produces_complete_html(self):
        html = render_order_card(self.idx, self.summary)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)

    def test_total_is_headline(self):
        """大字 = 应付合计 —— 点餐时最关心的数。"""
        html = render_order_card(self.idx, self.summary)
        self.assertIn("¥35.0", html)
        self.assertIn("点餐单", html)

    def test_fuel_signature(self):
        html = render_order_card(self.idx, self.summary)
        self.assertIn("这一单", html)
        self.assertIn("g 蛋白", html)

    def test_price_source_labeled(self):
        """接口价与菜单标价必须可区分 —— 来路如实标注。"""
        live = render_order_card(self.idx, self.summary)
        self.assertIn("实时计价", live)
        self.assertIn("不产生订单", live)  # 边界声明：点餐单不下单

        fallback = summarize_order(
            self.idx, self.picks, parse_quote(None, self.picks)
        )
        html = render_order_card(self.idx, fallback)
        self.assertIn("按菜单标价合计", html)

    def test_coverage_disclosure_present(self):
        html = render_order_card(self.idx, self.summary)
        self.assertIn("款在售", html)

    def test_store_name_escaped(self):
        html = render_order_card(
            self.idx, self.summary, store_name="<script>x</script>"
        )
        self.assertNotIn("<script>x</script>", html)

    def test_footer_always_carries_repo_link(self):
        """落款恒定带开源链接（没传 project_url 兜底 PROJECT_URL）。"""
        from card import PROJECT_URL

        without = render_order_card(self.idx, self.summary)
        self.assertIn(PROJECT_URL, without)
        with_url = render_order_card(
            self.idx, self.summary, project_url="https://example.com/x"
        )
        self.assertIn("https://example.com/x", with_url)

    def test_all_styles_render(self):
        for style in STYLES:
            html = render_order_card(self.idx, self.summary, style=style)
            self.assertIn(f't-{style}"', html)
            self.assertIn("¥35.0", html)

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            render_order_card(self.idx, self.summary, style="赛博")

    def test_no_create_order_call(self):
        """点餐单卡绝不出现「已下单」之类的承诺 —— 它不产生订单。"""
        html = render_order_card(self.idx, self.summary)
        self.assertNotIn("已下单", html)
        self.assertNotIn("订单号", html)


# 真实 create-order 响应（2026-10-13 实测：下单后立即取消，无资金损失）
REAL_CREATE = {
    "orderId": "1030431570000661829311883441",
    "payId": "111030252029351354368",
    "payH5Url": "https://m.mcd.cn/mcp/scanToPay?orderId=1030431570000661829311883441",
    "orderDetail": {
        "orderId": "1030431570000661829311883441",
        "orderStatus": "待支付",
        "storeName": "麦当劳北京建外SOHO(A座)餐厅",
        "orderProductList": [
            {
                "productName": "那么大鸡排（椒盐风味）",
                "quantity": 1,
                "price": "14",
            }
        ],
        "totalAmount": "14",
        "realTotalAmount": "14",
        "expirePayTime": "2026-10-13 23:08:44",
        "takeWay": "外带",
    },
}


class TestCreateOrder(unittest.TestCase):
    """写操作的解析层 —— 真实响应结构实测fixture。"""

    def test_parse_receipt(self):
        r = parse_create_response(REAL_CREATE)
        self.assertEqual(r.order_id, "1030431570000661829311883441")
        self.assertTrue(r.pay_url.startswith("https://m.mcd.cn/"))
        self.assertEqual(r.status, "待支付")
        self.assertEqual(r.total, 14.0)
        self.assertEqual(r.expire_pay_time, "2026-10-13 23:08:44")
        self.assertIn("那么大鸡排", r.lines[0])

    def test_missing_order_id_is_fatal(self):
        """解析不到订单号 = 状态未知，必须报错 —— 一笔没有订单号的真实
        订单，用户连取消都做不到。"""
        with self.assertRaises(ValueError):
            parse_create_response({"payH5Url": "https://x"})

    def test_receipt_has_three_essentials(self):
        """回传三要素：支付链接 / 订单号 / 取消方式 —— 一个不能少。"""
        text = format_receipt(parse_create_response(REAL_CREATE))
        self.assertIn("https://m.mcd.cn/", text)  # 支付链接
        self.assertIn("订单号：", text)  # 订单号
        self.assertIn("取消", text)  # 取消方式
        self.assertIn("23:08:44", text)  # 支付时限必须带上

    def test_cancel_response(self):
        self.assertTrue(parse_cancel_response({"cancelResult": True}))
        self.assertFalse(parse_cancel_response({"cancelResult": False}))
        self.assertFalse(parse_cancel_response(None))

    def test_items_payload_uses_code(self):
        idx = build()
        picks = resolve_picks(idx, "鸡排x2")
        payload = order_items_payload(picks)
        self.assertEqual(payload, [{"productCode": picks[0][0].code, "quantity": 2}])


class TestSecurityHardening(unittest.TestCase):
    """安全加固回归：XSS、钓鱼链接、脏数据不崩。"""

    def setUp(self):
        self.idx = build()
        self.picks = resolve_picks(self.idx, "鸡排, 牛奶")
        self.summary = summarize_order(
            self.idx, self.picks, parse_quote(REAL_QUOTE, self.picks)
        )

    def test_javascript_url_blocked_in_all_cards(self):
        """project_url 走 javascript: 协议 —— 必须整个丢弃。

        新契约：丢弃后落款**回落兜底链接**（用户要所有页面都带具体链接），
        所以断言改为「邪恶 URL 不出现 + href 是安全的 PROJECT_URL」。
        """
        from card import PROJECT_URL

        evil = "javascript:alert(document.cookie)"
        for render in (
            lambda: render_order_card(self.idx, self.summary, project_url=evil),
            lambda: render_quiz_card(self.idx, (0, 0, 0), project_url=evil),
        ):
            html = render()
            self.assertNotIn("javascript:", html)
            self.assertIn(f'<a href="{PROJECT_URL}"', html)

    def test_pay_url_official_domain_trusted(self):
        r = parse_create_response(REAL_CREATE)
        self.assertTrue(r.pay_url_trusted)
        self.assertNotIn("钓鱼", format_receipt(r))

    def test_pay_url_phishing_domain_warned(self):
        """MCP 被劫持回钓鱼域名 —— 链接保留但必须显著警告。"""
        evil = dict(REAL_CREATE)
        evil["payH5Url"] = "https://evil.example.com/pay?orderId=x"
        receipt = parse_create_response(evil)
        self.assertFalse(receipt.pay_url_trusted)
        text = format_receipt(receipt)
        self.assertIn("疑似钓鱼", text)
        self.assertIn("请勿在该页面输入任何账号信息", text)

    def test_quote_dirty_data_never_crashes(self):
        """quantity=0、非数字字段 —— 修掉除零崩溃，脏行丢弃退回标价。"""
        dirty = {
            "price": "3500",
            "productList": [
                {"productCode": "1", "productName": "A", "quantity": 0, "subtotal": 100},
                {"productCode": "2", "productName": "B", "quantity": "abc", "subtotal": 100},
                {"productCode": "3", "productName": "C", "quantity": 1, "subtotal": "不是数字"},
                {"productCode": "4", "productName": "D", "quantity": 2, "subtotal": 3500},
            ],
        }
        quote = parse_quote(dirty, self.picks)
        # 只有 D 行可信；A/B/C 全部丢弃
        self.assertEqual(len(quote.lines), 1)
        self.assertEqual(quote.lines[0].name, "D")
        self.assertEqual(quote.total, 35.0)

    def test_quote_all_dirty_falls_back_to_menu_price(self):
        dirty = {"price": "1", "productList": [{"quantity": 0, "subtotal": 1}]}
        quote = parse_quote(dirty, self.picks)
        self.assertEqual(quote.source, "menu-price")


if __name__ == "__main__":
    unittest.main()
