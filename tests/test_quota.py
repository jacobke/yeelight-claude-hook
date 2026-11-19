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


if __name__ == "__main__":
    unittest.main()
