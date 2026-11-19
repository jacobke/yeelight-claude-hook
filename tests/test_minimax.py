#!/usr/bin/env python3
"""minimax.py 的单元测试"""

import json
import os
import sys
import unittest

# 让测试可以从任意 cwd 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import minimax  # noqa: E402


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
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)
        self.assertEqual(snapshot.interval_reset_at, 1795073698120)
        self.assertEqual(snapshot.weekly_reset_at, 1795070409914)

    def test_non_zero_status_code_raises(self):
        body = {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(body)

    def test_missing_base_resp_raises(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains({"model_remains": []})

    def test_empty_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}, "model_remains": []}
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(body)

    def test_missing_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}}
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(body)

    def test_body_not_dict_raises(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(["not", "a", "dict"])

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
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_missing_reset_time_defaults_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 50,
                               "current_weekly_remaining_percent": 50}],
            "base_resp": {"status_code": 0},
        }
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_reset_at, 0)
        self.assertEqual(snapshot.weekly_reset_at, 0)


class TestDiffersFrom(unittest.TestCase):
    def test_none_always_differs(self):
        self.assertTrue(minimax.MinimaxSnapshot(50, 50).differs_from(None))

    def test_same_percent_ignores_reset_time(self):
        a = minimax.MinimaxSnapshot(50, 20, 111, 222)
        b = minimax.MinimaxSnapshot(50, 20, 999, 888)
        self.assertFalse(a.differs_from(b))

    def test_changed_percent_differs(self):
        a = minimax.MinimaxSnapshot(50, 20)
        b = minimax.MinimaxSnapshot(49, 20)
        self.assertTrue(a.differs_from(b))

    def test_changed_weekly_differs(self):
        a = minimax.MinimaxSnapshot(50, 20)
        b = minimax.MinimaxSnapshot(50, 21)
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
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_numeric_string_percent(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": "64",
                               "current_weekly_remaining_percent": "23"}],
            "base_resp": {"status_code": 0},
        }
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_float_string_percent(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": "64.9",
                               "current_weekly_remaining_percent": "23.4"}],
            "base_resp": {"status_code": 0},
        }
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_string_status_code_zero_accepted(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64,
                               "current_weekly_remaining_percent": 23}],
            "base_resp": {"status_code": "0", "status_msg": "success"},
        }
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_missing_status_code_raises(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64}],
            "base_resp": {"status_msg": "success"},
        }
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(body)

    def test_infinite_percent_is_clamped(self):
        """inf 走 int() 会抛 OverflowError，必须被兜住并规整进 0..100"""
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": float("inf"),
                               "current_weekly_remaining_percent": float("-inf")}],
            "base_resp": {"status_code": 0},
        }
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_base_resp_list_raises(self):
        body = {"model_remains": [], "base_resp": ["nope"]}
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(body)

    def _body_with_status(self, status):
        return {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 64,
                               "current_weekly_remaining_percent": 23}],
            "base_resp": {"status_code": status},
        }

    def test_bool_false_status_code_raises(self):
        """False 是 JSON 布尔不是状态码，绝不能被当成 0（成功）"""
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(self._body_with_status(False))

    def test_bool_true_status_code_raises(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(self._body_with_status(True))

    def test_fractional_float_status_code_raises(self):
        """0.4 截断成 0 等于放行畸形响应，必须当错误"""
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(self._body_with_status(0.5))

    def test_float_one_status_code_raises(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(self._body_with_status(1.0))

    def test_negative_fractional_float_status_code_raises(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.parse_remains(self._body_with_status(-0.5))

    def test_string_zero_status_code_still_accepted(self):
        """字符串 "0" 是合法成功码，别被改坏"""
        snapshot = minimax.parse_remains(self._body_with_status("0"))
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_bool_percent_becomes_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": True,
                               "current_weekly_remaining_percent": False}],
            "base_resp": {"status_code": 0},
        }
        snapshot = minimax.parse_remains(body)
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
        snapshot = minimax.parse_remains(body)
        self.assertEqual(snapshot.interval_reset_at, 0)
        self.assertEqual(snapshot.weekly_reset_at, 0)


class TestParseRemainsContract(unittest.TestCase):
    """契约：parse_remains 只允许抛 MinimaxError，任何其它异常都不许逃出来"""

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
                    result = minimax.parse_remains(body)
                except minimax.MinimaxError:
                    continue
                except Exception as exc:  # noqa: BLE001 - 契约测试要看到所有异常类型
                    self.fail("parse_remains 抛出了非 MinimaxError: %r (body=%r)"
                              % (exc, body))
                # 没抛异常也是一种合法结果，但百分比必须是规整过的整数
                self.assertIsInstance(result, minimax.MinimaxSnapshot)
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
        snapshot = minimax.parse_remains(body)
        self.assertGreaterEqual(snapshot.interval_pct, 0)
        self.assertLessEqual(snapshot.interval_pct, 100)
        self.assertGreaterEqual(snapshot.weekly_pct, 0)
        self.assertLessEqual(snapshot.weekly_pct, 100)


class TestLevelColor(unittest.TestCase):
    def test_warm_ramp_boundaries(self):
        self.assertEqual(minimax.level_color(100, minimax.WARM_RAMP), minimax.GREEN)
        self.assertEqual(minimax.level_color(50, minimax.WARM_RAMP), minimax.GREEN)
        self.assertEqual(minimax.level_color(49, minimax.WARM_RAMP), minimax.YELLOW)
        self.assertEqual(minimax.level_color(20, minimax.WARM_RAMP), minimax.YELLOW)
        self.assertEqual(minimax.level_color(19, minimax.WARM_RAMP), minimax.RED)
        self.assertEqual(minimax.level_color(0, minimax.WARM_RAMP), minimax.RED)

    def test_cool_ramp_boundaries(self):
        self.assertEqual(minimax.level_color(100, minimax.COOL_RAMP), minimax.TEAL)
        self.assertEqual(minimax.level_color(50, minimax.COOL_RAMP), minimax.TEAL)
        self.assertEqual(minimax.level_color(49, minimax.COOL_RAMP), minimax.BLUE)
        self.assertEqual(minimax.level_color(20, minimax.COOL_RAMP), minimax.BLUE)
        self.assertEqual(minimax.level_color(19, minimax.COOL_RAMP), minimax.PURPLE)
        self.assertEqual(minimax.level_color(0, minimax.COOL_RAMP), minimax.PURPLE)

    def test_clamps_out_of_range(self):
        self.assertEqual(minimax.level_color(150, minimax.WARM_RAMP), minimax.GREEN)
        self.assertEqual(minimax.level_color(-10, minimax.WARM_RAMP), minimax.RED)


class TestRenderBar(unittest.TestCase):
    def test_returns_100_pixels(self):
        self.assertEqual(len(minimax.render_bar(50, 50)), 100)

    def test_full_bars_fill_19_columns(self):
        grid = minimax.render_bar(100, 100)
        for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
            for col in range(minimax.BAR_WIDTH):
                self.assertNotEqual(grid[row * minimax.COLS + col], minimax.BLACK)

    def test_exhausted_bars_keep_a_dim_dot(self):
        # 0% 不能全黑 —— 否则和「功能未启用 / 灯坏了」分不出来
        grid = minimax.render_bar(0, 0)
        for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
            self.assertNotEqual(grid[row * minimax.COLS], minimax.BLACK,
                                "row %d 的左端应有一个暗点" % row)
            # 只有第一列亮，其余全黑
            for col in range(1, minimax.BAR_WIDTH):
                self.assertEqual(grid[row * minimax.COLS + col], minimax.BLACK)

    def test_exhausted_dot_is_dimmed_but_colored(self):
        grid = minimax.render_bar(0, 0)
        warm_dot = grid[minimax.ROW_TOP[0] * minimax.COLS]
        cool_dot = grid[minimax.ROW_BOTTOM[0] * minimax.COLS]
        # 仍然保有告警色相：红的 R 通道最大，紫的 B 通道最大
        self.assertGreater(warm_dot[0], warm_dot[1])
        self.assertGreater(warm_dot[0], warm_dot[2])
        self.assertGreater(cool_dot[2], cool_dot[1])
        # 但明显比正常告警色暗
        self.assertLess(sum(warm_dot), sum(minimax.RED))
        self.assertLess(sum(cool_dot), sum(minimax.PURPLE))

    def test_exhausted_dot_distinct_from_nonzero(self):
        # 1% 和 0% 必须能区分：颜色不同（1% 是亮色，0% 是暗色）
        one_pct = minimax.render_bar(1, 1)[minimax.ROW_TOP[0] * minimax.COLS]
        zero_pct = minimax.render_bar(0, 0)[minimax.ROW_TOP[0] * minimax.COLS]
        self.assertNotEqual(one_pct, zero_pct)
        self.assertLess(sum(zero_pct), sum(one_pct))

    def test_half_fill_is_ten_columns(self):
        grid = minimax.render_bar(50, 50)
        for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
            lit = sum(1 for col in range(minimax.BAR_WIDTH)
                      if grid[row * minimax.COLS + col] != minimax.BLACK)
            self.assertEqual(lit, 10, "row %d 的填充列数不对" % row)

    def test_low_percent_rounding(self):
        # 只要剩余 > 0 就至少亮一格 —— 额度过低时必须能和「已耗尽」/「功能未启用」区分开
        for pct, expected in ((1, 1), (2, 1), (3, 1), (0, 1)):
            grid = minimax.render_bar(pct, pct)
            for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
                lit = sum(1 for col in range(minimax.BAR_WIDTH)
                          if grid[row * minimax.COLS + col] != minimax.BLACK)
                self.assertEqual(lit, expected,
                                 "%d%% 在 row %d 的填充列数应为 %d" % (pct, row, expected))

    def test_low_percent_keeps_critical_color(self):
        # 1% 的那一格必须是告警色，不能是"正常"色
        grid = minimax.render_bar(1, 1)
        self.assertEqual(grid[minimax.ROW_TOP[0] * minimax.COLS], minimax.RED)
        self.assertEqual(grid[minimax.ROW_BOTTOM[0] * minimax.COLS], minimax.PURPLE)

    def test_minimum_one_column_never_exceeds_bar_width(self):
        for pct in range(0, 101):
            grid = minimax.render_bar(pct, pct)
            for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
                lit = sum(1 for col in range(minimax.BAR_WIDTH)
                          if grid[row * minimax.COLS + col] != minimax.BLACK)
                self.assertGreaterEqual(lit, 1 if pct > 0 else 0)
                self.assertLessEqual(lit, minimax.BAR_WIDTH)

    def test_last_column_always_black(self):
        grid = minimax.render_bar(100, 100)
        for row in range(minimax.ROWS):
            self.assertEqual(grid[row * minimax.COLS + minimax.COLS - 1], minimax.BLACK)

    def test_separator_row_is_black(self):
        grid = minimax.render_bar(100, 100)
        for col in range(minimax.COLS):
            self.assertEqual(grid[2 * minimax.COLS + col], minimax.BLACK)

    def test_rows_do_not_overlap(self):
        self.assertEqual(set(minimax.ROW_TOP) & set(minimax.ROW_BOTTOM), set())
        self.assertNotIn(2, minimax.ROW_TOP)
        self.assertNotIn(2, minimax.ROW_BOTTOM)

    def test_high_percent_uses_warm_and_cool_colors(self):
        grid = minimax.render_bar(74, 24)
        self.assertEqual(grid[minimax.ROW_TOP[0] * minimax.COLS], minimax.GREEN)
        self.assertEqual(grid[minimax.ROW_BOTTOM[0] * minimax.COLS], minimax.BLUE)

    def test_low_percent_uses_red_and_purple(self):
        grid = minimax.render_bar(12, 8)
        self.assertEqual(grid[minimax.ROW_TOP[0] * minimax.COLS], minimax.RED)
        self.assertEqual(grid[minimax.ROW_BOTTOM[0] * minimax.COLS], minimax.PURPLE)

    def test_unfilled_part_is_black(self):
        grid = minimax.render_bar(74, 24)
        # 5h 74% → int(19*0.74+0.5) = 14 列填充，第 15 列起为黑
        row = minimax.ROW_TOP[0]
        self.assertNotEqual(grid[row * minimax.COLS + 13], minimax.BLACK)
        self.assertEqual(grid[row * minimax.COLS + 14], minimax.BLACK)


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


class TestFetchRemains(unittest.TestCase):
    def setUp(self):
        self._original_urlopen = minimax.urllib.request.urlopen

    def tearDown(self):
        minimax.urllib.request.urlopen = self._original_urlopen

    def test_requires_api_key(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.fetch_quota("")

    def test_network_failure_becomes_quota_error(self):
        with self.assertRaises(minimax.MinimaxError):
            minimax.fetch_quota("dummy", api_base="http://127.0.0.1:9", timeout=1)

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

        minimax.urllib.request.urlopen = fake_urlopen
        snapshot = minimax.fetch_quota("dummy-key")

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

        minimax.urllib.request.urlopen = fake_urlopen
        minimax.fetch_quota("dummy-key", api_base="https://api.minimaxi.com/")
        self.assertEqual(captured["url"],
                         "https://api.minimaxi.com/v1/token_plan/remains")

    def test_invalid_json_becomes_quota_error(self):
        minimax.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(b"not json")
        with self.assertRaises(minimax.MinimaxError):
            minimax.fetch_quota("dummy-key")

    def test_business_error_becomes_quota_error(self):
        payload = json.dumps({
            "base_resp": {"status_code": 2049, "status_msg": "invalid api key"}
        }).encode()
        minimax.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(payload)
        with self.assertRaises(minimax.MinimaxError):
            minimax.fetch_quota("dummy-key")

    def test_malformed_api_base_becomes_quota_error(self):
        """api_base 配错时只能抛 MinimaxError，不能把 ValueError/AttributeError 漏出去"""
        for bad_base in ("", "not a url", "://x", 123):
            with self.subTest(api_base=bad_base):
                with self.assertRaises(minimax.MinimaxError):
                    minimax.fetch_quota("dummy-key", api_base=bad_base)


class TestResetProgress(unittest.TestCase):
    def test_zero_right_after_reset(self):
        now = 1_000_000_000_000
        window = 5 * 3600 * 1000
        self.assertEqual(minimax.reset_progress_pct(now + window, now_ms=now), 0)

    def test_halfway(self):
        now = 1_000_000_000_000
        window = 5 * 3600 * 1000
        self.assertEqual(minimax.reset_progress_pct(now + window // 2, now_ms=now), 50)

    def test_almost_reset(self):
        now = 1_000_000_000_000
        self.assertEqual(minimax.reset_progress_pct(now + 60_000, now_ms=now), 99)

    def test_past_reset_clamps_to_100(self):
        now = 1_000_000_000_000
        self.assertEqual(minimax.reset_progress_pct(now - 60_000, now_ms=now), 100)

    def test_missing_reset_time_returns_none(self):
        self.assertIsNone(minimax.reset_progress_pct(0, now_ms=1_000_000_000_000))
        self.assertIsNone(minimax.reset_progress_pct(None, now_ms=1_000_000_000_000))

    def test_out_of_range_clamped(self):
        now = 1_000_000_000_000
        window = 5 * 3600 * 1000
        # 距离重置超过一个窗口（异常数据）也不能超过 0..100
        self.assertEqual(minimax.reset_progress_pct(now + window * 3, now_ms=now), 0)


class TestResetBar(unittest.TestCase):
    def test_row2_is_black_without_reset_progress(self):
        grid = minimax.render_bar(50, 50)
        for col in range(minimax.COLS):
            self.assertEqual(grid[2 * minimax.COLS + col], minimax.BLACK)

    def test_row2_always_fully_lit_when_progress_given(self):
        # 整行 19 格常亮：走过的部分是渐变色，剩下的是暗灰轨道
        for pct in (0, 1, 50, 100):
            grid = minimax.render_bar(50, 50, reset_pct=pct)
            for col in range(minimax.BAR_WIDTH):
                self.assertNotEqual(grid[2 * minimax.COLS + col], minimax.BLACK,
                                    "reset_pct=%d 时 col%d 不应是黑的" % (pct, col))

    def test_row2_colored_part_matches_progress(self):
        for pct, expected in ((0, 1), (50, 10), (100, 19)):
            grid = minimax.render_bar(50, 50, reset_pct=pct)
            colored = sum(1 for col in range(minimax.BAR_WIDTH)
                          if grid[2 * minimax.COLS + col] not in (minimax.BLACK,
                                                                minimax.RESET_TRACK))
            self.assertEqual(colored, expected, "reset_pct=%d 的彩色列数不对" % pct)

    def test_row2_remainder_is_dark_grey_track(self):
        grid = minimax.render_bar(50, 50, reset_pct=50)
        row = 2 * minimax.COLS
        # 前 10 格是彩色（非黑非灰），后 9 格是暗灰
        for col in range(10):
            self.assertNotIn(grid[row + col], (minimax.BLACK, minimax.RESET_TRACK))
        for col in range(10, minimax.BAR_WIDTH):
            self.assertEqual(grid[row + col], minimax.RESET_TRACK)
        # 轨道明显暗于彩色部分
        self.assertLess(sum(minimax.RESET_TRACK),
                        sum(grid[row]))

    def test_reset_row_last_column_black(self):
        grid = minimax.render_bar(50, 50, reset_pct=100)
        self.assertEqual(grid[2 * minimax.COLS + minimax.COLS - 1], minimax.BLACK)

    def test_reset_row_does_not_touch_quota_rows(self):
        without = minimax.render_bar(30, 20)
        with_reset = minimax.render_bar(30, 20, reset_pct=80)
        for row in minimax.ROW_TOP + minimax.ROW_BOTTOM:
            for col in range(minimax.COLS):
                self.assertEqual(without[row * minimax.COLS + col],
                                 with_reset[row * minimax.COLS + col])

    def test_reset_row_uses_multiple_colors(self):
        grid = minimax.render_bar(50, 50, reset_pct=100)
        colors = {grid[2 * minimax.COLS + col] for col in range(minimax.BAR_WIDTH)}
        self.assertGreater(len(colors), 4, "整行应该铺开多种颜色，而不是单一颜色")

    def test_reset_row_starts_cool_and_ends_warm(self):
        grid = minimax.render_bar(50, 50, reset_pct=100)
        first = grid[2 * minimax.COLS]
        last = grid[2 * minimax.COLS + minimax.BAR_WIDTH - 1]
        # 起点偏蓝（B 最大），终点偏暖（R 最大）
        self.assertGreater(first[2], first[0])
        self.assertGreater(last[0], last[2])

    def test_reset_row_keeps_one_colored_cell_at_zero_progress(self):
        grid = minimax.render_bar(50, 50, reset_pct=0)
        row = 2 * minimax.COLS
        self.assertNotIn(grid[row], (minimax.BLACK, minimax.RESET_TRACK))
        for col in range(1, minimax.BAR_WIDTH):
            self.assertEqual(grid[row + col], minimax.RESET_TRACK)


if __name__ == "__main__":
    unittest.main()
