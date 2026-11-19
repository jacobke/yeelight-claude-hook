#!/usr/bin/env python3
"""yeelight-daemon.py 的调度逻辑测试

daemon 文件名带连字符，不能直接 import，用 importlib 按路径加载。
"""

import importlib.util
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quota  # noqa: E402

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
    daemon.quota_enabled = True
    daemon.quota_needs_repaint = True
    daemon.last_effect_finished_at = 0.0
    daemon.takeover_delay = 20
    daemon.last_snapshot = None
    daemon.last_rendered = None
    daemon.last_quota_fetch_at = 0.0
    daemon.poll_interval = 300
    daemon.api_key = "dummy"
    daemon.api_base = quota.DEFAULT_API_BASE
    daemon.instance = 2
    daemon.effect_thread = None
    daemon.painted = []
    daemon.paint_quota = lambda snapshot: daemon.painted.append(snapshot)
    for key, value in overrides.items():
        setattr(daemon, key, value)
    return daemon


class TestQuotaTick(unittest.TestCase):
    def test_effect_running_blocks_paint(self):
        d = make_daemon(effect_thread=FakeThread(True))
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertFalse(d.quota_tick())
        self.assertEqual(d.painted, [])

    def test_takeover_delay_blocks_paint(self):
        d = make_daemon(last_effect_finished_at=time.time())
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertFalse(d.quota_tick())
        self.assertEqual(d.painted, [])

    def test_paints_when_snapshot_available(self):
        d = make_daemon()
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertTrue(d.quota_tick())
        self.assertEqual(len(d.painted), 1)

    def test_no_snapshot_keeps_screen_untouched(self):
        d = make_daemon()
        d.quota_snapshot_if_available = lambda now=None: None
        self.assertFalse(d.quota_tick())
        self.assertEqual(d.painted, [])

    def test_unchanged_snapshot_does_not_repaint(self):
        d = make_daemon(quota_needs_repaint=False,
                        last_rendered=quota.QuotaSnapshot(50, 50))
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertFalse(d.quota_tick())
        self.assertEqual(d.painted, [])

    def test_changed_snapshot_repaints(self):
        d = make_daemon(quota_needs_repaint=False,
                        last_rendered=quota.QuotaSnapshot(50, 50))
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(49, 50)
        self.assertTrue(d.quota_tick())
        self.assertEqual(len(d.painted), 1)

    def test_disabled_quota_never_paints(self):
        d = make_daemon(quota_enabled=False)
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertFalse(d.quota_tick())


class TestSnapshotCache(unittest.TestCase):
    def test_fresh_cache_is_reused(self):
        d = make_daemon()
        calls = []
        original = daemon_module.quota.fetch_quota

        def fake_fetch(api_key, api_base):
            calls.append(api_base)
            return quota.QuotaSnapshot(50, 50)

        daemon_module.quota.fetch_quota = fake_fetch
        try:
            first = d.quota_snapshot_if_available(now=1000.0)
            second = d.quota_snapshot_if_available(now=1000.0 + 10)
        finally:
            daemon_module.quota.fetch_quota = original

        self.assertEqual(first.interval_pct, 50)
        self.assertEqual(second.interval_pct, 50)
        self.assertEqual(len(calls), 1)

    def test_stale_cache_triggers_refetch(self):
        d = make_daemon()
        calls = []
        original = daemon_module.quota.fetch_quota

        def fake_fetch(api_key, api_base):
            calls.append(api_base)
            return quota.QuotaSnapshot(50, 50)

        daemon_module.quota.fetch_quota = fake_fetch
        try:
            d.quota_snapshot_if_available(now=1000.0)
            d.quota_snapshot_if_available(now=1000.0 + 301)
        finally:
            daemon_module.quota.fetch_quota = original

        self.assertEqual(len(calls), 2)

    def test_fetch_failure_keeps_old_snapshot(self):
        d = make_daemon()
        d.last_snapshot = quota.QuotaSnapshot(42, 24)
        original = daemon_module.quota.fetch_quota

        def failing_fetch(api_key, api_base):
            raise quota.QuotaError("boom")

        daemon_module.quota.fetch_quota = failing_fetch
        try:
            snapshot = d.quota_snapshot_if_available(now=1000.0)
        finally:
            daemon_module.quota.fetch_quota = original

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.interval_pct, 42)

    def test_fetch_failure_without_previous_snapshot_returns_none(self):
        d = make_daemon()
        original = daemon_module.quota.fetch_quota

        def failing_fetch(api_key, api_base):
            raise quota.QuotaError("boom")

        daemon_module.quota.fetch_quota = failing_fetch
        try:
            snapshot = d.quota_snapshot_if_available(now=1000.0)
        finally:
            daemon_module.quota.fetch_quota = original

        self.assertIsNone(snapshot)


class TestInstanceMarkerDoesNotOverlapBar(unittest.TestCase):
    def test_marker_lands_in_reserved_column(self):
        grid = quota.render_bar(100, 100)
        daemon = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
        daemon.instance = 2
        daemon.mark_instance(grid)

        # instance 2 → 物理行 3 的 col19
        self.assertEqual(grid[3 * 20 + 19], (255, 200, 50))
        # 条本身（col0..col18）没有被破坏
        self.assertEqual(grid[3 * 20 + 18], quota.GREEN)
        self.assertEqual(grid[4 * 20 + 18], quota.GREEN)


class TestQuotaStateIsAccepted(unittest.TestCase):
    def test_quota_state_is_valid(self):
        self.assertIn("quota", daemon_module.VALID_STATES)

    def test_all_previous_states_still_valid(self):
        for state in ["start", "thinking", "done", "wait", "interrupt",
                      "complete", "end", "off"]:
            self.assertIn(state, daemon_module.VALID_STATES)

    def test_unknown_state_is_rejected(self):
        daemon = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
        result = daemon.handle_command({"state": "nope", "duration": 0})
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
