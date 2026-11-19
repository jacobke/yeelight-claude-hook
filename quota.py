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
    try:
        pct = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, pct))


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_remains(body):
    """解析 /v1/token_plan/remains 的响应体 → QuotaSnapshot。结构不符抛 QuotaError"""
    if not isinstance(body, dict):
        raise QuotaError("响应不是 JSON 对象")

    base_resp = body.get("base_resp")
    if not isinstance(base_resp, dict):
        raise QuotaError("响应缺少 base_resp")
    status = base_resp.get("status_code")
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
        entry = entries[0]
    if not isinstance(entry, dict):
        raise QuotaError("model_remains 条目格式异常")

    return QuotaSnapshot(
        interval_pct=_clamp_pct(entry.get("current_interval_remaining_percent")),
        weekly_pct=_clamp_pct(entry.get("current_weekly_remaining_percent")),
        interval_reset_at=_to_int(entry.get("end_time")),
        weekly_reset_at=_to_int(entry.get("weekly_end_time")),
    )
