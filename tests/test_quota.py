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

    def _body_with_status(self, status):
        return {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64,
                               "current_weekly_remaining_percent": 23}],
            "base_resp": {"status_code": status},
        }

    def test_bool_false_status_code_raises(self):
        """False 是 JSON 布尔不是状态码，绝不能被当成 0（成功）"""
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(self._body_with_status(False))

    def test_bool_true_status_code_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(self._body_with_status(True))

    def test_fractional_float_status_code_raises(self):
        """0.4 截断成 0 等于放行畸形响应，必须当错误"""
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(self._body_with_status(0.5))

    def test_float_one_status_code_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(self._body_with_status(1.0))

    def test_negative_fractional_float_status_code_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(self._body_with_status(-0.5))

    def test_string_zero_status_code_still_accepted(self):
        """字符串 "0" 是合法成功码，别被改坏"""
        snapshot = quota.parse_remains(self._body_with_status("0"))
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_bool_percent_becomes_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": True,
                               "current_weekly_remaining_percent": False}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_bool_end_time_becomes_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 50,
                               "current_weekly_remaining_percent": 50,
                               "end_time": True,
                               "weekly_end_time": False}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_reset_at, 0)
        self.assertEqual(snapshot.weekly_reset_at, 0)


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


class TestLevelColor(unittest.TestCase):
    def test_warm_ramp_boundaries(self):
        self.assertEqual(quota.level_color(100, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(50, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(49, quota.WARM_RAMP), quota.YELLOW)
        self.assertEqual(quota.level_color(20, quota.WARM_RAMP), quota.YELLOW)
        self.assertEqual(quota.level_color(19, quota.WARM_RAMP), quota.RED)
        self.assertEqual(quota.level_color(0, quota.WARM_RAMP), quota.RED)

    def test_cool_ramp_boundaries(self):
        self.assertEqual(quota.level_color(100, quota.COOL_RAMP), quota.TEAL)
        self.assertEqual(quota.level_color(50, quota.COOL_RAMP), quota.TEAL)
        self.assertEqual(quota.level_color(49, quota.COOL_RAMP), quota.BLUE)
        self.assertEqual(quota.level_color(20, quota.COOL_RAMP), quota.BLUE)
        self.assertEqual(quota.level_color(19, quota.COOL_RAMP), quota.PURPLE)
        self.assertEqual(quota.level_color(0, quota.COOL_RAMP), quota.PURPLE)

    def test_clamps_out_of_range(self):
        self.assertEqual(quota.level_color(150, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(-10, quota.WARM_RAMP), quota.RED)


class TestRenderBar(unittest.TestCase):
    def test_returns_100_pixels(self):
        self.assertEqual(len(quota.render_bar(50, 50)), 100)

    def test_full_bars_fill_19_columns(self):
        grid = quota.render_bar(100, 100)
        for row in quota.ROW_TOP + quota.ROW_BOTTOM:
            for col in range(quota.BAR_WIDTH):
                self.assertNotEqual(grid[row * quota.COLS + col], quota.BLACK)

    def test_empty_bars_are_black(self):
        grid = quota.render_bar(0, 0)
        for row in quota.ROW_TOP + quota.ROW_BOTTOM:
            for col in range(quota.BAR_WIDTH):
                self.assertEqual(grid[row * quota.COLS + col], quota.BLACK)

    def test_half_fill_is_ten_columns(self):
        grid = quota.render_bar(50, 50)
        for row in quota.ROW_TOP + quota.ROW_BOTTOM:
            lit = sum(1 for col in range(quota.BAR_WIDTH)
                      if grid[row * quota.COLS + col] != quota.BLACK)
            self.assertEqual(lit, 10, "row %d 的填充列数不对" % row)

    def test_low_percent_rounding(self):
        # int(19*pct/100+0.5) 的四舍五入边界：1%/2% 不够一列，3% 起亮一列
        for pct, expected in ((1, 0), (2, 0), (3, 1)):
            grid = quota.render_bar(pct, pct)
            for row in quota.ROW_TOP + quota.ROW_BOTTOM:
                lit = sum(1 for col in range(quota.BAR_WIDTH)
                          if grid[row * quota.COLS + col] != quota.BLACK)
                self.assertEqual(lit, expected,
                                 "%d%% 在 row %d 的填充列数应为 %d" % (pct, row, expected))

    def test_last_column_always_black(self):
        grid = quota.render_bar(100, 100)
        for row in range(quota.ROWS):
            self.assertEqual(grid[row * quota.COLS + quota.COLS - 1], quota.BLACK)

    def test_separator_row_is_black(self):
        grid = quota.render_bar(100, 100)
        for col in range(quota.COLS):
            self.assertEqual(grid[2 * quota.COLS + col], quota.BLACK)

    def test_rows_do_not_overlap(self):
        self.assertEqual(set(quota.ROW_TOP) & set(quota.ROW_BOTTOM), set())
        self.assertNotIn(2, quota.ROW_TOP)
        self.assertNotIn(2, quota.ROW_BOTTOM)

    def test_high_percent_uses_warm_and_cool_colors(self):
        grid = quota.render_bar(74, 24)
        self.assertEqual(grid[quota.ROW_TOP[0] * quota.COLS], quota.GREEN)
        self.assertEqual(grid[quota.ROW_BOTTOM[0] * quota.COLS], quota.BLUE)

    def test_low_percent_uses_red_and_purple(self):
        grid = quota.render_bar(12, 8)
        self.assertEqual(grid[quota.ROW_TOP[0] * quota.COLS], quota.RED)
        self.assertEqual(grid[quota.ROW_BOTTOM[0] * quota.COLS], quota.PURPLE)

    def test_unfilled_part_is_black(self):
        grid = quota.render_bar(74, 24)
        # 5h 74% → int(19*0.74+0.5) = 14 列填充，第 15 列起为黑
        row = quota.ROW_TOP[0]
        self.assertNotEqual(grid[row * quota.COLS + 13], quota.BLACK)
        self.assertEqual(grid[row * quota.COLS + 14], quota.BLACK)


class FakeResponse:
    """模拟 urllib 的 HTTP 响应对象"""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchQuota(unittest.TestCase):
    def setUp(self):
        self._original_urlopen = quota.urllib.request.urlopen

    def tearDown(self):
        quota.urllib.request.urlopen = self._original_urlopen

    def test_requires_api_key(self):
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("")

    def test_network_failure_becomes_quota_error(self):
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy", api_base="http://127.0.0.1:9", timeout=1)

    def test_successful_fetch(self):
        payload = json.dumps({
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 64,
                "current_weekly_remaining_percent": 23,
            }],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }).encode()

        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            return FakeResponse(payload)

        quota.urllib.request.urlopen = fake_urlopen
        snapshot = quota.fetch_quota("dummy-key")

        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)
        self.assertEqual(captured["url"],
                         "https://api.minimaxi.com/v1/token_plan/remains")
        self.assertEqual(captured["auth"], "Bearer dummy-key")

    def test_trailing_slash_in_api_base_is_tolerated(self):
        payload = json.dumps({
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 10,
                               "current_weekly_remaining_percent": 20}],
            "base_resp": {"status_code": 0},
        }).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse(payload)

        quota.urllib.request.urlopen = fake_urlopen
        quota.fetch_quota("dummy-key", api_base="https://api.minimaxi.com/")
        self.assertEqual(captured["url"],
                         "https://api.minimaxi.com/v1/token_plan/remains")

    def test_invalid_json_becomes_quota_error(self):
        quota.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(b"not json")
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy-key")

    def test_business_error_becomes_quota_error(self):
        payload = json.dumps({
            "base_resp": {"status_code": 2049, "status_msg": "invalid api key"}
        }).encode()
        quota.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(payload)
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy-key")

    def test_malformed_api_base_becomes_quota_error(self):
        """api_base 配错时只能抛 QuotaError，不能把 ValueError/AttributeError 漏出去"""
        for bad_base in ("", "not a url", "://x", 123):
            with self.subTest(api_base=bad_base):
                with self.assertRaises(quota.QuotaError):
                    quota.fetch_quota("dummy-key", api_base=bad_base)


if __name__ == "__main__":
    unittest.main()
