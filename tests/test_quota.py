#!/usr/bin/env python3
"""quota.py 的单元测试"""

import json
import os
import sys
import unittest

# 让测试可以从任意 cwd 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quota  # noqa: E402


class TestParseRemains(unittest.TestCase):
    def test_normal_response(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 64,
                "current_weekly_remaining_percent": 23,
                "end_time": 1795073698120,
                "weekly_end_time": 1795070409914,
            }],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)
        self.assertEqual(snapshot.interval_reset_at, 1795073698120)
        self.assertEqual(snapshot.weekly_reset_at, 1795070409914)

    def test_non_zero_status_code_raises(self):
        body = {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_missing_base_resp_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains({"model_remains": []})

    def test_empty_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}, "model_remains": []}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_missing_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_body_not_dict_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(["not", "a", "dict"])

    def test_prefers_general_entry(self):
        body = {
            "model_remains": [
                {"model_name": "MiniMax-M3", "current_interval_remaining_percent": 10,
                 "current_weekly_remaining_percent": 20},
                {"model_name": "general", "current_interval_remaining_percent": 64,
                 "current_weekly_remaining_percent": 23},
            ],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_falls_back_to_first_entry(self):
        body = {
            "model_remains": [
                {"model_name": "MiniMax-M3", "current_interval_remaining_percent": 11,
                 "current_weekly_remaining_percent": 22},
            ],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 11)
        self.assertEqual(snapshot.weekly_pct, 22)

    def test_clamps_out_of_range_percent(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 150,
                "current_weekly_remaining_percent": -5,
            }],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 100)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_non_numeric_percent_becomes_zero(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": "n/a",
                "current_weekly_remaining_percent": None,
            }],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_missing_reset_time_defaults_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 50,
                               "current_weekly_remaining_percent": 50}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_reset_at, 0)
        self.assertEqual(snapshot.weekly_reset_at, 0)


class TestDiffersFrom(unittest.TestCase):
    def test_none_always_differs(self):
        self.assertTrue(quota.QuotaSnapshot(50, 50).differs_from(None))

    def test_same_percent_ignores_reset_time(self):
        a = quota.QuotaSnapshot(50, 20, 111, 222)
        b = quota.QuotaSnapshot(50, 20, 999, 888)
        self.assertFalse(a.differs_from(b))

    def test_changed_percent_differs(self):
        a = quota.QuotaSnapshot(50, 20)
        b = quota.QuotaSnapshot(49, 20)
        self.assertTrue(a.differs_from(b))

    def test_changed_weekly_differs(self):
        a = quota.QuotaSnapshot(50, 20)
        b = quota.QuotaSnapshot(50, 21)
        self.assertTrue(a.differs_from(b))


class TestParseRemainsMalformed(unittest.TestCase):
    """畸形输入的容错行为"""

    def test_mixed_entries_falls_back_to_first_dict(self):
        body = {
            "model_remains": ["garbage", {"model_name": "MiniMax-M3",
                                           "current_interval_remaining_percent": 33,
                                           "current_weekly_remaining_percent": 44}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 33)
        self.assertEqual(snapshot.weekly_pct, 44)

    def test_non_dict_first_still_prefers_general(self):
        body = {
            "model_remains": ["garbage", None,
                              {"model_name": "general",
                               "current_interval_remaining_percent": 64,
                               "current_weekly_remaining_percent": 23}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_numeric_string_percent(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": "64",
                               "current_weekly_remaining_percent": "23"}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_float_string_percent(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": "64.9",
                               "current_weekly_remaining_percent": "23.4"}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_string_status_code_zero_accepted(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64,
                               "current_weekly_remaining_percent": 23}],
            "base_resp": {"status_code": "0", "status_msg": "success"},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_missing_status_code_raises(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64}],
            "base_resp": {"status_msg": "success"},
        }
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_infinite_percent_is_clamped(self):
        """inf 走 int() 会抛 OverflowError，必须被兜住并规整进 0..100"""
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": float("inf"),
                               "current_weekly_remaining_percent": float("-inf")}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertGreaterEqual(snapshot.interval_pct, 0)
        self.assertLessEqual(snapshot.interval_pct, 100)
        self.assertGreaterEqual(snapshot.weekly_pct, 0)
        self.assertLessEqual(snapshot.weekly_pct, 100)

    def test_nan_percent_is_clamped(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": float("nan"),
                               "current_weekly_remaining_percent": float("nan")}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_base_resp_list_raises(self):
        body = {"model_remains": [], "base_resp": ["nope"]}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)


class TestParseRemainsContract(unittest.TestCase):
    """契约：parse_remains 只允许抛 QuotaError，任何其它异常都不许逃出来"""

    MALFORMED_BODIES = [
        None,
        [],
        "string",
        42,
        {},
        {"base_resp": None},
        {"base_resp": []},
        {"base_resp": "ok"},
        {"base_resp": {}},
        {"base_resp": {"status_code": None}},
        {"base_resp": {"status_code": "not a number"}},
        {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}},
        {"base_resp": {"status_code": 0}},
        {"base_resp": {"status_code": 0}, "model_remains": None},
        {"base_resp": {"status_code": 0}, "model_remains": "nope"},
        {"base_resp": {"status_code": 0}, "model_remains": []},
        {"base_resp": {"status_code": 0}, "model_remains": ["garbage", 1, None]},
        {"base_resp": {"status_code": 0}, "model_remains": [
            {"model_name": "general",
             "current_interval_remaining_percent": float("inf"),
             "current_weekly_remaining_percent": float("-inf"),
             "end_time": float("nan"),
             "weekly_end_time": None}]},
        {"base_resp": {"status_code": 0}, "model_remains": [
            {"model_name": "general",
             "current_interval_remaining_percent": {"nested": "dict"},
             "current_weekly_remaining_percent": ["list"]}]},
    ]

    def test_only_quota_error_escapes(self):
        for body in self.MALFORMED_BODIES:
            with self.subTest(body=body):
                try:
                    result = quota.parse_remains(body)
                except quota.QuotaError:
                    continue
                except Exception as exc:  # noqa: BLE001 - 契约测试要看到所有异常类型
                    self.fail("parse_remains 抛出了非 QuotaError: %r (body=%r)"
                              % (exc, body))
                # 没抛异常也是一种合法结果，但百分比必须是规整过的整数
                self.assertIsInstance(result, quota.QuotaSnapshot)
                self.assertIsInstance(result.interval_pct, int)
                self.assertIsInstance(result.weekly_pct, int)
                self.assertGreaterEqual(result.interval_pct, 0)
                self.assertLessEqual(result.interval_pct, 100)
                self.assertGreaterEqual(result.weekly_pct, 0)
                self.assertLessEqual(result.weekly_pct, 100)

    def test_infinity_literal_from_json_parsed_body(self):
        """json.loads 默认接受 Infinity / NaN 字面量，走真实解析路径"""
        body = json.loads(
            '{"model_remains": [{"model_name": "general",'
            ' "current_interval_remaining_percent": Infinity,'
            ' "current_weekly_remaining_percent": NaN}],'
            ' "base_resp": {"status_code": 0}}')
        snapshot = quota.parse_remains(body)
        self.assertGreaterEqual(snapshot.interval_pct, 0)
        self.assertLessEqual(snapshot.interval_pct, 100)
        self.assertGreaterEqual(snapshot.weekly_pct, 0)
        self.assertLessEqual(snapshot.weekly_pct, 100)


if __name__ == "__main__":
    unittest.main()
