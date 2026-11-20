#!/usr/bin/env python3
"""
Cursor 套餐用量查询

余额来自 Cursor 客户端同款接口（未公开、可能变更）：
POST {api_base}/aiserver.v1.DashboardService/GetCurrentPeriodUsage

认证用本机已登录 Cursor 的 access token，不需要单独的 API key。
金额单位是美元。除网络请求和读取本地登录态外，解析都是纯函数。
"""

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import deepseek

DEFAULT_API_BASE = "https://api2.cursor.sh"
POLL_INTERVAL_DEFAULT = 300
ALTERNATE_INTERVAL_DEFAULT = 5
MAX_DOLLARS = 1_000_000.0
OAUTH_CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"

# 珊瑚 / 青柠，避开 MiniMax 的绿黄红青蓝紫和 DeepSeek 的品红白
USED_COLOR = (255, 110, 20)
REMAINING_COLOR = (170, 255, 40)

_AUTH_KEYS = ("cursorAuth/accessToken", "cursorAuth/refreshToken")
SAFE_STORAGE_PREFIX = "cursor-safe-storage:v1:"
_SAFE_STORAGE_SERVICE = "Cursor Safe Storage"
_SAFE_STORAGE_ACCOUNTS = ("Cursor Key", "Cursor")
_CHROMIUM_SALT = b"saltysalt"
_CHROMIUM_IV = b" " * 16


class CursorError(Exception):
    """用量查询或解析失败"""


class CursorAuthError(CursorError):
    """登录态失效，可以尝试用 refresh token 换新"""


def default_state_db():
    """Cursor 桌面端登录态数据库"""
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    else:
        base = os.path.join(home, ".config")
    return os.path.join(base, "Cursor", "User", "globalStorage", "state.vscdb")


def _dollars(value):
    """美分 → 美元。缺失或非数字返回 None"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number / 100.0


def _clamp_dollars(value):
    return max(0.0, min(MAX_DOLLARS, value))


def _percent(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(100.0, number))


def parse_period_usage(body):
    """解析 GetCurrentPeriodUsage 响应 → (已用, 剩余)，单位美元。

    没有美元额度、只有百分比时，返回已用百分比和剩余百分比。
    结构不符抛 CursorError。
    """
    if not isinstance(body, dict):
        raise CursorError("响应不是 JSON 对象")
    plan = body.get("planUsage")
    if not isinstance(plan, dict):
        raise CursorError("响应缺少 planUsage")

    limit = _dollars(plan.get("limit"))
    remaining = _dollars(plan.get("remaining"))
    included = _dollars(plan.get("includedSpend"))
    if limit is None and remaining is None and included is None:
        used_pct = _percent(plan.get("totalPercentUsed"))
        if used_pct is None:
            raise CursorError("响应缺少用量数据")
        return _clamp_dollars(used_pct), _clamp_dollars(100.0 - used_pct)

    if remaining is None and limit is not None and included is not None:
        remaining = limit - included
    if remaining is None:
        raise CursorError("响应缺少剩余额度")
    if included is None and limit is not None:
        included = limit - remaining
    if included is None:
        included = 0.0
    return _clamp_dollars(included), _clamp_dollars(remaining)


def _request(url, payload, headers, timeout, auth_error=False):
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
    except (AttributeError, TypeError, ValueError) as e:
        raise CursorError("Cursor API 地址非法: %s" % e) from e

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if auth_error and e.code in (401, 403):
            raise CursorAuthError("Cursor API HTTP %s" % e.code) from e
        raise CursorError("Cursor API HTTP %s" % e.code) from e
    except urllib.error.URLError as e:
        raise CursorError("Cursor API 网络错误: %s" % e.reason) from e
    except OSError as e:
        raise CursorError("Cursor API 请求失败: %s" % e) from e

    try:
        body = json.loads(raw)
    except ValueError as e:
        raise CursorError("Cursor API 返回的不是合法 JSON") from e
    if not isinstance(body, dict):
        raise CursorError("Cursor API 返回的不是 JSON 对象")
    return body


def fetch_period_usage(access_token, api_base=DEFAULT_API_BASE, timeout=10.0):
    """请求当前账期用量 → (已用, 剩余)。失败抛 CursorError / CursorAuthError"""
    if not access_token:
        raise CursorError("未登录 Cursor")
    url = api_base.rstrip("/") + "/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
    body = _request(
        url,
        {},
        {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
        timeout,
        auth_error=True,
    )
    return parse_period_usage(body)


def refresh_access_token(refresh_token, api_base=DEFAULT_API_BASE, timeout=10.0):
    """用 refresh token 换新的 access token。失败抛 CursorError"""
    if not refresh_token:
        raise CursorAuthError("没有 Cursor refresh token")
    url = api_base.rstrip("/") + "/oauth/token"
    body = _request(
        url,
        {
            "grant_type": "refresh_token",
            "client_id": OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        },
        {"Content-Type": "application/json"},
        timeout,
    )
    if body.get("shouldLogout"):
        raise CursorAuthError("Cursor 登录已失效，需要在 Cursor 里重新登录")
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise CursorAuthError("Cursor 刷新登录态失败")
    return token


def _pkcs7_unpad(data):
    if not data:
        raise CursorError("Cursor 登录态解密失败")
    pad = data[-1]
    if not isinstance(pad, int):
        pad = ord(pad)
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise CursorError("Cursor 登录态解密失败")
    return data[:-pad]


def unseal_token(value, password):
    """解开 Cursor 的 safeStorage 密文。明文 token 原样返回。

    新版 Cursor 把 access token 存成 cursor-safe-storage:v1: + base64(v10 密文)。
    密钥来自登录钥匙串里的 Cursor Safe Storage，算法是 Chromium 的
    PBKDF2-HMAC-SHA1 + AES-128-CBC。
    """
    if not isinstance(value, str) or not value.startswith(SAFE_STORAGE_PREFIX):
        return value
    if not password:
        raise CursorError("没有 Cursor Safe Storage 密码，无法解密登录态")
    try:
        blob = base64.b64decode(value[len(SAFE_STORAGE_PREFIX):], validate=True)
    except (ValueError, TypeError) as e:
        raise CursorError("Cursor 登录态格式无法识别") from e
    if not blob.startswith(b"v10"):
        raise CursorError("Cursor 登录态格式无法识别")
    key = hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), _CHROMIUM_SALT, 1003, dklen=16)
    proc = subprocess.run(
        [
            "openssl", "enc", "-aes-128-cbc", "-d",
            "-K", key.hex(), "-iv", _CHROMIUM_IV.hex(), "-nopad",
        ],
        input=blob[3:],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise CursorError("Cursor 登录态解密失败")
    try:
        return _pkcs7_unpad(proc.stdout).decode("utf-8")
    except UnicodeError as e:
        raise CursorError("Cursor 登录态解密失败") from e


def read_safe_storage_password():
    """从 macOS 登录钥匙串读取 Cursor Safe Storage 密码。失败抛 CursorError"""
    if sys.platform != "darwin":
        raise CursorError("当前系统无法解密 Cursor 登录态")
    last_error = ""
    for account in _SAFE_STORAGE_ACCOUNTS:
        proc = subprocess.run(
            [
                "security", "find-generic-password",
                "-s", _SAFE_STORAGE_SERVICE,
                "-a", account,
                "-w",
            ],
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.decode("utf-8", errors="replace").rstrip("\n")
        if proc.stderr:
            last_error = proc.stderr.decode("utf-8", errors="replace").strip()
    if last_error:
        raise CursorError("无法读取钥匙串中的 Cursor Safe Storage: %s" % last_error)
    raise CursorError("钥匙串里没有 Cursor Safe Storage")


def _connect_readonly(path):
    quoted = urllib.parse.quote(os.path.abspath(path))
    last_error = None
    for query in ("mode=ro&immutable=1", "mode=ro"):
        uri = "file:%s?%s" % (quoted, query)
        try:
            return sqlite3.connect(uri, uri=True, timeout=5)
        except sqlite3.Error as e:
            last_error = e
    if last_error is not None:
        raise last_error
    raise sqlite3.Error("无法打开 %s" % path)


def _read_raw_tokens(db_path):
    """读出数据库里的原始值，不解密。文件不存在或损坏时返回 ("", "")"""
    if not os.path.isfile(db_path):
        return "", ""
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error:
        return "", ""
    try:
        found = {}
        try:
            rows = conn.execute(
                "SELECT key, value FROM ItemTable WHERE key IN (?, ?)",
                _AUTH_KEYS,
            )
        except sqlite3.Error:
            return "", ""
        for key, value in rows:
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if isinstance(value, str):
                found[key] = value
    finally:
        conn.close()
    return found.get(_AUTH_KEYS[0], ""), found.get(_AUTH_KEYS[1], "")


def read_local_tokens(db_path=None, password=None):
    """从 Cursor 的 state.vscdb 读取 (access_token, refresh_token)。

    新版 Cursor 会把 token 加密存放。遇到密文时用钥匙串里的
    Cursor Safe Storage 解开。文件不存在时返回 ("", "")。
    不会把 token 写回数据库。
    """
    if not db_path:
        db_path = default_state_db()
    access, refresh = _read_raw_tokens(db_path)
    sealed = SAFE_STORAGE_PREFIX
    if access.startswith(sealed) or refresh.startswith(sealed):
        if password is None:
            password = read_safe_storage_password()
        if access.startswith(sealed):
            access = unseal_token(access, password)
        if refresh.startswith(sealed):
            refresh = unseal_token(refresh, password)
    if refresh == access:
        # 两个字段是同一份密文时，没有可用的 refresh token
        refresh = ""
    return access, refresh


def compose_page(used, remaining):
    """(已用, 剩余) → (mode, [已用串, 剩余串])，布局规则与 DeepSeek 页相同"""
    return deepseek.compose_page(used, remaining)


def render_page(mode, texts, index=0):
    """渲染 Cursor 页。左 = 本周期已用（珊瑚），右 = 剩余额度（青柠）"""
    return deepseek.render_page(
        mode, texts, index,
        left_color=USED_COLOR,
        right_color=REMAINING_COLOR,
    )
