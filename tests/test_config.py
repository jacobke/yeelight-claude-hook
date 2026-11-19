#!/usr/bin/env python3
"""config.py 的单元测试"""

import argparse
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as app_config  # noqa: E402


def make_args(**overrides):
    """构造一个模拟 argparse.Namespace 的参数对象"""
    defaults = dict(
        ip=None, port=None, instance=None, shared=None,
        quota_api_key=None, quota_api_base=None, quota_interval=None,
        no_quota=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveSettings(unittest.TestCase):
    def test_defaults_when_nothing_configured(self):
        s = app_config.resolve_settings(make_args(), {}, env={}, claude_token="")
        self.assertIsNone(s.ip)
        self.assertEqual(s.port, 55443)
        self.assertEqual(s.instance, 0)
        self.assertEqual(s.shared, 1)
        self.assertTrue(s.quota_enabled)
        self.assertEqual(s.api_base, "https://api.minimaxi.com")
        self.assertEqual(s.api_key, "")
        self.assertEqual(s.poll_interval, 300)
        self.assertEqual(s.takeover_delay, 20)

    def test_config_file_used_when_no_cli(self):
        cfg = {
            "ip": "10.0.0.1", "port": 1234, "instance": 3, "shared": 2,
            "quota": {
                "enabled": True,
                "api_base": "https://api.minimax.io",
                "api_key": "from-config",
                "poll_interval": 60,
                "takeover_delay": 5,
            },
        }
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.ip, "10.0.0.1")
        self.assertEqual(s.port, 1234)
        self.assertEqual(s.instance, 3)
        self.assertEqual(s.shared, 2)
        self.assertEqual(s.api_base, "https://api.minimax.io")
        self.assertEqual(s.api_key, "from-config")
        self.assertEqual(s.poll_interval, 60)
        self.assertEqual(s.takeover_delay, 5)

    def test_cli_beats_config(self):
        cfg = {"ip": "10.0.0.1", "quota": {"api_key": "from-config"}}
        args = make_args(ip="10.0.0.9", quota_api_key="from-cli")
        s = app_config.resolve_settings(args, cfg, env={}, claude_token="")
        self.assertEqual(s.ip, "10.0.0.9")
        self.assertEqual(s.api_key, "from-cli")

    def test_env_beats_config(self):
        cfg = {"quota": {"api_key": "from-config"}}
        s = app_config.resolve_settings(make_args(), cfg,
                                        env={"MINIMAX_API_KEY": "from-env"},
                                        claude_token="")
        self.assertEqual(s.api_key, "from-env")

    def test_claude_settings_is_last_resort(self):
        s = app_config.resolve_settings(make_args(), {}, env={},
                                        claude_token="from-claude")
        self.assertEqual(s.api_key, "from-claude")

    def test_full_api_key_precedence(self):
        cfg = {"quota": {"api_key": "from-config"}}
        env = {"MINIMAX_API_KEY": "from-env"}
        args = make_args(quota_api_key="from-cli")
        self.assertEqual(
            app_config.resolve_settings(args, cfg, env=env,
                                        claude_token="from-claude").api_key,
            "from-cli")
        self.assertEqual(
            app_config.resolve_settings(make_args(), cfg, env=env,
                                        claude_token="from-claude").api_key,
            "from-env")
        self.assertEqual(
            app_config.resolve_settings(make_args(), cfg, env={},
                                        claude_token="from-claude").api_key,
            "from-config")

    def test_no_quota_flag_disables(self):
        s = app_config.resolve_settings(make_args(no_quota=True), {}, env={},
                                        claude_token="")
        self.assertFalse(s.quota_enabled)

    def test_config_can_disable_quota(self):
        cfg = {"quota": {"enabled": False}}
        s = app_config.resolve_settings(make_args(), cfg, env={},
                                        claude_token="")
        self.assertFalse(s.quota_enabled)

    def test_malformed_quota_section_is_ignored(self):
        cfg = {"quota": "not-a-dict"}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertTrue(s.quota_enabled)
        self.assertEqual(s.api_key, "")


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(app_config.load_config("/nonexistent/config.json"), {})

    def test_invalid_json_returns_empty(self):
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(app_config.load_config(path), {})

    def test_non_dict_json_returns_empty(self):
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        self.assertEqual(app_config.load_config(path), {})

    def test_valid_file_is_returned(self):
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ip": "10.0.0.1"}, f)
        self.assertEqual(app_config.load_config(path), {"ip": "10.0.0.1"})


class TestReadClaudeSettingsToken(unittest.TestCase):
    def test_reads_token(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-test"}}, f)
        self.assertEqual(app_config.read_claude_settings_token(path), "sk-test")

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            app_config.read_claude_settings_token("/nonexistent/settings.json"), "")

    def test_missing_env_section_returns_empty(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"other": {}}, f)
        self.assertEqual(app_config.read_claude_settings_token(path), "")


if __name__ == "__main__":
    unittest.main()
