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


if __name__ == "__main__":
    unittest.main()
