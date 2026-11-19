# MiniMax Token Plan 余量进度条 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Yeelight Cube Lite（5×20 点阵）上常驻显示 MiniMax Token Plan 的剩余配额：上 2 行是 5 小时滚动窗口的进度条，下 2 行是周窗口的进度条，颜色随余量从绿→黄→红 / 青→蓝→紫变化。

**Architecture:** daemon 内置一个配额线程常驻轮询 MiniMax 接口（默认 5 分钟一次），空闲时把配额条画到设备上，有 hook 效果运行时让位、效果结束后接管。MiniMax 客户端与像素渲染抽成独立模块 `quota.py`（纯函数，可单测），配置加载与多级优先级抽成 `config.py`。daemon 是唯一持有设备长连接的进程，因此由它统一调度「谁占屏幕」，避免竞态。

**Tech Stack:** Python 3（标准库 `urllib` / `json` / `dataclasses` / `unittest`，**不引入第三方依赖**）；Yeelight LAN 协议（TCP 55443，JSON-RPC，FX direct 模式 + `update_leds` base64 像素）。

**设计依据:** `docs/superpowers/specs/2026-11-19-token-plan-progress-bar-design.md`

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `quota.py`（新增） | MiniMax 接口客户端 + 配额快照数据模型 + 配色 + 像素渲染。除 `fetch_quota()` 外全是纯函数，不碰 socket、不碰设备 |
| `config.py`（新增） | 读取 `config.json`、解析多级优先级（CLI > 环境变量 > 配置文件 > 默认值），产出 `Settings` |
| `yeelight-daemon.py`（修改） | 接入 `quota.py` / `config.py`；新增配额线程与调度状态；新增 `quota` 状态；新增 `--quota-*` 参数 |
| `yeelight-client.py`（修改） | `--state` 选项增加 `quota` |
| `tests/__init__.py`（新增） | 空文件，使 `tests` 成为包 |
| `tests/test_quota.py`（新增） | `quota.py` 的单元测试 |
| `tests/test_config.py`（新增） | `config.py` 的单元测试 |
| `tests/test_daemon.py`（新增） | daemon 调度逻辑与实例标记的集成测试 |
| `config.json.example`（修改） | 增加 `quota` 段 |
| `README.md` / `README_CN.md` / `EFFECTS.md`（修改） | 文档 |

### 与设计文档的偏差

设计文档 §11 把「配置加载」列在 `yeelight-daemon.py` 下。本计划改为独立的 `config.py`：
daemon 已有 582 行，配置的多级优先级解析逻辑有真实分支且需要测试，塞进去会让 daemon 继续膨胀。
`config.py` 只依赖 `quota.py` 里的三个常量，依赖方向单向、无环。

---

## 任务清单

| # | 任务 | 类型 |
|---|---|---|
| 1 | `quota.py`：数据模型 + 响应解析 | TDD |
| 2 | `quota.py`：配色 + 像素渲染 | TDD |
| 3 | `quota.py`：接口请求 | TDD |
| 4 | `config.py`：配置加载 + 优先级解析 | TDD |
| 5 | daemon 接入配置 + `--dry-run` | 集成 |
| 6 | daemon 配额线程 + 调度状态机 | TDD |
| 7 | daemon `quota` 状态 + client `--state quota` | 集成 |
| 8 | `config.json.example` + 三份文档 | 文档 |

---

### Task 1: `quota.py` 数据模型与响应解析

**Files:**
- Create: `quota.py`
- Create: `tests/__init__.py`
- Create: `tests/test_quota.py`

- [ ] **Step 1: 建测试包目录**

```bash
cd /path/to/yeelight-claude-hook
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 2: 写失败的测试**

创建 `tests/test_quota.py`：

```python
#!/usr/bin/env python3
"""quota.py 的单元测试"""

import json
import os
import sys
import unittest

# 让测试可以从任意 cwd 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quota  # noqa: E402


class TestParseRemains(unittest.TestCase):
    def test_normal_response(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 64,
                "current_weekly_remaining_percent": 23,
                "end_time": 1795073698120,
                "weekly_end_time": 1795070409914,
            }],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)
        self.assertEqual(snapshot.interval_reset_at, 1795073698120)
        self.assertEqual(snapshot.weekly_reset_at, 1795070409914)

    def test_non_zero_status_code_raises(self):
        body = {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_missing_base_resp_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains({"model_remains": []})

    def test_empty_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}, "model_remains": []}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_missing_model_remains_raises(self):
        body = {"base_resp": {"status_code": 0}}
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(body)

    def test_body_not_dict_raises(self):
        with self.assertRaises(quota.QuotaError):
            quota.parse_remains(["not", "a", "dict"])

    def test_prefers_general_entry(self):
        body = {
            "model_remains": [
                {"model_name": "MiniMax-M3", "current_interval_remaining_percent": 10,
                 "current_weekly_remaining_percent": 20},
                {"model_name": "general", "current_interval_remaining_percent": 64,
                 "current_weekly_remaining_percent": 23},
            ],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)

    def test_falls_back_to_first_entry(self):
        body = {
            "model_remains": [
                {"model_name": "MiniMax-M3", "current_interval_remaining_percent": 11,
                 "current_weekly_remaining_percent": 22},
            ],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 11)
        self.assertEqual(snapshot.weekly_pct, 22)

    def test_clamps_out_of_range_percent(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 150,
                "current_weekly_remaining_percent": -5,
            }],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 100)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_non_numeric_percent_becomes_zero(self):
        body = {
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": "n/a",
                "current_weekly_remaining_percent": None,
            }],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_pct, 0)
        self.assertEqual(snapshot.weekly_pct, 0)

    def test_missing_reset_time_defaults_zero(self):
        body = {
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 50,
                               "current_weekly_remaining_percent": 50}],
            "base_resp": {"status_code": 0},
        }
        snapshot = quota.parse_remains(body)
        self.assertEqual(snapshot.interval_reset_at, 0)
        self.assertEqual(snapshot.weekly_reset_at, 0)


class TestDiffersFrom(unittest.TestCase):
    def test_none_always_differs(self):
        self.assertTrue(quota.QuotaSnapshot(50, 50).differs_from(None))

    def test_same_percent_ignores_reset_time(self):
        a = quota.QuotaSnapshot(50, 20, 111, 222)
        b = quota.QuotaSnapshot(50, 20, 999, 888)
        self.assertFalse(a.differs_from(b))

    def test_changed_percent_differs(self):
        a = quota.QuotaSnapshot(50, 20)
        b = quota.QuotaSnapshot(49, 20)
        self.assertTrue(a.differs_from(b))

    def test_changed_weekly_differs(self):
        a = quota.QuotaSnapshot(50, 20)
        b = quota.QuotaSnapshot(50, 21)
        self.assertTrue(a.differs_from(b))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'quota'`

- [ ] **Step 4: 写最小实现**

创建 `quota.py`：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 15 tests OK

- [ ] **Step 6: 提交**

```bash
git add quota.py tests/__init__.py tests/test_quota.py
git commit -m "feat: add quota.py with MiniMax token plan response parsing"
```

---

### Task 2: `quota.py` 配色与像素渲染

**Files:**
- Modify: `quota.py`（追加函数）
- Modify: `tests/test_quota.py`（追加测试类）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_quota.py` 的 `if __name__ == "__main__":` 之前插入：

```python
class TestLevelColor(unittest.TestCase):
    def test_warm_ramp_boundaries(self):
        self.assertEqual(quota.level_color(100, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(50, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(49, quota.WARM_RAMP), quota.YELLOW)
        self.assertEqual(quota.level_color(20, quota.WARM_RAMP), quota.YELLOW)
        self.assertEqual(quota.level_color(19, quota.WARM_RAMP), quota.RED)
        self.assertEqual(quota.level_color(0, quota.WARM_RAMP), quota.RED)

    def test_cool_ramp_boundaries(self):
        self.assertEqual(quota.level_color(100, quota.COOL_RAMP), quota.TEAL)
        self.assertEqual(quota.level_color(50, quota.COOL_RAMP), quota.TEAL)
        self.assertEqual(quota.level_color(49, quota.COOL_RAMP), quota.BLUE)
        self.assertEqual(quota.level_color(20, quota.COOL_RAMP), quota.BLUE)
        self.assertEqual(quota.level_color(19, quota.COOL_RAMP), quota.PURPLE)
        self.assertEqual(quota.level_color(0, quota.COOL_RAMP), quota.PURPLE)

    def test_clamps_out_of_range(self):
        self.assertEqual(quota.level_color(150, quota.WARM_RAMP), quota.GREEN)
        self.assertEqual(quota.level_color(-10, quota.WARM_RAMP), quota.RED)


class TestRenderBar(unittest.TestCase):
    def test_returns_100_pixels(self):
        self.assertEqual(len(quota.render_bar(50, 50)), 100)

    def test_full_bars_fill_19_columns(self):
        grid = quota.render_bar(100, 100)
        for row in quota.ROW_TOP + quota.ROW_BOTTOM:
            for col in range(quota.BAR_WIDTH):
                self.assertNotEqual(grid[row * quota.COLS + col], quota.BLACK)

    def test_empty_bars_are_black(self):
        grid = quota.render_bar(0, 0)
        for row in quota.ROW_TOP + quota.ROW_BOTTOM:
            for col in range(quota.BAR_WIDTH):
                self.assertEqual(grid[row * quota.COLS + col], quota.BLACK)

    def test_half_fill_is_ten_columns(self):
        grid = quota.render_bar(50, 50)
        lit = sum(1 for col in range(quota.BAR_WIDTH)
                  if grid[quota.ROW_TOP[0] * quota.COLS + col] != quota.BLACK)
        self.assertEqual(lit, 10)

    def test_last_column_always_black(self):
        grid = quota.render_bar(100, 100)
        for row in range(quota.ROWS):
            self.assertEqual(grid[row * quota.COLS + quota.COLS - 1], quota.BLACK)

    def test_separator_row_is_black(self):
        grid = quota.render_bar(100, 100)
        for col in range(quota.COLS):
            self.assertEqual(grid[2 * quota.COLS + col], quota.BLACK)

    def test_rows_do_not_overlap(self):
        self.assertEqual(set(quota.ROW_TOP) & set(quota.ROW_BOTTOM), set())
        self.assertNotIn(2, quota.ROW_TOP)
        self.assertNotIn(2, quota.ROW_BOTTOM)

    def test_high_percent_uses_warm_and_cool_colors(self):
        grid = quota.render_bar(74, 24)
        self.assertEqual(grid[quota.ROW_TOP[0] * quota.COLS], quota.GREEN)
        self.assertEqual(grid[quota.ROW_BOTTOM[0] * quota.COLS], quota.BLUE)

    def test_low_percent_uses_red_and_purple(self):
        grid = quota.render_bar(12, 8)
        self.assertEqual(grid[quota.ROW_TOP[0] * quota.COLS], quota.RED)
        self.assertEqual(grid[quota.ROW_BOTTOM[0] * quota.COLS], quota.PURPLE)

    def test_unfilled_part_is_black(self):
        grid = quota.render_bar(74, 24)
        # 5h 74% → int(19*0.74+0.5) = 14 列填充，第 15 列起为黑
        row = quota.ROW_TOP[0]
        self.assertNotEqual(grid[row * quota.COLS + 13], quota.BLACK)
        self.assertEqual(grid[row * quota.COLS + 14], quota.BLACK)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: module 'quota' has no attribute 'level_color'`

- [ ] **Step 3: 写最小实现**

在 `quota.py` 末尾追加：

```python
def level_color(pct, ramp):
    """按色阶取颜色：ramp 是 ((阈值, 颜色), ...) 的序列"""
    pct = max(0, min(100, int(pct)))
    for threshold, color in ramp:
        if pct >= threshold:
            return color
    return ramp[-1][1]


def render_bar(interval_pct, weekly_pct):
    """渲染配额条 → 100 个 (r, g, b) 像素

    布局（物理行，row4 = 顶）：
        row4 ┐
        row3 ┘ 5 小时条（2px 厚，19 列）
        row2   分隔行（空，col19 留给实例标记）
        row1 ┐
        row0 ┘ 周条（2px 厚，19 列）
    """
    grid = [BLACK] * (ROWS * COLS)

    def draw(rows, pct, ramp):
        color = level_color(pct, ramp)
        pct = max(0, min(100, int(pct)))
        filled = int(BAR_WIDTH * pct / 100 + 0.5)
        for row in rows:
            for col in range(BAR_WIDTH):
                if col < filled:
                    grid[row * COLS + col] = color

    draw(ROW_TOP, interval_pct, WARM_RAMP)
    draw(ROW_BOTTOM, weekly_pct, COOL_RAMP)
    return grid
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 28 tests OK

- [ ] **Step 5: 目视验证渲染结果**

Run:
```bash
python3 - <<'EOF'
import quota
grid = quota.render_bar(74, 24)
for r in range(4, -1, -1):
    print("row%d |" % r + "".join("█" if grid[r*20+c] != quota.BLACK else "·" for c in range(20)) + "|")
EOF
```
Expected:
```
row4 |██████████████·····|
row3 |██████████████·····|
row2 |····················|
row1 |█████···············|
row0 |█████···············|
```

- [ ] **Step 6: 提交**

```bash
git add quota.py tests/test_quota.py
git commit -m "feat: add quota bar rendering with level-based colors"
```

---

### Task 3: `quota.py` 接口请求

**Files:**
- Modify: `quota.py`（追加 `fetch_quota`）
- Modify: `tests/test_quota.py`（追加测试类）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_quota.py` 的 `if __name__ == "__main__":` 之前插入：

```python
class FakeResponse:
    """模拟 urllib 的 HTTP 响应对象"""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchQuota(unittest.TestCase):
    def setUp(self):
        self._original_urlopen = quota.urllib.request.urlopen

    def tearDown(self):
        quota.urllib.request.urlopen = self._original_urlopen

    def test_requires_api_key(self):
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("")

    def test_network_failure_becomes_quota_error(self):
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy", api_base="http://127.0.0.1:9", timeout=1)

    def test_successful_fetch(self):
        payload = json.dumps({
            "model_remains": [{
                "model_name": "general",
                "current_interval_remaining_percent": 64,
                "current_weekly_remaining_percent": 23,
            }],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }).encode()

        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            return FakeResponse(payload)

        quota.urllib.request.urlopen = fake_urlopen
        snapshot = quota.fetch_quota("dummy-key")

        self.assertEqual(snapshot.interval_pct, 64)
        self.assertEqual(snapshot.weekly_pct, 23)
        self.assertEqual(captured["url"],
                         "https://api.minimaxi.com/v1/token_plan/remains")
        self.assertEqual(captured["auth"], "Bearer dummy-key")

    def test_trailing_slash_in_api_base_is_tolerated(self):
        payload = json.dumps({
            "model_remains": [{"model_name": "general",
                               "current_interval_remaining_percent": 10,
                               "current_weekly_remaining_percent": 20}],
            "base_resp": {"status_code": 0},
        }).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse(payload)

        quota.urllib.request.urlopen = fake_urlopen
        quota.fetch_quota("dummy-key", api_base="https://api.minimaxi.com/")
        self.assertEqual(captured["url"],
                         "https://api.minimaxi.com/v1/token_plan/remains")

    def test_invalid_json_becomes_quota_error(self):
        quota.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(b"not json")
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy-key")

    def test_business_error_becomes_quota_error(self):
        payload = json.dumps({
            "base_resp": {"status_code": 2049, "status_msg": "invalid api key"}
        }).encode()
        quota.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(payload)
        with self.assertRaises(quota.QuotaError):
            quota.fetch_quota("dummy-key")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: module 'quota' has no attribute 'fetch_quota'`

- [ ] **Step 3: 写最小实现**

在 `quota.py` 末尾追加：

```python
def fetch_quota(api_key, api_base=DEFAULT_API_BASE, timeout=10.0):
    """请求 MiniMax 配额接口 → QuotaSnapshot。任何失败都抛 QuotaError"""
    if not api_key:
        raise QuotaError("未配置 MiniMax API key")

    url = api_base.rstrip("/") + "/v1/token_plan/remains"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="GET",
    )

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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 34 tests OK

- [ ] **Step 5: 用真实接口验证一次**

Run:
```bash
python3 - <<'EOF'
import json, os, quota
token = json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"]["ANTHROPIC_AUTH_TOKEN"]
snap = quota.fetch_quota(token)
print("5h 剩余 %d%%  周剩余 %d%%" % (snap.interval_pct, snap.weekly_pct))
print("5h 重置:", snap.interval_reset_at, " 周重置:", snap.weekly_reset_at)
EOF
```
Expected: 打印两个百分比（0..100 之间），例如 `5h 剩余 62%  周剩余 22%`。

- [ ] **Step 6: 提交**

```bash
git add quota.py tests/test_quota.py
git commit -m "feat: add MiniMax token plan API client"
```

---

### Task 4: `config.py` 配置加载与优先级解析

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_config.py`：

```python
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

    def test_config_disable_applies_when_no_flag(self):
        cfg = {"quota": {"enabled": False}}
        s = app_config.resolve_settings(make_args(no_quota=False), cfg, env={},
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: 写最小实现**

创建 `config.py`：

```python
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

from quota import DEFAULT_API_BASE, POLL_INTERVAL_DEFAULT, TAKEOVER_DELAY_DEFAULT

DEFAULT_PORT = 55443
CLAUDE_SETTINGS_PATH = "~/.claude/settings.json"


@dataclass(frozen=True)
class Settings:
    """解析后的完整配置"""

    ip: Optional[str]
    port: int
    instance: int
    shared: int
    quota_enabled: bool
    api_base: str
    api_key: str
    poll_interval: int
    takeover_delay: int


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


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_settings(args, config, env=None, claude_token=""):
    """把命令行参数、配置文件、环境变量合成一份 Settings"""
    env = os.environ if env is None else env

    quota_cfg = config.get("quota")
    if not isinstance(quota_cfg, dict):
        quota_cfg = {}

    api_key = (
        getattr(args, "quota_api_key", None)
        or env.get("MINIMAX_API_KEY")
        or quota_cfg.get("api_key")
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
        getattr(args, "quota_api_base", None)
        or quota_cfg.get("api_base")
        or DEFAULT_API_BASE
    )

    poll_interval = _int_or_none(getattr(args, "quota_interval", None))
    if poll_interval is None:
        poll_interval = _int_or_none(quota_cfg.get("poll_interval"))
    if poll_interval is None:
        poll_interval = POLL_INTERVAL_DEFAULT

    takeover_delay = _int_or_none(quota_cfg.get("takeover_delay"))
    if takeover_delay is None:
        takeover_delay = TAKEOVER_DELAY_DEFAULT

    if getattr(args, "no_quota", False):
        quota_enabled = False
    elif "enabled" in quota_cfg:
        quota_enabled = bool(quota_cfg["enabled"])
    else:
        quota_enabled = True

    return Settings(
        ip=ip,
        port=port,
        instance=instance,
        shared=shared,
        quota_enabled=quota_enabled,
        api_base=api_base,
        api_key=api_key,
        poll_interval=poll_interval,
        takeover_delay=takeover_delay,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 51 tests OK

- [ ] **Step 5: 提交**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config loading with multi-level precedence"
```

---

### Task 5: daemon 接入配置 + `--dry-run`

**Files:**
- Modify: `yeelight-daemon.py`（import 区、`__init__`、`main`）

- [ ] **Step 1: 加 import**

在 `yeelight-daemon.py` 的 import 区（`import threading` 之后）加入：

```python
import config as app_config
import quota
```

- [ ] **Step 2: 改 `__init__` 签名与新增字段**

把 `YeelightDaemon.__init__` 整体替换为：

```python
    def __init__(self, ip, port=55443, instance=0, shared=1,
                 quota_enabled=False, api_base=quota.DEFAULT_API_BASE,
                 api_key="", poll_interval=quota.POLL_INTERVAL_DEFAULT,
                 takeover_delay=quota.TAKEOVER_DELAY_DEFAULT):
        self.ip = ip
        self.port = port
        self.instance = instance  # 实例编号 (0=不显示, 1-20=显示位置)
        self.shared = max(1, shared)  # 同时连接此设备的 daemon 数量，用于分摊命令配额
        self.sock = None
        self.running = True
        self.interrupted = False  # 效果中断标志
        self.effect_thread = None  # 当前效果线程
        self.command_count = 0
        self.last_command_time = 0
        self.lock = threading.Lock()  # 保护 socket 操作
        self.reader_thread = None  # 后台读取线程，防止设备 send buffer 填满导致假死
        # 命令间隔：默认 1 秒（每秒 1 命令 = 60/分钟）。
        # 共享模式下按 daemon 数量均分：shared=2 → 每 2 秒 1 命令（30/分钟）
        self.command_interval = float(self.shared)

        # ===== MiniMax 配额条 =====
        self.quota_enabled = quota_enabled and bool(api_key)
        self.api_base = api_base
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.takeover_delay = takeover_delay
        self.quota_thread = None            # 配额轮询线程
        self.last_snapshot = None          # 最近一次成功拉到的快照
        self.last_rendered = None          # 最近一次画到屏幕上的快照
        self.quota_needs_repaint = True    # 效果抢过屏幕后置位
        self.last_quota_fetch_at = 0.0     # 最近一次尝试拉取的时间戳
        self.last_effect_finished_at = time.time()  # 启动后立即允许显示配额条
```

- [ ] **Step 3: 改 `main` 的参数解析与配置解析**

把 `main()` 整体替换为：

```python
def main():
    parser = argparse.ArgumentParser(description="Yeelight Daemon")
    parser.add_argument("--ip", default=None, help="设备 IP 地址")
    parser.add_argument("--port", type=int, default=None, help="设备端口 (默认 55443)")
    parser.add_argument("--instance", type=int, default=None,
                        help="Instance number (1-5) for pixel marking, 0=disabled")
    parser.add_argument("--shared", type=int, default=None,
                        help="Number of daemons sharing this device (default 1). "
                             "Each daemon will limit to 60/shared commands per minute.")
    parser.add_argument("--config", default=None,
                        help="配置文件路径 (默认: 脚本同目录的 config.json)")
    parser.add_argument("--quota-api-key", default=None, help="MiniMax API key")
    parser.add_argument("--quota-api-base", default=None, help="MiniMax API 域名")
    parser.add_argument("--quota-interval", type=int, default=None,
                        help="配额轮询间隔（秒，默认 300）")
    parser.add_argument("--no-quota", action="store_true", help="关闭配额条功能")
    parser.add_argument("--dry-run", action="store_true",
                        help="打印解析后的配置后退出，不连接设备")
    args = parser.parse_args()

    cfg = app_config.load_config(args.config)
    settings = app_config.resolve_settings(
        args, cfg, claude_token=app_config.read_claude_settings_token())

    if args.dry_run:
        data = dataclasses.asdict(settings)
        key = data.get("api_key") or ""
        if key:
            # 打码，避免把完整 key 留在终端记录里
            data["api_key"] = "%s...%s" % (key[:6], key[-4:])
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if not settings.ip:
        print("Error: device IP not specified (use --ip or config.json)",
              file=sys.stderr)
        return 1

    daemon = YeelightDaemon(
        settings.ip, settings.port, settings.instance, settings.shared,
        settings.quota_enabled, settings.api_base, settings.api_key,
        settings.poll_interval, settings.takeover_delay)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        daemon.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not daemon.connect():
        return 1

    daemon.activate_direct_mode()
    daemon.run_server()

    return 0
```

同时在 import 区加入 `import dataclasses`（放在 `import base64` 之后）。

- [ ] **Step 4: 验证 `--dry-run` 输出**

Run: `python3 yeelight-daemon.py --dry-run --ip 192.168.1.100 --instance 2`
Expected:
```json
{
  "ip": "192.168.1.100",
  "port": 55443,
  "instance": 2,
  "shared": 1,
  "quota_enabled": true,
  "api_base": "https://api.minimaxi.com",
  "api_key": "sk-cp-...Oz8Y",
  "poll_interval": 300,
  "takeover_delay": 20
}
```
（`api_key` 是打码后的值，前 6 位 + 后 4 位。中间是空的说明没解析到 key ——
那就去检查 `~/.claude/settings.json` 里的 `ANTHROPIC_AUTH_TOKEN`。）

- [ ] **Step 5: 验证没有 IP 时报错退出**

Run: `python3 yeelight-daemon.py --dry-run --ip ""` 应仍打印 JSON；
Run: `python3 yeelight-daemon.py` （不传 --ip，且本机无 config.json）
Expected: `Error: device IP not specified (use --ip or config.json)`，退出码 1

- [ ] **Step 6: 跑一遍已有测试确认没打破**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 51 tests OK

- [ ] **Step 7: 提交**

```bash
git add yeelight-daemon.py
git commit -m "feat: wire config loading and --dry-run into daemon"
```

---

### Task 6: daemon 配额线程与调度状态机

**Files:**
- Modify: `yeelight-daemon.py`（新增配额方法、修改 `run_effect`）
- Create: `tests/test_daemon.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_daemon.py`：

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: 'YeelightDaemon' object has no attribute 'quota_tick'`

- [ ] **Step 3: 写实现**

在 `yeelight-daemon.py` 的 `YeelightDaemon` 类中，`send_pixels_with_mark` 方法之后插入：

```python
    # ========================================================================
    # MiniMax 配额条
    # ========================================================================

    def quota_snapshot_if_available(self, now=None):
        """取当前可用的配额快照（带缓存）。

        缓存新鲜时直接复用；过期时请求接口。请求失败时返回上一次成功的快照
        （可能为 None），这样接口临时故障不会让画面消失。
        """
        if now is None:
            now = time.time()
        if (self.last_snapshot is not None
                and now - self.last_quota_fetch_at < self.poll_interval):
            return self.last_snapshot

        try:
            snapshot = quota.fetch_quota(self.api_key, self.api_base)
        except quota.QuotaError as e:
            print("Quota fetch failed: %s" % e, file=sys.stderr, flush=True)
            # 失败也要等一个轮询周期再重试
            self.last_quota_fetch_at = now
            return self.last_snapshot

        self.last_snapshot = snapshot
        self.last_quota_fetch_at = now
        return snapshot

    def quota_should_paint(self, now=None):
        """判断当前是否应该画一次配额条（不产生副作用）"""
        if not self.quota_enabled:
            return False
        if self.effect_thread and self.effect_thread.is_alive():
            return False
        if now is None:
            now = time.time()
        if now - self.last_effect_finished_at < self.takeover_delay:
            return False
        snapshot = self.quota_snapshot_if_available(now)
        if snapshot is None:
            return False
        return snapshot.differs_from(self.last_rendered) or self.quota_needs_repaint

    def paint_quota(self, snapshot):
        """接管屏幕并画出配额条"""
        grid = quota.render_bar(snapshot.interval_pct, snapshot.weekly_pct)
        # 接管序列：停掉设备端内置效果（complete 的绿色呼吸），回到 direct 模式
        self.send_command("stop_cf", [])
        self.send_command("set_power", ["on"])
        self.send_command("activate_fx_mode", [{"mode": "direct"}])
        self.send_pixels_with_mark(grid)
        self.last_rendered = snapshot
        self.quota_needs_repaint = False

    def quota_tick(self):
        """配额线程的一轮：判断并（必要时）绘制一次配额条。返回是否绘制了"""
        if not self.quota_should_paint():
            return False
        snapshot = self.quota_snapshot_if_available()
        if snapshot is None:
            return False
        self.paint_quota(snapshot)
        return True

    def quota_loop(self):
        """配额线程主循环"""
        while self.running:
            time.sleep(1)
            try:
                self.quota_tick()
            except Exception as e:
                print("Quota loop error: %s" % e, file=sys.stderr, flush=True)

    def start_quota_thread(self):
        """启动配额线程（未配置 API key 时不启动）"""
        if not self.quota_enabled:
            print("Quota meter disabled (no API key or --no-quota)",
                  file=sys.stderr, flush=True)
            return
        self.quota_thread = threading.Thread(target=self.quota_loop, daemon=True)
        self.quota_thread.start()
```

- [ ] **Step 4: 让效果与配额条正确交接**

把 `run_effect` 整体替换为（在原有逻辑外包一层 try/finally）：

```python
    def run_effect(self, state, duration=5.0):
        """运行效果（在独立线程中）"""
        self.interrupted = False  # 重置中断标志
        # 效果抢过了屏幕，回来后需要重画一次配额条
        self.quota_needs_repaint = True

        try:
            # 对于点阵效果，确保先进入 direct mode
            # complete 使用内置效果，不需要 direct mode
            if state not in ["complete", "off"]:
                self.send_command("stop_cf", [])  # 停止内置效果
                time.sleep(0.1)
                self.send_command("set_power", ["on"])
                time.sleep(0.1)
                self.send_command("activate_fx_mode", [{"mode": "direct"}])
                time.sleep(0.2)

            handlers = {
                "start": lambda: self.effect_start(duration),
                "thinking": lambda: self.effect_thinking(duration),
                "done": lambda: self.effect_done(),
                "wait": lambda: self.effect_wait(duration),
                "interrupt": lambda: self.effect_interrupt(),
                "complete": lambda: self.effect_complete(),
                "end": lambda: self.effect_end(duration),
                "off": lambda: self.effect_off(),
            }

            handler = handlers.get(state)
            if handler:
                handler()
        finally:
            # 记录效果结束时间，配额线程据此判断保护期
            self.last_effect_finished_at = time.time()
```

（`quota` 状态的 handler 与白名单在 Task 7 里一并加入，本任务不碰。）

- [ ] **Step 5: 启动配额线程**

在 `yeelight-daemon.py` 的 `main()` 中，把：

```python
    daemon.activate_direct_mode()
    daemon.run_server()
```

改成：

```python
    daemon.activate_direct_mode()
    daemon.start_quota_thread()
    daemon.run_server()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 63 tests OK

- [ ] **Step 7: 提交**

```bash
git add yeelight-daemon.py tests/test_daemon.py
git commit -m "feat: add quota thread and scheduling to daemon"
```

---

### Task 7: `quota` 状态与 client 支持

**Files:**
- Modify: `yeelight-daemon.py`（`effect_quota` 方法、`handle_command` 的状态白名单）
- Modify: `yeelight-client.py`（`--state` 选项）

- [ ] **Step 1: 把状态白名单提成模块级常量**

在 `yeelight-daemon.py` 的 `# 配置` 常量区（`ROWS, COLS = 5, 20` 之后）加入：

```python
# 所有可用的效果状态
VALID_STATES = [
    "start", "thinking", "done", "wait", "interrupt",
    "complete", "end", "off", "quota",
]
```

然后在 `handle_command` 中，把状态校验那一行：

```python
        if state not in ["start", "thinking", "done", "wait", "interrupt", "complete", "end", "off"]:
            return {"status": "error", "message": f"Unknown state: {state}"}
```

改成：

```python
        if state not in VALID_STATES:
            return {"status": "error", "message": f"Unknown state: {state}"}
```

- [ ] **Step 2: 加 `effect_quota` 方法**

在 `yeelight-daemon.py` 的 `effect_complete` 方法之后插入：

```python
    def effect_quota(self):
        """立即绘制一次配额条（调试 / 手动刷新用）"""
        snapshot = self.quota_snapshot_if_available()
        if snapshot is None:
            print("No quota data available", file=sys.stderr, flush=True)
            return
        self.paint_quota(snapshot)
```

- [ ] **Step 3: 在 `run_effect` 里接上 `quota` handler**

在 Task 6 改过的 `run_effect` 中，把 direct mode 的排除列表：

```python
            if state not in ["complete", "off"]:
```

改成：

```python
            if state not in ["complete", "off", "quota"]:
```

（`quota` 状态的接管序列由 `paint_quota` 自己负责，这里不要重复执行。）

并在 `handlers` 字典里追加一行：

```python
                "quota": lambda: self.effect_quota(),
```

- [ ] **Step 4: client 支持 `quota` 状态**

在 `yeelight-client.py` 中，把：

```python
    parser.add_argument("--state", "-s", required=True,
                        choices=['start', 'thinking', 'done', 'wait', 'interrupt', 'complete', 'end', 'off'])
```

改成：

```python
    parser.add_argument("--state", "-s", required=True,
                        choices=['start', 'thinking', 'done', 'wait', 'interrupt',
                                 'complete', 'end', 'off', 'quota'])
```

- [ ] **Step 5: 写 daemon 侧的测试**

在 `tests/test_daemon.py` 的 `if __name__ == "__main__":` 之前插入：

```python
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
```

`handle_command` 对未知状态在白名单检查后就直接返回，不会启动线程、也不访问任何实例
字段，所以用 `__new__` 造出来的空对象也能安全调用。

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 66 tests OK

- [ ] **Step 7: 真机验证**

先重启 daemon：

```bash
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
sleep 3
tail -20 /tmp/yeelight-daemon.log
```

Expected: 日志里没有异常；若配置了 API key，会看到配额线程启动。

然后手动触发一次：

```bash
python3 yeelight-client.py --state quota
```

Expected: 设备上显示两条进度条（上=5h 绿，下=周 蓝），最右侧有金色实例标记。

- [ ] **Step 8: 提交**

```bash
git add yeelight-daemon.py yeelight-client.py tests/test_daemon.py
git commit -m "feat: add quota state for manual refresh"
```

---

### Task 8: 配置模板与文档

**Files:**
- Modify: `config.json.example`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `EFFECTS.md`

- [ ] **Step 1: 更新 `config.json.example`**

把内容替换为：

```json
{
  "ip": "192.168.1.100",
  "port": 55443,
  "instance": 0,
  "shared": 1,
  "quota": {
    "enabled": true,
    "api_base": "https://api.minimaxi.com",
    "api_key": "",
    "poll_interval": 300,
    "takeover_delay": 20
  }
}
```

- [ ] **Step 2: 更新 `README.md`**

在 `## Features` 列表末尾追加一行：

```markdown
- 📊 **Quota Meter** - Progress bars show remaining MiniMax Token Plan allowance
```

在 `## Demo` 表格后追加：

```markdown
### Token Plan Meter

When idle, the lamp shows your remaining MiniMax Token Plan allowance as two
progress bars — the 5-hour rolling window on top, the weekly window below.
The colors shift as the allowance runs low (green → yellow → red for the
5-hour window, cyan → blue → purple for the weekly one).

```
row4 |██████████████·····|   ← 5-hour window
row3 |██████████████·····|
row2 |····················|
row1 |█████···············|   ← weekly window
row0 |█████···············|
```
```

在 `## Files` 表格中追加两行：

```markdown
| `quota.py` | MiniMax Token Plan client and quota bar rendering |
| `config.py` | Configuration loading (config.json, env vars, CLI) |
```

在 `## Quick Start` 的 `### 4. Test` 之后追加一节：

````markdown
### 5. Token Plan Meter (Optional)

Copy `config.json.example` to `config.json` and fill in your MiniMax
subscription key (`config.json` is git-ignored):

```json
{
  "ip": "192.168.1.100",
  "instance": 0,
  "quota": {
    "enabled": true,
    "api_base": "https://api.minimaxi.com",
    "api_key": "sk-your-minimax-subscription-key",
    "poll_interval": 300,
    "takeover_delay": 20
  }
}
```

The API key is resolved in this order: `--quota-api-key` → `MINIMAX_API_KEY`
environment variable → `config.json` → `ANTHROPIC_AUTH_TOKEN` in
`~/.claude/settings.json`.

Check what the daemon resolved without touching the device:

```bash
python3 yeelight-daemon.py --dry-run
```

Force an immediate repaint:

```bash
python3 yeelight-client.py --state quota
```

The meter only paints while the lamp is idle — hook effects take priority and
the meter returns once they finish (after `takeover_delay` seconds, so the
green "task complete" breathing light stays visible for a while).
````

- [ ] **Step 3: 更新 `README_CN.md`**

在 `## 功能特性` 列表末尾追加：

```markdown
- 📊 **配额进度条** - 展示 MiniMax Token Plan 剩余额度
```

在 `## 效果预览` 表格后追加：

```markdown
## 配额进度条

空闲时，灯上显示 MiniMax Token Plan 的剩余额度：上 2 行是 5 小时滚动窗口，
下 2 行是周窗口。余量越低颜色越紧张（5h 绿→黄→红，周 青→蓝→紫）。

```
row4 |██████████████·····|   ← 5 小时窗口
row3 |██████████████·····|
row2 |····················|
row1 |█████···············|   ← 周窗口
row0 |█████···············|
```
```

在 `## 文件说明` 表格中追加：

```markdown
| `quota.py` | MiniMax 配额查询与进度条渲染 |
| `config.py` | 配置加载（config.json、环境变量、命令行） |
```

在 `### 4. 验证` 之后追加：

````markdown
### 5. 配额进度条（可选）

把 `config.json.example` 复制成 `config.json`，填入 MiniMax 订阅 key
（`config.json` 已在 .gitignore 中）：

```json
{
  "ip": "192.168.1.100",
  "instance": 0,
  "quota": {
    "enabled": true,
    "api_base": "https://api.minimaxi.com",
    "api_key": "sk-your-minimax-subscription-key",
    "poll_interval": 300,
    "takeover_delay": 20
  }
}
```

API key 的取值顺序：`--quota-api-key` → 环境变量 `MINIMAX_API_KEY` →
`config.json` → `~/.claude/settings.json` 里的 `ANTHROPIC_AUTH_TOKEN`。

查看 daemon 解析出的配置（不连设备）：

```bash
python3 yeelight-daemon.py --dry-run
```

手动强制刷新一次：

```bash
python3 yeelight-client.py --state quota
```

配额条只在灯空闲时显示 —— hook 效果优先，效果结束后（延迟 `takeover_delay` 秒，
让"任务完成"的绿色呼吸灯多亮一会儿）配额条再接管。
````

- [ ] **Step 4: 更新 `EFFECTS.md`**

在 `## 效果详情` 一节中，`### END (结束)` 之后追加：

```markdown
### QUOTA (配额余量)

- **颜色**: 按余量变化
  - 5 小时窗口（暖色阶）: ≥50% 绿 `(0,255,120)` → ≥20% 黄 `(255,200,0)` → 否则 红 `(255,40,40)`
  - 周窗口（冷色阶）: ≥50% 青 `(0,220,200)` → ≥20% 蓝 `(80,140,255)` → 否则 紫 `(170,80,255)`
- **内容**: 上下两条 2px 厚的进度条
  - 上 2 行（row4 + row3）= 5 小时滚动窗口剩余百分比
  - 下 2 行（row1 + row0）= 周窗口剩余百分比
  - 中间 row2 空出来，最右列 col19 留给实例标记
- **数据源**: `GET {api_base}/v1/token_plan/remains`，默认每 5 分钟查询一次
- **时机**: 仅在空闲时显示；hook 效果优先，效果结束后延迟 20 秒接管
- **触发**: daemon 内置配额线程自动刷新；`--state quota` 可手动强制刷新
```

并在文件末尾的 `## 手动测试` 代码块中追加一行：

```bash
python3 yeelight-client.py --state quota
```

- [ ] **Step 5: 确认没有把 key 提交进仓库**

Run: `grep -rn "sk-cp-\|sk-your" --include="*.py" --include="*.json" --include="*.md" . | grep -v "^./.git" | grep -v "config.json.example"`
Expected: 无输出（只有 `config.json.example` 里的占位符 `sk-your-minimax-subscription-key`）

Run: `git check-ignore -v config.json`
Expected: `.gitignore:26:config.json    config.json`（确认 config.json 被忽略）

- [ ] **Step 6: 跑全部测试**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 66 tests OK

- [ ] **Step 7: 提交**

```bash
git add config.json.example README.md README_CN.md EFFECTS.md
git commit -m "docs: document token plan quota meter and configuration"
```

---

## 完成标准

全部任务完成后，下面这些必须成立：

```bash
# 1. 全部测试通过
python3 -m unittest discover -s tests -t .

# 2. daemon 能解析配置
python3 yeelight-daemon.py --dry-run

# 3. daemon 语法正确、可启动
python3 -c "import ast; ast.parse(open('yeelight-daemon.py').read())"

# 4. 设备上能看到配额条
python3 yeelight-client.py --state quota
```

**人工验收清单：**

- [ ] 灯空闲时显示两条进度条，上条绿色（5h）、下条蓝色（周）
- [ ] 触发 THINK 效果时，配额条立刻让位给蜡烛效果
- [ ] 效果结束约 20 秒后，配额条重新出现
- [ ] `Stop` 后的绿色呼吸灯至少显示 20 秒，才被配额条覆盖
- [ ] 断网时灯上仍显示上一次的配额条（不清屏）
- [ ] 重启 daemon 后不需要改 plist，配额条照常出现
