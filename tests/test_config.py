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
        minimax_api_key=None, minimax_api_base=None, minimax_interval=None,
        no_minimax=False,
        deepseek_api_key=None, deepseek_api_base=None, no_deepseek=False,
        rotation_interval=None, transition_frames=None,
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
        self.assertTrue(s.minimax_enabled)
        self.assertEqual(s.minimax_api_base, "https://api.minimaxi.com")
        self.assertEqual(s.minimax_api_key, "")
        self.assertEqual(s.minimax_poll_interval, 300)
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
        self.assertEqual(s.minimax_api_base, "https://api.minimax.io")
        self.assertEqual(s.minimax_api_key, "from-config")
        self.assertEqual(s.minimax_poll_interval, 60)
        self.assertEqual(s.takeover_delay, 5)

    def test_cli_beats_config(self):
        cfg = {"ip": "10.0.0.1", "quota": {"api_key": "from-config"}}
        args = make_args(ip="10.0.0.9", minimax_api_key="from-cli")
        s = app_config.resolve_settings(args, cfg, env={}, claude_token="")
        self.assertEqual(s.ip, "10.0.0.9")
        self.assertEqual(s.minimax_api_key, "from-cli")

    def test_env_beats_config(self):
        cfg = {"quota": {"api_key": "from-config"}}
        s = app_config.resolve_settings(make_args(), cfg,
                                        env={"MINIMAX_API_KEY": "from-env"},
                                        claude_token="")
        self.assertEqual(s.minimax_api_key, "from-env")

    def test_claude_settings_is_last_resort(self):
        s = app_config.resolve_settings(make_args(), {}, env={},
                                        claude_token="from-claude")
        self.assertEqual(s.minimax_api_key, "from-claude")

    def test_full_api_key_precedence(self):
        cfg = {"quota": {"api_key": "from-config"}}
        env = {"MINIMAX_API_KEY": "from-env"}
        args = make_args(minimax_api_key="from-cli")
        self.assertEqual(
            app_config.resolve_settings(args, cfg, env=env,
                                        claude_token="from-claude").minimax_api_key,
            "from-cli")
        self.assertEqual(
            app_config.resolve_settings(make_args(), cfg, env=env,
                                        claude_token="from-claude").minimax_api_key,
            "from-env")
        self.assertEqual(
            app_config.resolve_settings(make_args(), cfg, env={},
                                        claude_token="from-claude").minimax_api_key,
            "from-config")

    def test_no_quota_flag_disables(self):
        s = app_config.resolve_settings(make_args(no_minimax=True), {}, env={},
                                        claude_token="")
        self.assertFalse(s.minimax_enabled)

    def test_config_can_disable_quota(self):
        cfg = {"quota": {"enabled": False}}
        s = app_config.resolve_settings(make_args(), cfg, env={},
                                        claude_token="")
        self.assertFalse(s.minimax_enabled)

    def test_malformed_quota_section_is_ignored(self):
        cfg = {"quota": "not-a-dict"}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertTrue(s.minimax_enabled)
        self.assertEqual(s.minimax_api_key, "")

    def test_minimax_section_is_read(self):
        cfg = {"minimax": {"api_key": "mm-key",
                           "api_base": "https://api.minimaxi.com",
                           "poll_interval": 120}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.minimax_api_key, "mm-key")
        self.assertEqual(s.minimax_api_base, "https://api.minimaxi.com")
        self.assertEqual(s.minimax_poll_interval, 120)

    def test_legacy_quota_section_still_works(self):
        cfg = {"quota": {"api_key": "legacy-key"}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.minimax_api_key, "legacy-key")

    def test_minimax_section_wins_over_legacy_quota(self):
        cfg = {"minimax": {"api_key": "new"}, "quota": {"api_key": "old"}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.minimax_api_key, "new")

    def test_malformed_minimax_section_falls_back_to_legacy(self):
        cfg = {"minimax": "nope", "quota": {"api_key": "legacy"}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.minimax_api_key, "legacy")


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


class TestDeepSeekSettings(unittest.TestCase):
    def test_defaults(self):
        s = app_config.resolve_settings(make_args(), {}, env={}, claude_token="")
        self.assertTrue(s.deepseek_enabled)
        self.assertEqual(s.deepseek_api_base, "https://api.deepseek.com")
        self.assertEqual(s.deepseek_api_key, "")
        self.assertEqual(s.deepseek_poll_interval, 300)
        self.assertEqual(s.deepseek_alternate_interval, 5)
        self.assertEqual(s.deepseek_state_path, "")
        self.assertEqual(s.rotation_interval, 10)
        self.assertEqual(s.rotation_transition_frames, 5)

    def test_config_values(self):
        cfg = {"deepseek": {
            "enabled": True,
            "api_base": "https://example.com",
            "api_key": "ds-key",
            "poll_interval": 60,
            "alternate_interval": 3,
            "state_path": "/tmp/state.json",
        }, "rotation": {"interval": 20, "transition_frames": 3}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.deepseek_api_base, "https://example.com")
        self.assertEqual(s.deepseek_api_key, "ds-key")
        self.assertEqual(s.deepseek_poll_interval, 60)
        self.assertEqual(s.deepseek_alternate_interval, 3)
        self.assertEqual(s.deepseek_state_path, "/tmp/state.json")
        self.assertEqual(s.rotation_interval, 20)
        self.assertEqual(s.rotation_transition_frames, 3)

    def test_env_key_wins_over_config(self):
        cfg = {"deepseek": {"api_key": "from-config"}}
        s = app_config.resolve_settings(make_args(), cfg,
                                        env={"DEEPSEEK_API_KEY": "from-env"},
                                        claude_token="")
        self.assertEqual(s.deepseek_api_key, "from-env")

    def test_cli_key_wins_over_env(self):
        args = make_args(deepseek_api_key="from-cli")
        s = app_config.resolve_settings(args, {},
                                        env={"DEEPSEEK_API_KEY": "from-env"},
                                        claude_token="")
        self.assertEqual(s.deepseek_api_key, "from-cli")

    def test_claude_token_reused_when_base_url_is_deepseek(self):
        s = app_config.resolve_settings(
            make_args(), {}, env={}, claude_token="claude-token",
            claude_env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                        "ANTHROPIC_AUTH_TOKEN": "claude-token"})
        self.assertEqual(s.deepseek_api_key, "claude-token")

    def test_claude_token_ignored_for_other_providers(self):
        s = app_config.resolve_settings(
            make_args(), {}, env={}, claude_token="claude-token",
            claude_env={"ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
                        "ANTHROPIC_AUTH_TOKEN": "claude-token"})
        self.assertEqual(s.deepseek_api_key, "")

    def test_config_key_beats_claude_token(self):
        cfg = {"deepseek": {"api_key": "from-config"}}
        s = app_config.resolve_settings(
            make_args(), cfg, env={}, claude_token="claude-token",
            claude_env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com",
                        "ANTHROPIC_AUTH_TOKEN": "claude-token"})
        self.assertEqual(s.deepseek_api_key, "from-config")

    def test_no_deepseek_flag_disables(self):
        s = app_config.resolve_settings(make_args(no_deepseek=True), {},
                                        env={}, claude_token="")
        self.assertFalse(s.deepseek_enabled)

    def test_config_can_disable_deepseek(self):
        cfg = {"deepseek": {"enabled": False}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertFalse(s.deepseek_enabled)

    def test_malformed_deepseek_section_ignored(self):
        cfg = {"deepseek": "nope"}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertTrue(s.deepseek_enabled)
        self.assertEqual(s.deepseek_api_key, "")


class TestReadClaudeSettingsEnv(unittest.TestCase):
    def test_reads_env(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"env": {"ANTHROPIC_BASE_URL": "https://x",
                               "ANTHROPIC_AUTH_TOKEN": "t"}}, f)
        env = app_config.read_claude_settings_env(path)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://x")

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            app_config.read_claude_settings_env("/nonexistent/settings.json"), {})


if __name__ == "__main__":
    unittest.main()
