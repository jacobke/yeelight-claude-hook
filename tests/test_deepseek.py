#!/usr/bin/env python3
"""deepseek.py 的单元测试"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deepseek  # noqa: E402


def balance_body(total, currency="CNY"):
    return {
        "is_available": True,
        "balance_infos": [{
            "currency": currency,
            "total_balance": str(total),
            "granted_balance": "0",
            "topped_up_balance": str(total),
        }],
    }


class TestParseBalance(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("58.44")), 58.44)

    def test_integer_string(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("100")), 100.0)

    def test_prefers_cny(self):
        body = {"is_available": True, "balance_infos": [
            {"currency": "USD", "total_balance": "10.00"},
            {"currency": "CNY", "total_balance": "58.44"},
        ]}
        self.assertAlmostEqual(deepseek.parse_balance(body), 58.44)

    def test_falls_back_to_first_entry(self):
        body = {"is_available": True, "balance_infos": [
            {"currency": "USD", "total_balance": "10.00"},
        ]}
        self.assertAlmostEqual(deepseek.parse_balance(body), 10.0)

    def test_not_a_dict(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(["nope"])

    def test_missing_balance_infos(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance({"is_available": True})

    def test_empty_balance_infos(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance({"balance_infos": []})

    def test_non_numeric_balance(self):
        body = {"balance_infos": [{"currency": "CNY", "total_balance": "n/a"}]}
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(body)

    def test_missing_total_balance(self):
        body = {"balance_infos": [{"currency": "CNY"}]}
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(body)

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("-3.5")), 0.0)

    def test_huge_value_clamped(self):
        self.assertAlmostEqual(
            deepseek.parse_balance(balance_body("999999999999")),
            deepseek.MAX_BALANCE)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchBalance(unittest.TestCase):
    def setUp(self):
        self._original = deepseek.urllib.request.urlopen

    def tearDown(self):
        deepseek.urllib.request.urlopen = self._original

    def test_requires_api_key(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("")

    def test_successful_fetch(self):
        payload = json.dumps(balance_body("58.44")).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            return FakeResponse(payload)

        deepseek.urllib.request.urlopen = fake_urlopen
        value = deepseek.fetch_balance("dummy-key")
        self.assertAlmostEqual(value, 58.44)
        self.assertEqual(captured["url"], "https://api.deepseek.com/user/balance")
        self.assertEqual(captured["auth"], "Bearer dummy-key")

    def test_trailing_slash_tolerated(self):
        payload = json.dumps(balance_body("1.0")).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse(payload)

        deepseek.urllib.request.urlopen = fake_urlopen
        deepseek.fetch_balance("k", api_base="https://api.deepseek.com/")
        self.assertEqual(captured["url"], "https://api.deepseek.com/user/balance")

    def test_invalid_json(self):
        deepseek.urllib.request.urlopen = lambda r, timeout=None: FakeResponse(b"nope")
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k")

    def test_bad_api_base(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k", api_base="not a url")

    def test_network_failure(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k", api_base="http://127.0.0.1:9", timeout=1)


class TestFormatAmount(unittest.TestCase):
    def test_small_with_decimal(self):
        self.assertEqual(deepseek.format_amount(3.24, allow_decimal=True), "3.2")
        self.assertEqual(deepseek.format_amount(0.04, allow_decimal=True), "0.0")
        self.assertEqual(deepseek.format_amount(9.99, allow_decimal=True), "10.0")

    def test_small_without_decimal(self):
        self.assertEqual(deepseek.format_amount(3.6, allow_decimal=False), "4")
        self.assertEqual(deepseek.format_amount(0.4, allow_decimal=False), "0")

    def test_large_always_integer(self):
        self.assertEqual(deepseek.format_amount(12.5, allow_decimal=True), "13")
        self.assertEqual(deepseek.format_amount(123.4, allow_decimal=True), "123")
        self.assertEqual(deepseek.format_amount(0.0, allow_decimal=True), "0.0")

    def test_negative_treated_as_zero(self):
        self.assertEqual(deepseek.format_amount(-5, allow_decimal=False), "0")


class TestAbbreviate(unittest.TestCase):
    def test_below_ten_thousand(self):
        self.assertEqual(deepseek.abbreviate(0), "0")
        self.assertEqual(deepseek.abbreviate(9999), "9999")

    def test_thousands_no_decimal(self):
        self.assertEqual(deepseek.abbreviate(10000), "10K")
        self.assertEqual(deepseek.abbreviate(12345), "12K")
        self.assertEqual(deepseek.abbreviate(999999), "1000K")

    def test_millions_one_decimal(self):
        self.assertEqual(deepseek.abbreviate(1000000), "1.0M")
        self.assertEqual(deepseek.abbreviate(1234567), "1.2M")


class TestTextWidth(unittest.TestCase):
    def test_widths(self):
        self.assertEqual(deepseek.text_width("3.2"), 9)
        self.assertEqual(deepseek.text_width("58"), 7)
        self.assertEqual(deepseek.text_width("123"), 11)
        self.assertEqual(deepseek.text_width("1234"), 15)
        self.assertEqual(deepseek.text_width("12345"), 19)
        self.assertEqual(deepseek.text_width("12K"), 11)
        self.assertEqual(deepseek.text_width("1.2M"), 13)


class TestComposePage(unittest.TestCase):
    def test_typical_side_by_side(self):
        mode, texts = deepseek.compose_page(3.24, 58.44)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3.2", "58"])

    def test_three_digit_spend_two_digit_balance_side(self):
        mode, texts = deepseek.compose_page(123.0, 58.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["123", "58"])

    def test_three_digit_both_alternates(self):
        mode, texts = deepseek.compose_page(123.0, 456.0)
        self.assertEqual(mode, "alternate")
        self.assertEqual(texts, ["123", "456"])

    def test_five_digit_balance_abbreviated_side(self):
        mode, texts = deepseek.compose_page(3.0, 12345.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3", "12K"])

    def test_spend_decimal_dropped_before_alternating(self):
        mode, texts = deepseek.compose_page(1.2, 12345.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["1", "12K"])

    def test_four_digit_balance_side(self):
        mode, texts = deepseek.compose_page(3.0, 1234.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3", "1234"])


class TestComposeWidthInvariant(unittest.TestCase):
    def test_every_mode_fits(self):
        cases = [
            (0, 0), (3.24, 58.44), (12.5, 99.9), (123, 456),
            (3, 1234), (3, 12345), (3, 1234567), (1.2, 12345),
            (999999, 9999999), (0.01, 0.01),
        ]
        for spend, balance in cases:
            mode, texts = deepseek.compose_page(spend, balance)
            for text in texts:
                self.assertLessEqual(
                    deepseek.text_width(text), deepseek.USABLE_WIDTH,
                    "『%s』超宽 (spend=%s balance=%s)" % (text, spend, balance))
            if mode == "side":
                total = (deepseek.text_width(texts[0]) + 1
                         + deepseek.text_width(texts[1]))
                self.assertLessEqual(
                    total, deepseek.USABLE_WIDTH,
                    "并排超宽 spend=%s balance=%s" % (spend, balance))


class TestRenderPage(unittest.TestCase):
    def test_returns_100_pixels(self):
        self.assertEqual(len(deepseek.render_page("side", ["3.2", "58"])), 100)

    def test_last_column_always_black(self):
        for mode, texts, index in (
            ("side", ["3.2", "58"], 0),
            ("alternate", ["123", "456"], 0),
            ("alternate", ["123", "456"], 1),
        ):
            grid = deepseek.render_page(mode, texts, index)
            for row in range(deepseek.ROWS):
                self.assertEqual(
                    grid[row * deepseek.COLS + deepseek.COLS - 1],
                    deepseek.BLACK, "%s/%s 的 col19 应为黑" % (mode, index))

    def test_side_uses_both_colors(self):
        grid = deepseek.render_page("side", ["3.2", "58"])
        colors = {px for px in grid if px != deepseek.BLACK}
        self.assertEqual(colors, {deepseek.SPEND_COLOR, deepseek.BALANCE_COLOR})

    def test_alternate_index_selects_color(self):
        spend_grid = deepseek.render_page("alternate", ["123", "456"], 0)
        balance_grid = deepseek.render_page("alternate", ["123", "456"], 1)
        spend_colors = {px for px in spend_grid if px != deepseek.BLACK}
        balance_colors = {px for px in balance_grid if px != deepseek.BLACK}
        self.assertEqual(spend_colors, {deepseek.SPEND_COLOR})
        self.assertEqual(balance_colors, {deepseek.BALANCE_COLOR})

    def test_empty_page_is_black(self):
        grid = deepseek.render_page("side", ["", ""])
        self.assertEqual(set(grid), {deepseek.BLACK})

    def test_glyphs_do_not_overflow(self):
        # 最宽的合法组合也不能画到 col19 之外
        grid = deepseek.render_page("side", ["123", "58"])
        for row in range(deepseek.ROWS):
            self.assertEqual(grid[row * deepseek.COLS + 19], deepseek.BLACK)


class TestPaletteDisjointFromMiniMax(unittest.TestCase):
    """DeepSeek 页的配色不得与 MiniMax 页的任何颜色重合"""

    def test_no_overlap_with_minimax_palette(self):
        import quota
        minimax_colors = {
            quota.GREEN, quota.YELLOW, quota.RED, quota.TEAL, quota.BLUE,
            quota.PURPLE, quota.BLACK, quota.RESET_TRACK,
        }
        for _, color in quota.RESET_STOPS:
            minimax_colors.add(color)

        deepseek_colors = {deepseek.SPEND_COLOR, deepseek.BALANCE_COLOR}
        overlap = deepseek_colors & minimax_colors
        self.assertEqual(overlap, set(),
                         "DeepSeek 配色与 MiniMax 重合: %s" % (overlap,))

    def test_rendered_pixels_never_match_minimax(self):
        import quota
        minimax_colors = {quota.GREEN, quota.YELLOW, quota.RED, quota.TEAL,
                          quota.BLUE, quota.PURPLE, quota.RESET_TRACK}
        for _, color in quota.RESET_STOPS:
            minimax_colors.add(color)

        grids = [
            deepseek.render_page("side", ["3.2", "58"]),
            deepseek.render_page("alternate", ["123", "456"], 0),
            deepseek.render_page("alternate", ["123", "456"], 1),
        ]
        for grid in grids:
            for px in grid:
                if px == deepseek.BLACK:
                    continue
                self.assertNotIn(px, minimax_colors)


class TestSpendTracker(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "quota_state.json")

    def test_first_run_sets_baseline(self):
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(61.73, "2026-11-19"), 0.0)
        self.assertAlmostEqual(t.day_start, 61.73)

    def test_spend_accumulates_same_day(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        self.assertAlmostEqual(t.update(60.00, "2026-11-19"), 1.73)
        self.assertAlmostEqual(t.update(58.44, "2026-11-19"), 3.29)

    def test_top_up_adjusts_baseline(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        t.update(58.44, "2026-11-19")          # 花了 3.29
        self.assertAlmostEqual(t.update(108.44, "2026-11-19"), 3.29,
                               msg="充值 50 不应抵消已花的钱")
        self.assertAlmostEqual(t.update(100.00, "2026-11-19"), 11.73,
                               msg="充值后继续消费应继续累加")

    def test_new_day_resets(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        t.update(58.44, "2026-11-19")
        self.assertAlmostEqual(t.update(58.44, "2026-11-20"), 0.0)
        self.assertAlmostEqual(t.day_start, 58.44)

    def test_state_persists_across_instances(self):
        t1 = deepseek.SpendTracker(self.path)
        t1.update(61.73, "2026-11-19")
        t1.update(58.44, "2026-11-19")

        t2 = deepseek.SpendTracker(self.path)
        t2.load()
        self.assertAlmostEqual(t2.day_start, 61.73)
        self.assertAlmostEqual(t2.update(57.00, "2026-11-19"), 4.73)

    def test_corrupt_state_treated_as_fresh(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(50.0, "2026-11-19"), 0.0)
        self.assertAlmostEqual(t.day_start, 50.0)

    def test_non_dict_state_treated_as_fresh(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(50.0, "2026-11-19"), 0.0)

    def test_save_writes_readable_json(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["date"], "2026-11-19")
        self.assertAlmostEqual(data["day_start"], 61.73)

    def test_spend_never_negative(self):
        t = deepseek.SpendTracker(self.path)
        t.update(50.0, "2026-11-19")
        # 余额上涨但没归零基线（例如浮点抖动）时不应出现负数
        self.assertGreaterEqual(t.spent(), 0.0)


if __name__ == "__main__":
    unittest.main()
