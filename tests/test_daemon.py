#!/usr/bin/env python3
"""yeelight-daemon.py 的调度逻辑测试

daemon 文件名带连字符，不能直接 import，用 importlib 按路径加载。
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import minimax  # noqa: E402
import deepseek as deepseek_module  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_daemon_module():
    path = os.path.join(ROOT, "yeelight-daemon.py")
    spec = importlib.util.spec_from_file_location("yeelight_daemon", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


daemon_module = load_daemon_module()


class FakeThread:
    def __init__(self, alive):
        self._alive = alive

    def is_alive(self):
        return self._alive


def make_daemon(**overrides):
    """构造一个不连接设备的 daemon 实例（只填调度相关字段）"""
    daemon = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
    daemon.minimax_enabled = True
    daemon.display_needs_repaint = True
    daemon.last_effect_finished_at = 0.0
    daemon.takeover_delay = 20
    daemon.minimax_snapshot = None
    daemon.last_minimax_rendered = None
    daemon.last_minimax_reset_fill = None
    daemon.minimax_last_fetch_at = 0.0
    daemon.minimax_poll_interval = 300
    daemon.minimax_api_key = "dummy"
    daemon.minimax_api_base = minimax.DEFAULT_API_BASE
    daemon.instance = 2
    daemon.effect_thread = None
    daemon.painted = []
    daemon.paint_minimax = lambda snapshot: daemon.painted.append(snapshot)
    daemon.deepseek_enabled = False
    daemon.deepseek_api_key = ""
    daemon.deepseek_api_base = deepseek_module.DEFAULT_API_BASE
    daemon.deepseek_poll_interval = 300
    daemon.deepseek_alternate_interval = 5
    daemon.deepseek_balance = None
    daemon.deepseek_spend = 0.0
    daemon.deepseek_last_fetch_at = 0.0
    daemon.deepseek_subpage = 0
    daemon.deepseek_subpage_started_at = 0.0
    daemon.last_deepseek_rendered = None
    daemon.rotation_interval = 10
    daemon.transition_frames = 5
    daemon.transition = None
    daemon.command_interval = 1.0
    daemon.page = "minimax"
    daemon.page_started_at = 0.0
    for key, value in overrides.items():
        setattr(daemon, key, value)
    return daemon


class TestMinimaxTick(unittest.TestCase):
    def test_effect_running_blocks_paint(self):
        d = make_daemon(effect_thread=FakeThread(True))
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertFalse(d.display_tick())
        self.assertEqual(d.painted, [])

    def test_takeover_delay_blocks_paint(self):
        d = make_daemon(last_effect_finished_at=time.time())
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertFalse(d.display_tick())
        self.assertEqual(d.painted, [])

    def test_paints_when_snapshot_available(self):
        d = make_daemon()
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertTrue(d.display_tick())
        self.assertEqual(len(d.painted), 1)

    def test_no_snapshot_keeps_screen_untouched(self):
        d = make_daemon()
        d.minimax_snapshot_if_available = lambda now=None: None
        self.assertFalse(d.display_tick())
        self.assertEqual(d.painted, [])

    def test_unchanged_snapshot_does_not_repaint(self):
        d = make_daemon(display_needs_repaint=False,
                        last_minimax_rendered=minimax.MinimaxSnapshot(50, 50))
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertFalse(d.display_tick())
        self.assertEqual(d.painted, [])

    def test_changed_snapshot_repaints(self):
        d = make_daemon(display_needs_repaint=False,
                        last_minimax_rendered=minimax.MinimaxSnapshot(50, 50))
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(49, 50)
        self.assertTrue(d.display_tick())
        self.assertEqual(len(d.painted), 1)

    def test_reset_countdown_change_triggers_repaint(self):
        # 配额百分比没变，但倒计时走过一格 → 需要重绘中间那行
        now_ms = 1_000_000_000_000
        reset_at = now_ms + minimax.INTERVAL_WINDOW_MS // 2
        snapshot = minimax.MinimaxSnapshot(50, 50, interval_reset_at=reset_at)

        d = make_daemon(display_needs_repaint=False,
                        last_minimax_rendered=snapshot,
                        last_minimax_reset_fill=10)
        d.minimax_snapshot_if_available = lambda now=None: snapshot
        self.assertFalse(d.display_should_paint(now=now_ms / 1000.0))

        # 走过一格后应触发重绘。每格约 15.8 分钟，但 50% 这个位置
        # 要到 56% 才跨格，所以取 20 分钟留出余量
        later = now_ms + 20 * 60 * 1000
        self.assertTrue(d.display_should_paint(now=later / 1000.0))

    def test_reset_countdown_absent_does_not_force_repaint(self):
        # 没有重置时间时，中间那行不画，也不应因此反复重绘
        snapshot = minimax.MinimaxSnapshot(50, 50, interval_reset_at=0)
        d = make_daemon(display_needs_repaint=False,
                        last_minimax_rendered=snapshot,
                        last_minimax_reset_fill=None)
        d.minimax_snapshot_if_available = lambda now=None: snapshot
        self.assertFalse(d.display_should_paint(now=1_000_000_000.0))

    def test_disabled_quota_never_paints(self):
        d = make_daemon(minimax_enabled=False)
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertFalse(d.display_tick())


class TestTakeoverSequence(unittest.TestCase):
    def _daemon(self):
        d = make_daemon()
        d.sent = []
        d.command_interval = 0
        d.direct_mode_ready = False
        d.last_command_time = 0
        d.command_count = 0

        def fake_send(method, params):
            d.sent.append(method)
            return True

        d.send_command = fake_send
        return d

    def test_takeover_sent_once(self):
        d = self._daemon()
        d._takeover_and_send([(0, 0, 0)] * 100)
        d._takeover_and_send([(0, 0, 0)] * 100)
        self.assertEqual(d.sent.count("activate_fx_mode"), 1)
        self.assertEqual(d.sent.count("stop_cf"), 1)

    def test_effect_resets_direct_mode_flag(self):
        d = self._daemon()
        d._takeover_and_send([(0, 0, 0)] * 100)
        self.assertTrue(d.direct_mode_ready)
        d.direct_mode_ready = False
        d._takeover_and_send([(0, 0, 0)] * 100)
        self.assertEqual(d.sent.count("activate_fx_mode"), 2)

    def test_reconnect_clears_flag(self):
        d = self._daemon()
        d.direct_mode_ready = True
        d.sock = None
        d.connect = lambda: True
        d.reconnect()
        self.assertFalse(d.direct_mode_ready)


class TestSnapshotCache(unittest.TestCase):
    def test_fresh_cache_is_reused(self):
        d = make_daemon()
        calls = []
        original = daemon_module.minimax.fetch_quota

        def fake_fetch(api_key, api_base):
            calls.append(api_base)
            return minimax.MinimaxSnapshot(50, 50)

        daemon_module.minimax.fetch_quota = fake_fetch
        try:
            first = d.minimax_snapshot_if_available(now=1000.0)
            second = d.minimax_snapshot_if_available(now=1000.0 + 10)
        finally:
            daemon_module.minimax.fetch_quota = original

        self.assertEqual(first.interval_pct, 50)
        self.assertEqual(second.interval_pct, 50)
        self.assertEqual(len(calls), 1)

    def test_stale_cache_triggers_refetch(self):
        d = make_daemon()
        calls = []
        original = daemon_module.minimax.fetch_quota

        def fake_fetch(api_key, api_base):
            calls.append(api_base)
            return minimax.MinimaxSnapshot(50, 50)

        daemon_module.minimax.fetch_quota = fake_fetch
        try:
            d.minimax_snapshot_if_available(now=1000.0)
            d.minimax_snapshot_if_available(now=1000.0 + 301)
        finally:
            daemon_module.minimax.fetch_quota = original

        self.assertEqual(len(calls), 2)

    def test_fetch_failure_keeps_old_snapshot(self):
        d = make_daemon()
        d.minimax_snapshot = minimax.MinimaxSnapshot(42, 24)
        original = daemon_module.minimax.fetch_quota

        def failing_fetch(api_key, api_base):
            raise minimax.MinimaxError("boom")

        daemon_module.minimax.fetch_quota = failing_fetch
        try:
            snapshot = d.minimax_snapshot_if_available(now=1000.0)
        finally:
            daemon_module.minimax.fetch_quota = original

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.interval_pct, 42)

    def test_fetch_failure_without_previous_snapshot_returns_none(self):
        d = make_daemon()
        original = daemon_module.minimax.fetch_quota

        def failing_fetch(api_key, api_base):
            raise minimax.MinimaxError("boom")

        daemon_module.minimax.fetch_quota = failing_fetch
        try:
            snapshot = d.minimax_snapshot_if_available(now=1000.0)
        finally:
            daemon_module.minimax.fetch_quota = original

        self.assertIsNone(snapshot)


class TestInstanceMarkerDoesNotOverlapBar(unittest.TestCase):
    def test_marker_lands_in_reserved_column(self):
        grid = minimax.render_bar(100, 100)
        daemon = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
        daemon.instance = 2
        daemon.mark_instance(grid)

        # instance 2 → 物理行 3 的 col19
        self.assertEqual(grid[3 * 20 + 19], (255, 200, 50))
        # 条本身（col0..col18）没有被破坏
        self.assertEqual(grid[3 * 20 + 18], minimax.GREEN)
        self.assertEqual(grid[4 * 20 + 18], minimax.GREEN)


class TestMinimaxStateIsAccepted(unittest.TestCase):
    def test_minimax_state_is_valid(self):
        self.assertIn("minimax", daemon_module.VALID_STATES)

    def test_all_previous_states_still_valid(self):
        for state in ["start", "thinking", "done", "wait", "interrupt",
                      "complete", "end", "off"]:
            self.assertIn(state, daemon_module.VALID_STATES)

    def test_unknown_state_is_rejected(self):
        daemon = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
        result = daemon.handle_command({"state": "nope", "duration": 0})
        self.assertEqual(result["status"], "error")


class TestPageRotation(unittest.TestCase):
    def _daemon_with_both_pages(self, **overrides):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=58.0, deepseek_spend=3.2,
                        last_effect_finished_at=-1000.0, display_needs_repaint=False)
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: (d.deepseek_spend,
                                                           d.deepseek_balance)
        d.painted_pages = []
        d.sent_grids = []
        d._takeover_and_send = lambda grid: d.sent_grids.append(grid)
        for key, value in overrides.items():
            setattr(d, key, value)
        return d

    def test_single_page_never_rotates(self):
        d = make_daemon(deepseek_enabled=False, display_needs_repaint=False,
                        last_minimax_rendered=minimax.MinimaxSnapshot(50, 50),
                        last_effect_finished_at=-1000.0)
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        self.assertFalse(d.display_should_paint(now=1000.0))
        self.assertEqual(d.page, "minimax")

    def test_rotates_after_interval(self):
        d = self._daemon_with_both_pages(page="minimax", page_started_at=0.0)
        self.assertTrue(d.display_should_paint(now=11.0))
        self.assertEqual(d.page, "minimax", "应先开始过渡，而不是瞬间切页")
        self.assertEqual(d.transition["to"], "deepseek")

        for _ in range(d.transition_frames):
            d.paint_current_page()
        self.assertEqual(d.page, "deepseek")
        self.assertIsNone(d.transition)
        self.assertEqual(len(d.sent_grids), d.transition_frames)

    def test_does_not_rotate_before_interval(self):
        d = self._daemon_with_both_pages(
            page="minimax", page_started_at=0.0,
            last_minimax_rendered=minimax.MinimaxSnapshot(50, 50),
            last_minimax_reset_fill=None)
        self.assertFalse(d.display_should_paint(now=5.0))

    def test_rotation_stops_during_effect(self):
        d = self._daemon_with_both_pages(
            page="minimax", page_started_at=0.0,
            effect_thread=FakeThread(True))
        self.assertFalse(d.display_should_paint(now=11.0))
        self.assertEqual(d.page, "minimax")

    def test_effect_resets_to_first_page(self):
        d = self._daemon_with_both_pages(page="deepseek")
        # 直接验证效果结束时的字段重置逻辑
        d.reset_page_after_effect(now=500.0)
        self.assertEqual(d.page, "minimax")
        self.assertAlmostEqual(d.page_started_at, 500.0)
        self.assertEqual(d.deepseek_subpage, 0)

    def test_falls_back_when_deepseek_missing(self):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        display_needs_repaint=False,
                        last_minimax_rendered=minimax.MinimaxSnapshot(50, 50),
                        last_effect_finished_at=-1000.0, page="deepseek")
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: None
        self.assertTrue(d.display_should_paint(now=1000.0))
        self.assertEqual(d.page, "minimax")

    def test_failed_first_fetch_is_throttled(self):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=None, deepseek_last_fetch_at=0.0)
        calls = []
        original = daemon_module.deepseek.fetch_balance

        def failing_fetch(api_key, api_base):
            calls.append(1)
            raise deepseek_module.DeepSeekError("boom")

        daemon_module.deepseek.fetch_balance = failing_fetch
        try:
            for t in range(0, 60):          # 连续 60 次 tick（60 秒）
                d.deepseek_values_if_available(now=1000.0 + t)
        finally:
            daemon_module.deepseek.fetch_balance = original

        self.assertEqual(len(calls), 1, "首次失败后应等满轮询间隔再重试")

    def test_failed_fetch_retries_after_interval(self):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=None, deepseek_last_fetch_at=0.0)
        calls = []
        original = daemon_module.deepseek.fetch_balance

        def failing_fetch(api_key, api_base):
            calls.append(1)
            raise deepseek_module.DeepSeekError("boom")

        daemon_module.deepseek.fetch_balance = failing_fetch
        try:
            d.deepseek_values_if_available(now=1000.0)
            d.deepseek_values_if_available(now=1000.0 + 301)
        finally:
            daemon_module.deepseek.fetch_balance = original

        self.assertEqual(len(calls), 2)


class TestDeepSeekSubpage(unittest.TestCase):
    def _daemon(self, **overrides):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=456.0, deepseek_spend=123.0,
                        page="deepseek", page_started_at=0.0,
                        deepseek_subpage_started_at=0.0,
                        last_effect_finished_at=-1000.0,
                        display_needs_repaint=False)
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: (d.deepseek_spend,
                                                           d.deepseek_balance)
        for key, value in overrides.items():
            setattr(d, key, value)
        return d

    def test_alternate_mode_switches_after_interval(self):
        d = self._daemon()
        self.assertTrue(d.display_should_paint(now=6.0))
        self.assertEqual(d.deepseek_subpage, 1)

    def test_alternate_mode_waits_for_interval(self):
        d = self._daemon(deepseek_subpage=0,
                         last_deepseek_rendered=("alternate", ("123", "456"), 0))
        self.assertFalse(d.display_should_paint(now=2.0))
        self.assertEqual(d.deepseek_subpage, 0)

    def test_side_by_side_mode_does_not_switch(self):
        d = self._daemon(deepseek_balance=58.0, deepseek_spend=3.2,
                         last_deepseek_rendered=("side", ("3.2", "58"), 0))
        self.assertFalse(d.display_should_paint(now=6.0))
        self.assertEqual(d.deepseek_subpage, 0)

    def test_new_values_trigger_repaint(self):
        d = self._daemon(deepseek_balance=58.0, deepseek_spend=3.2,
                         last_deepseek_rendered=("side", ("3.2", "58"), 0))
        d.deepseek_spend = 4.0
        self.assertTrue(d.display_should_paint(now=6.0))


class TestDryRunKeyMasking(unittest.TestCase):
    """--dry-run 绝不能输出完整密钥"""

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "yeelight-daemon.py"),
             "--dry-run", *extra],
            capture_output=True, text=True, timeout=60)

    def test_keys_are_masked(self):
        result = self._run("--minimax-api-key", "TESTKEY12345678",
                           "--deepseek-api-key", "DSKEY12345678")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["minimax_api_key"], "TESTKE...5678")
        self.assertEqual(data["deepseek_api_key"], "DSKEY1...5678")
        self.assertNotIn("TESTKEY12345678", result.stdout)
        self.assertNotIn("DSKEY12345678", result.stdout)

    def test_no_minimax_flag_is_honoured(self):
        result = self._run("--no-minimax")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["minimax_enabled"])


class TestBlendGrids(unittest.TestCase):
    def test_alpha_zero_returns_first(self):
        a = [(10, 20, 30)] * 100
        b = [(200, 100, 50)] * 100
        self.assertEqual(daemon_module.blend_grids(a, b, 0.0), a)

    def test_alpha_one_returns_second(self):
        a = [(10, 20, 30)] * 100
        b = [(200, 100, 50)] * 100
        self.assertEqual(daemon_module.blend_grids(a, b, 1.0), b)

    def test_alpha_half_averages(self):
        a = [(0, 0, 0)]
        b = [(200, 100, 50)]
        self.assertEqual(daemon_module.blend_grids(a, b, 0.5), [(100, 50, 25)])

    def test_alpha_is_clamped(self):
        a = [(0, 0, 0)]
        b = [(255, 255, 255)]
        self.assertEqual(daemon_module.blend_grids(a, b, -1.0), a)
        self.assertEqual(daemon_module.blend_grids(a, b, 2.0), b)


class TestFadeTransition(unittest.TestCase):
    def _daemon(self):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=58.0, deepseek_spend=3.2,
                        page="minimax", page_started_at=0.0,
                        last_effect_finished_at=-1000.0,
                        transition_frames=3)
        d.minimax_snapshot_if_available = lambda now=None: minimax.MinimaxSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: (d.deepseek_spend,
                                                           d.deepseek_balance)
        d.sent_grids = []
        d._takeover_and_send = lambda grid: d.sent_grids.append(grid)
        return d

    def test_transition_runs_for_configured_frames(self):
        d = self._daemon()
        self.assertTrue(d.display_should_paint(now=11.0))
        for _ in range(3):
            d.paint_current_page()
        self.assertEqual(len(d.sent_grids), 3)
        self.assertEqual(d.page, "deepseek")
        self.assertIsNone(d.transition)

    def test_last_frame_is_target_page(self):
        d = self._daemon()
        d.display_should_paint(now=11.0)
        for _ in range(3):
            d.paint_current_page()
        target = d._page_grid("deepseek")
        self.assertEqual(d.sent_grids[-1], target)

    def test_zero_frames_switches_immediately(self):
        d = self._daemon()
        d.transition_frames = 0
        d.display_should_paint(now=11.0)
        self.assertEqual(d.page, "deepseek")
        self.assertIsNone(d.transition)

    def test_effect_end_clears_transition(self):
        d = self._daemon()
        d.display_should_paint(now=11.0)
        self.assertIsNotNone(d.transition)
        d.reset_page_after_effect(now=20.0)
        self.assertIsNone(d.transition)

    def test_transition_falls_back_when_target_unavailable(self):
        d = self._daemon()
        d.display_should_paint(now=11.0)
        d.deepseek_values_if_available = lambda now=None: None
        d.paint_current_page()
        self.assertIsNone(d.transition)
        self.assertEqual(d.page, "deepseek")


if __name__ == "__main__":
    unittest.main()
