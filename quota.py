#!/usr/bin/env python3
"""
MiniMax Token Plan 配额查询与进度条渲染

只依赖标准库。除 fetch_quota() 外全部是纯函数，不触碰 socket 与设备，
可以直接单元测试。

接口: GET {api_base}/v1/token_plan/remains
      Authorization: Bearer <api_key>

Token Plan 返回的是「剩余百分比」形态，*_total_count / *_usage_count 恒为 0，
不能用计数算比例。
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_API_BASE = "https://api.minimaxi.com"   # 国内站；国际站为 https://api.minimax.io
POLL_INTERVAL_DEFAULT = 300                      # 轮询间隔（秒）
TAKEOVER_DELAY_DEFAULT = 20                      # 效果结束后延迟多久接管屏幕（秒）

# 设备几何：5 行 × 20 列
ROWS, COLS = 5, 20
BAR_WIDTH = 19          # 条占 col0..col18；col19 留给实例标记
ROW_TOP = (4, 3)        # 5 小时条占的物理行（row4 = 顶）
ROW_BOTTOM = (1, 0)     # 周条占的物理行

# 配色
GREEN = (0, 255, 120)
YELLOW = (255, 200, 0)
RED = (255, 40, 40)
TEAL = (0, 220, 200)
BLUE = (80, 140, 255)
PURPLE = (170, 80, 255)
BLACK = (0, 0, 0)

# 色阶：(阈值, 颜色)，取第一个满足 pct >= 阈值 的颜色
WARM_RAMP = ((50, GREEN), (20, YELLOW), (0, RED))     # 5 小时窗口
COOL_RAMP = ((50, TEAL), (20, BLUE), (0, PURPLE))     # 周窗口

# 5 小时滚动窗口的时长（毫秒）
INTERVAL_WINDOW_MS = 5 * 3600 * 1000

# 中间那行的「重置倒计时」渐变色阶：(位置 0..1, 颜色)
# 蓝 → 青 → 绿 → 黄 → 橙：越接近重置，右边越长、整行越暖
RESET_STOPS = (
    (0.00, (40, 80, 220)),    # 蓝
    (0.30, (0, 200, 200)),    # 青
    (0.55, (0, 220, 100)),    # 绿
    (0.80, (230, 200, 0)),    # 黄
    (1.00, (255, 80, 0)),     # 橙
)

# 中间那行的「轨道」：还没走到的部分用暗灰常亮，让整行看起来是完整的
RESET_TRACK = (36, 36, 36)


class QuotaError(Exception):
    """配额查询或解析失败"""


@dataclass(frozen=True)
class QuotaSnapshot:
    """某一时刻的配额快照"""

    interval_pct: int       # 5 小时滚动窗口剩余百分比，0..100
    weekly_pct: int         # 周窗口剩余百分比，0..100
    interval_reset_at: int = 0   # 5 小时窗口重置时间（epoch ms）
    weekly_reset_at: int = 0     # 周窗口重置时间（epoch ms）

    def differs_from(self, other):
        """只比较百分比 —— 重置时间变化不必触发重绘"""
        if other is None:
            return True
        return (self.interval_pct != other.interval_pct
                or self.weekly_pct != other.weekly_pct)


def _clamp_pct(value):
    """把接口返回的百分比规整成 0..100 的整数；非数字按 0 处理"""
    if isinstance(value, bool):
        return 0
    try:
        pct = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(100, pct))


def _to_int(value):
    """把接口返回的整数规整为 int；非数字/不可转的返回 0"""
    if isinstance(value, bool):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def parse_remains(body):
    """解析 /v1/token_plan/remains 的响应体 → QuotaSnapshot。结构不符抛 QuotaError"""
    if not isinstance(body, dict):
        raise QuotaError("响应不是 JSON 对象")

    base_resp = body.get("base_resp")
    if not isinstance(base_resp, dict):
        raise QuotaError("响应缺少 base_resp")
    status = base_resp.get("status_code")
    if isinstance(status, bool):
        # bool 不是合法的状态码：True/False 一律当错误，避免 False 被当成 0 成功
        status = -1
    elif not isinstance(status, int):
        try:
            f = float(status)
            # 只有整数值的浮点才算合法状态码，0.4 这类截断成 0 等于放行畸形响应
            status = int(f) if f.is_integer() else -1
        except (TypeError, ValueError, OverflowError):
            status = -1
    if status != 0:
        raise QuotaError("MiniMax API 错误: %s (status_code=%s)"
                         % (base_resp.get("status_msg", ""), status))

    entries = body.get("model_remains")
    if not isinstance(entries, list) or not entries:
        raise QuotaError("响应缺少 model_remains 数据")

    entry = None
    for item in entries:
        if isinstance(item, dict) and item.get("model_name") == "general":
            entry = item
            break
    if entry is None:
        # 没有 general 就取第一条「可用」的条目（跳过非 dict 的垃圾数据）
        for item in entries:
            if isinstance(item, dict):
                entry = item
                break
    if not isinstance(entry, dict):
        raise QuotaError("model_remains 条目格式异常")

    return QuotaSnapshot(
        interval_pct=_clamp_pct(entry.get("current_interval_remaining_percent")),
        weekly_pct=_clamp_pct(entry.get("current_weekly_remaining_percent")),
        interval_reset_at=_to_int(entry.get("end_time")),
        weekly_reset_at=_to_int(entry.get("weekly_end_time")),
    )


def _dim(color, factor=0.3):
    """把颜色按比例压暗，用于「耗尽」时保留的暗点"""
    return tuple(int(c * factor) for c in color)


def _gradient_color(pos):
    """按位置 0..1 在 RESET_STOPS 上取渐变色"""
    pos = max(0.0, min(1.0, pos))
    for i in range(len(RESET_STOPS) - 1):
        p0, c0 = RESET_STOPS[i]
        p1, c1 = RESET_STOPS[i + 1]
        if pos <= p1:
            span = p1 - p0
            t = 0.0 if span == 0 else (pos - p0) / span
            return tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
    return RESET_STOPS[-1][1]


def reset_progress_pct(reset_at_ms, now_ms=None, window_ms=INTERVAL_WINDOW_MS):
    """5 小时窗口「已走过」的百分比（0..100）：0 = 刚重置，100 = 即将重置。

    没有重置时间（缺失 / 非法）时返回 None，表示这一行不画。
    """
    try:
        reset_at_ms = int(reset_at_ms)
    except (TypeError, ValueError, OverflowError):
        return None
    if reset_at_ms <= 0:
        return None
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    elapsed = window_ms - (reset_at_ms - now_ms)
    pct = int(elapsed * 100.0 / window_ms)
    return max(0, min(100, pct))


def reset_fill_columns(reset_pct):
    """重置倒计时行应亮的列数（1..BAR_WIDTH）；reset_pct 为 None 时返回 None"""
    if reset_pct is None:
        return None
    pct = _clamp_pct(reset_pct)
    filled = int(BAR_WIDTH * pct / 100 + 0.5)
    return max(1, filled)


def level_color(pct, ramp):
    """按色阶取颜色：ramp 是 ((阈值, 颜色), ...) 的序列"""
    pct = max(0, min(100, int(pct)))
    for threshold, color in ramp:
        if pct >= threshold:
            return color
    return ramp[-1][1]


def render_bar(interval_pct, weekly_pct, reset_pct=None):
    """渲染配额条 → 100 个 (r, g, b) 像素

    布局（物理行，row4 = 顶）：
        row4 ┐
        row3 ┘ 5 小时条（2px 厚，19 列）
        row2   重置倒计时（1px，渐变：蓝→青→绿→黄→橙；col19 留给实例标记）
        row1 ┐
        row0 ┘ 周条（2px 厚，19 列）

    reset_pct 为 None 时 row2 保持全黑。
    """
    grid = [BLACK] * (ROWS * COLS)

    def draw(rows, pct, ramp):
        pct = _clamp_pct(pct)
        color = level_color(pct, ramp)
        filled = int(BAR_WIDTH * pct / 100 + 0.5)
        # 只要还剩一点就至少亮一格：否则 1%/2% 会和「已耗尽」一样全黑，
        # 恰好在最需要信息的时刻丢掉信息
        if pct > 0 and filled < 1:
            filled = 1
        elif pct == 0:
            # 耗尽：保留一个压暗的告警色点 —— 全黑会让人以为功能坏了
            filled = 1
            color = _dim(color)
        for row in rows:
            for col in range(BAR_WIDTH):
                if col < filled:
                    grid[row * COLS + col] = color

    draw(ROW_TOP, interval_pct, WARM_RAMP)
    draw(ROW_BOTTOM, weekly_pct, COOL_RAMP)

    filled = reset_fill_columns(reset_pct)
    if filled is not None:
        # 整行 19 格常亮：走过的部分走渐变色，没走到的是暗灰轨道
        for col in range(BAR_WIDTH):
            if col < filled:
                pos = col / float(BAR_WIDTH - 1)
                grid[2 * COLS + col] = _gradient_color(pos)
            else:
                grid[2 * COLS + col] = RESET_TRACK

    return grid


def fetch_quota(api_key, api_base=DEFAULT_API_BASE, timeout=10.0):
    """请求 MiniMax 配额接口 → QuotaSnapshot。任何失败都抛 QuotaError"""
    if not api_key:
        raise QuotaError("未配置 MiniMax API key")

    try:
        url = api_base.rstrip("/") + "/v1/token_plan/remains"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            method="GET",
        )
    except (AttributeError, TypeError, ValueError) as e:
        # api_base 配错（不是字符串 / URL 格式非法）也要变成 QuotaError
        raise QuotaError("MiniMax API 地址非法: %s" % e) from e

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise QuotaError("MiniMax API HTTP %s" % e.code) from e
    except urllib.error.URLError as e:
        raise QuotaError("MiniMax API 网络错误: %s" % e.reason) from e
    except OSError as e:
        raise QuotaError("MiniMax API 请求失败: %s" % e) from e

    try:
        body = json.loads(raw)
    except ValueError as e:
        raise QuotaError("MiniMax API 返回的不是合法 JSON") from e

    return parse_remains(body)
