#!/usr/bin/env python3
"""
DeepSeek 余额查询与今日消费追踪

余额来自官方接口：GET {api_base}/user/balance
今日消费 = 当天起点余额 - 当前余额（官方没有公开的消费查询接口）

除 fetch_balance() 与 SpendTracker 的文件读写外，全部是纯函数。
"""

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://api.deepseek.com"
POLL_INTERVAL_DEFAULT = 300        # 余额轮询间隔（秒）
ALTERNATE_INTERVAL_DEFAULT = 5     # 轮流模式下的子页切换间隔（秒）
MAX_BALANCE = 10_000_000.0         # 余额上限，超出按上限处理

# 设备几何
ROWS, COLS = 5, 20
USABLE_WIDTH = COLS - 1            # col19 留给实例标记

# 配色：品红 / 白，与 MiniMax 页的绿黄红青蓝紫完全错开
SPEND_COLOR = (255, 0, 160)
BALANCE_COLOR = (235, 235, 235)
BLACK = (0, 0, 0)


class DeepSeekError(Exception):
    """余额查询或解析失败"""


def _clamp_balance(value):
    return max(0.0, min(MAX_BALANCE, value))


def parse_balance(body):
    """解析 /user/balance 响应体 → 余额（float）。结构不符抛 DeepSeekError"""
    if not isinstance(body, dict):
        raise DeepSeekError("响应不是 JSON 对象")

    infos = body.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise DeepSeekError("响应缺少 balance_infos 数据")

    entry = None
    for item in infos:
        if isinstance(item, dict) and item.get("currency") == "CNY":
            entry = item
            break
    if entry is None:
        entry = infos[0]
    if not isinstance(entry, dict):
        raise DeepSeekError("balance_infos 条目格式异常")

    raw = entry.get("total_balance")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as e:
        raise DeepSeekError("total_balance 不是数字: %r" % (raw,)) from e
    if value != value:  # NaN
        raise DeepSeekError("total_balance 是 NaN")

    return _clamp_balance(value)


def fetch_balance(api_key, api_base=DEFAULT_API_BASE, timeout=10.0):
    """请求 DeepSeek 余额接口 → float。任何失败都抛 DeepSeekError"""
    if not api_key:
        raise DeepSeekError("未配置 DeepSeek API key")

    try:
        url = api_base.rstrip("/") + "/user/balance"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + api_key,
                "Accept": "application/json",
            },
            method="GET",
        )
    except (AttributeError, TypeError, ValueError) as e:
        raise DeepSeekError("DeepSeek API 地址非法: %s" % e) from e

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise DeepSeekError("DeepSeek API HTTP %s" % e.code) from e
    except urllib.error.URLError as e:
        raise DeepSeekError("DeepSeek API 网络错误: %s" % e.reason) from e
    except OSError as e:
        raise DeepSeekError("DeepSeek API 请求失败: %s" % e) from e

    try:
        body = json.loads(raw)
    except ValueError as e:
        raise DeepSeekError("DeepSeek API 返回的不是合法 JSON") from e

    return parse_balance(body)
