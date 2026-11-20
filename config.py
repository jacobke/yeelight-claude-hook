#!/usr/bin/env python3
"""
配置加载与优先级解析

优先级：命令行参数 > 环境变量 > config.json > 内置默认值

config.json 位于脚本同目录，默认已被 .gitignore 忽略；
config.json.example 是提交到仓库的模板。
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

from minimax import DEFAULT_API_BASE, POLL_INTERVAL_DEFAULT, TAKEOVER_DELAY_DEFAULT

import cursor_plan
import deepseek

DEFAULT_PORT = 55443
CLAUDE_SETTINGS_PATH = "~/.claude/settings.json"


@dataclass(frozen=True)
class Settings:
    """解析后的完整配置"""

    ip: Optional[str]
    port: int
    instance: int
    shared: int
    minimax_enabled: bool
    minimax_api_base: str
    minimax_api_key: str
    minimax_poll_interval: int
    takeover_delay: int
    deepseek_enabled: bool
    deepseek_api_base: str
    deepseek_api_key: str
    deepseek_poll_interval: int
    deepseek_alternate_interval: int
    deepseek_state_path: str
    cursor_enabled: bool
    cursor_api_base: str
    cursor_access_token: str
    cursor_state_db: str
    cursor_poll_interval: int
    cursor_alternate_interval: int
    rotation_interval: int
    rotation_transition_frames: int


def default_config_path():
    """脚本同目录的 config.json"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "config.json")


def load_config(path=None):
    """读取 JSON 配置文件；文件不存在或损坏时返回空字典"""
    if path is None:
        path = default_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def read_claude_settings_token(path=None):
    """从 ~/.claude/settings.json 读 ANTHROPIC_AUTH_TOKEN，作为 API key 的最后一级兜底"""
    if path is None:
        path = os.path.expanduser(CLAUDE_SETTINGS_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    env = data.get("env")
    if not isinstance(env, dict):
        return ""
    token = env.get("ANTHROPIC_AUTH_TOKEN")
    return token if isinstance(token, str) else ""


def read_claude_settings_env(path=None):
    """读取 ~/.claude/settings.json 的 env 字典；失败返回空字典"""
    if path is None:
        path = os.path.expanduser(CLAUDE_SETTINGS_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    env = data.get("env")
    return env if isinstance(env, dict) else {}


def _int_or_none(value):
    """把配置值转成 int；不可转的返回 None（表示「未配置」）"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_settings(args, config, env=None, claude_token="", claude_env=None):
    """把命令行参数、配置文件、环境变量合成一份 Settings"""
    env = os.environ if env is None else env

    # MiniMax 的配置段叫 minimax；旧版本叫 quota，保留兼容
    minimax_cfg = config.get("minimax")
    if not isinstance(minimax_cfg, dict):
        minimax_cfg = config.get("quota")
    if not isinstance(minimax_cfg, dict):
        minimax_cfg = {}

    api_key = (
        getattr(args, "minimax_api_key", None)
        or env.get("MINIMAX_API_KEY")
        or minimax_cfg.get("api_key")
        or claude_token
        or ""
    )

    ip = getattr(args, "ip", None) or config.get("ip") or None

    port = _int_or_none(getattr(args, "port", None))
    if port is None:
        port = _int_or_none(config.get("port"))
    if port is None:
        port = DEFAULT_PORT

    instance = _int_or_none(getattr(args, "instance", None))
    if instance is None:
        instance = _int_or_none(config.get("instance"))
    if instance is None:
        instance = 0

    shared = _int_or_none(getattr(args, "shared", None))
    if shared is None:
        shared = _int_or_none(config.get("shared"))
    if shared is None:
        shared = 1

    api_base = (
        getattr(args, "minimax_api_base", None)
        or minimax_cfg.get("api_base")
        or DEFAULT_API_BASE
    )

    poll_interval = _int_or_none(getattr(args, "minimax_interval", None))
    if poll_interval is None:
        poll_interval = _int_or_none(minimax_cfg.get("poll_interval"))
    if poll_interval is None:
        poll_interval = POLL_INTERVAL_DEFAULT

    takeover_delay = _int_or_none(minimax_cfg.get("takeover_delay"))
    if takeover_delay is None:
        takeover_delay = TAKEOVER_DELAY_DEFAULT

    if getattr(args, "no_minimax", False):
        minimax_enabled = False
    elif "enabled" in minimax_cfg:
        minimax_enabled = bool(minimax_cfg["enabled"])
    else:
        minimax_enabled = True

    ds_cfg = config.get("deepseek")
    if not isinstance(ds_cfg, dict):
        ds_cfg = {}
    rot_cfg = config.get("rotation")
    if not isinstance(rot_cfg, dict):
        rot_cfg = {}

    deepseek_api_key = (
        getattr(args, "deepseek_api_key", None)
        or env.get("DEEPSEEK_API_KEY")
        or ds_cfg.get("api_key")
        or ""
    )
    if not deepseek_api_key and isinstance(claude_env, dict):
        base_url = claude_env.get("ANTHROPIC_BASE_URL") or ""
        if "deepseek" in str(base_url).lower():
            deepseek_api_key = claude_env.get("ANTHROPIC_AUTH_TOKEN") or ""

    deepseek_api_base = (
        getattr(args, "deepseek_api_base", None)
        or ds_cfg.get("api_base")
        or deepseek.DEFAULT_API_BASE
    )

    deepseek_poll_interval = _int_or_none(ds_cfg.get("poll_interval"))
    if deepseek_poll_interval is None:
        deepseek_poll_interval = deepseek.POLL_INTERVAL_DEFAULT

    deepseek_alternate_interval = _int_or_none(ds_cfg.get("alternate_interval"))
    if deepseek_alternate_interval is None:
        deepseek_alternate_interval = deepseek.ALTERNATE_INTERVAL_DEFAULT

    deepseek_state_path = ds_cfg.get("state_path") or ""

    rotation_interval = _int_or_none(getattr(args, "rotation_interval", None))
    if rotation_interval is None:
        rotation_interval = _int_or_none(rot_cfg.get("interval"))
    if rotation_interval is None:
        rotation_interval = 10

    transition_frames = _int_or_none(getattr(args, "transition_frames", None))
    if transition_frames is None:
        transition_frames = _int_or_none(rot_cfg.get("transition_frames"))
    if transition_frames is None:
        transition_frames = 3
    transition_frames = max(0, transition_frames)

    if getattr(args, "no_deepseek", False):
        deepseek_enabled = False
    elif "enabled" in ds_cfg:
        deepseek_enabled = bool(ds_cfg["enabled"])
    else:
        deepseek_enabled = True

    cursor_cfg = config.get("cursor")
    if not isinstance(cursor_cfg, dict):
        cursor_cfg = {}

    cursor_access_token = (
        getattr(args, "cursor_access_token", None)
        or env.get("CURSOR_ACCESS_TOKEN")
        or cursor_cfg.get("access_token")
        or ""
    )
    cursor_api_base = (
        getattr(args, "cursor_api_base", None)
        or cursor_cfg.get("api_base")
        or cursor_plan.DEFAULT_API_BASE
    )
    cursor_state_db = cursor_cfg.get("state_db") or ""

    cursor_poll_interval = _int_or_none(cursor_cfg.get("poll_interval"))
    if cursor_poll_interval is None:
        cursor_poll_interval = cursor_plan.POLL_INTERVAL_DEFAULT

    cursor_alternate_interval = _int_or_none(cursor_cfg.get("alternate_interval"))
    if cursor_alternate_interval is None:
        cursor_alternate_interval = cursor_plan.ALTERNATE_INTERVAL_DEFAULT

    if getattr(args, "no_cursor", False):
        cursor_enabled = False
    elif "enabled" in cursor_cfg:
        cursor_enabled = bool(cursor_cfg["enabled"])
    else:
        cursor_enabled = False

    return Settings(
        ip=ip,
        port=port,
        instance=instance,
        shared=shared,
        minimax_enabled=minimax_enabled,
        minimax_api_base=api_base,
        minimax_api_key=api_key,
        minimax_poll_interval=poll_interval,
        takeover_delay=takeover_delay,
        deepseek_enabled=deepseek_enabled,
        deepseek_api_base=deepseek_api_base,
        deepseek_api_key=deepseek_api_key,
        deepseek_poll_interval=deepseek_poll_interval,
        deepseek_alternate_interval=deepseek_alternate_interval,
        deepseek_state_path=deepseek_state_path,
        cursor_enabled=cursor_enabled,
        cursor_api_base=cursor_api_base,
        cursor_access_token=cursor_access_token,
        cursor_state_db=cursor_state_db,
        cursor_poll_interval=cursor_poll_interval,
        cursor_alternate_interval=cursor_alternate_interval,
        rotation_interval=rotation_interval,
        rotation_transition_frames=transition_frames,
    )
