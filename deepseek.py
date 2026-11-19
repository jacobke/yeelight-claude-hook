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

# 3x5 字形（row 0 = 顶部）；小数点用 1 列宽
GLYPHS = {
    "0": [[1, 1, 1], [1, 0, 1], [1, 0, 1], [1, 0, 1], [1, 1, 1]],
    "1": [[0, 1, 0], [1, 1, 0], [0, 1, 0], [0, 1, 0], [1, 1, 1]],
    "2": [[1, 1, 1], [0, 0, 1], [1, 1, 1], [1, 0, 0], [1, 1, 1]],
    "3": [[1, 1, 1], [0, 0, 1], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "4": [[1, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1], [0, 0, 1]],
    "5": [[1, 1, 1], [1, 0, 0], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "6": [[1, 1, 1], [1, 0, 0], [1, 1, 1], [1, 0, 1], [1, 1, 1]],
    "7": [[1, 1, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1]],
    "8": [[1, 1, 1], [1, 0, 1], [1, 1, 1], [1, 0, 1], [1, 1, 1]],
    "9": [[1, 1, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    ".": [[0], [0], [0], [0], [1]],
    "K": [[1, 0, 1], [1, 0, 1], [1, 1, 0], [1, 0, 1], [1, 0, 1]],
    "M": [[1, 0, 1], [1, 1, 1], [1, 0, 1], [1, 0, 1], [1, 0, 1]],
}


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


def _round_half_up(value):
    """四舍五入。Python 内置 round() 是银行家舍入（12.5 → 12），金额显示不能用它"""
    return int(value + 0.5)


def format_amount(value, allow_decimal=True):
    """金额 → 数字字符串。value < 10 且允许小数时保留 1 位小数"""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return "0"
    if value != value:  # NaN
        return "0"
    if value < 0:
        value = 0.0
    if allow_decimal and value < 10:
        return "%.1f" % value
    return "%d" % _round_half_up(value)


def abbreviate(value):
    """大额缩写：< 1 万取整，1 万~100 万用 K（不带小数），>= 100 万用 M（1 位小数）"""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return "0"
    if value != value or value < 0:
        value = 0.0
    if value < 10000:
        return "%d" % _round_half_up(value)
    if value < 1000000:
        return "%dK" % _round_half_up(value / 1000.0)
    return "%.1fM" % (value / 1000000.0)


def text_width(text):
    """数字串占用的列数：数字 3 列、小数点 1 列、字符间距 1 列"""
    if not text:
        return 0
    return sum(1 if ch == "." else 3 for ch in text) + (len(text) - 1)


def _fits_side(left, right):
    return text_width(left) + 1 + text_width(right) <= USABLE_WIDTH


def compose_page(spend, balance):
    """把两个金额组合成一页 → (mode, [消费串, 余额串])

    mode == "side"      两段并排
    mode == "alternate" 同一页内轮流显示
    """
    spend_str = format_amount(spend, allow_decimal=True)
    balance_str = format_amount(balance, allow_decimal=False)
    if _fits_side(spend_str, balance_str):
        return "side", [spend_str, balance_str]

    spend_str = format_amount(spend, allow_decimal=False)
    if _fits_side(spend_str, balance_str):
        return "side", [spend_str, balance_str]

    abbreviated = abbreviate(balance)
    if _fits_side(spend_str, abbreviated):
        return "side", [spend_str, abbreviated]

    # 轮流模式：各自占满整行，保留小数；单个数太长时缩写
    spend_alt = format_amount(spend, allow_decimal=True)
    if text_width(spend_alt) > USABLE_WIDTH:
        spend_alt = abbreviate(spend)
    balance_alt = format_amount(balance, allow_decimal=False)
    if text_width(balance_alt) > USABLE_WIDTH:
        balance_alt = abbreviate(balance)
    return "alternate", [spend_alt, balance_alt]


def _draw_text(grid, text, col0, color):
    """从 col0 开始，把 text 画在 5 行的垂直居中位置"""
    col = col0
    for ch in text:
        glyph = GLYPHS.get(ch)
        if glyph is None:
            col += 4
            continue
        width = len(glyph[0])
        for row_idx, row_data in enumerate(glyph):
            phys_row = ROWS - 1 - row_idx
            for bit_idx, value in enumerate(row_data):
                if not value:
                    continue
                px_col = col + bit_idx
                if 0 <= px_col < COLS:
                    grid[phys_row * COLS + px_col] = color
        col += width + 1


def render_page(mode, texts, index=0):
    """渲染 DeepSeek 页 → 100 个 (r, g, b) 像素

    mode == "side"       texts[0] 品红居左、texts[1] 白色居右，中间 1 列分隔
    mode == "alternate"  只显示 texts[index]，index 0 = 品红消费，1 = 白余额
    """
    grid = [BLACK] * (ROWS * COLS)

    if mode == "alternate":
        text = texts[index] if 0 <= index < len(texts) else ""
        if not text:
            return grid
        color = SPEND_COLOR if index == 0 else BALANCE_COLOR
        start = (USABLE_WIDTH - text_width(text)) // 2
        _draw_text(grid, text, start, color)
        return grid

    left = texts[0] if texts else ""
    right = texts[1] if len(texts) > 1 else ""
    left_w = text_width(left)
    right_w = text_width(right)
    total = left_w + (1 + right_w if right else 0)
    start = (USABLE_WIDTH - total) // 2
    if left:
        _draw_text(grid, left, start, SPEND_COLOR)
    if right:
        _draw_text(grid, right, start + left_w + 1, BALANCE_COLOR)
    return grid
