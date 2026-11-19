#!/usr/bin/env python3
"""deepseek.py 的单元测试"""

import json
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
