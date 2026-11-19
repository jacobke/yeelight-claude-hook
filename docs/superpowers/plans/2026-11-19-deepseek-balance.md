# DeepSeek 余额页 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Yeelight 5×20 点阵上增加一页，与 MiniMax 配额页每 10 秒轮播，显示 DeepSeek 今日消费与账户余额。

**Architecture:** 新增 `deepseek.py`（余额客户端 + 今日消费基线追踪 + 金额格式化 + 页面渲染，除网络与文件读写外全是纯函数）。daemon 的显示循环从「只画 MiniMax」扩展为「选页 → 拉数据 → 画当前页」，页面轮播与页内轮流共用同一套空闲/效果保护逻辑。

**Tech Stack:** Python 3 标准库（`urllib` / `json` / `unittest`）；Yeelight LAN 协议（`update_leds` + FX direct 模式）。

**设计依据:** `docs/superpowers/specs/2026-11-19-deepseek-balance-design.md`

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `deepseek.py`（新增） | DeepSeek 余额接口、`DeepSeekError`、`SpendTracker`、金额格式化、页面渲染 |
| `tests/test_deepseek.py`（新增） | 上述模块的单元测试 |
| `config.py`（修改） | 新增 deepseek / rotation 配置解析与 `Settings` 字段 |
| `yeelight-daemon.py`（修改） | 显示循环、页面轮播、DeepSeek 轮询、按页绘制 |
| `tests/test_daemon.py`（修改） | 方法改名 + 轮播测试 |
| `config.json.example` / `.gitignore` / 文档（修改） | 配置模板与说明 |

### 命名变更

daemon 里原来的 `quota_tick` / `quota_should_paint` / `quota_loop` / `start_quota_thread`
现在要同时负责 DeepSeek 页，改名为：

| 旧名 | 新名 |
|---|---|
| `quota_tick` | `display_tick` |
| `quota_should_paint` | `display_should_paint` |
| `quota_loop` | `display_loop` |
| `start_quota_thread` | `start_display_thread` |

`paint_quota` / `quota_snapshot_if_available` / `quota_snapshot_if_available` 保持原名（仍只负责 MiniMax）。

---

## 任务清单

| # | 任务 | 类型 |
|---|---|---|
| 1 | `deepseek.py`：余额接口与解析 | TDD |
| 2 | `deepseek.py`：金额格式化与页面组合 | TDD |
| 3 | `deepseek.py`：页面渲染与配色隔离 | TDD |
| 4 | `deepseek.py`：`SpendTracker` 今日消费 | TDD |
| 5 | `config.py`：deepseek / rotation 配置 | TDD |
| 6 | daemon：显示循环与轮播 | TDD |
| 7 | 文档与配置模板 | 文档 |

---

### Task 1: `deepseek.py` 余额接口与解析

**Files:**
- Create: `deepseek.py`
- Create: `tests/test_deepseek.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_deepseek.py`：

```python
#!/usr/bin/env python3
"""deepseek.py 的单元测试"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deepseek  # noqa: E402


def balance_body(total, currency="CNY"):
    return {
        "is_available": True,
        "balance_infos": [{
            "currency": currency,
            "total_balance": str(total),
            "granted_balance": "0",
            "topped_up_balance": str(total),
        }],
    }


class TestParseBalance(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("58.44")), 58.44)

    def test_integer_string(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("100")), 100.0)

    def test_prefers_cny(self):
        body = {"is_available": True, "balance_infos": [
            {"currency": "USD", "total_balance": "10.00"},
            {"currency": "CNY", "total_balance": "58.44"},
        ]}
        self.assertAlmostEqual(deepseek.parse_balance(body), 58.44)

    def test_falls_back_to_first_entry(self):
        body = {"is_available": True, "balance_infos": [
            {"currency": "USD", "total_balance": "10.00"},
        ]}
        self.assertAlmostEqual(deepseek.parse_balance(body), 10.0)

    def test_not_a_dict(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(["nope"])

    def test_missing_balance_infos(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance({"is_available": True})

    def test_empty_balance_infos(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance({"balance_infos": []})

    def test_non_numeric_balance(self):
        body = {"balance_infos": [{"currency": "CNY", "total_balance": "n/a"}]}
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(body)

    def test_missing_total_balance(self):
        body = {"balance_infos": [{"currency": "CNY"}]}
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.parse_balance(body)

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(deepseek.parse_balance(balance_body("-3.5")), 0.0)

    def test_huge_value_clamped(self):
        self.assertAlmostEqual(
            deepseek.parse_balance(balance_body("999999999999")),
            deepseek.MAX_BALANCE)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchBalance(unittest.TestCase):
    def setUp(self):
        self._original = deepseek.urllib.request.urlopen

    def tearDown(self):
        deepseek.urllib.request.urlopen = self._original

    def test_requires_api_key(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("")

    def test_successful_fetch(self):
        payload = json.dumps(balance_body("58.44")).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            return FakeResponse(payload)

        deepseek.urllib.request.urlopen = fake_urlopen
        value = deepseek.fetch_balance("dummy-key")
        self.assertAlmostEqual(value, 58.44)
        self.assertEqual(captured["url"], "https://api.deepseek.com/user/balance")
        self.assertEqual(captured["auth"], "Bearer dummy-key")

    def test_trailing_slash_tolerated(self):
        payload = json.dumps(balance_body("1.0")).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse(payload)

        deepseek.urllib.request.urlopen = fake_urlopen
        deepseek.fetch_balance("k", api_base="https://api.deepseek.com/")
        self.assertEqual(captured["url"], "https://api.deepseek.com/user/balance")

    def test_invalid_json(self):
        deepseek.urllib.request.urlopen = lambda r, timeout=None: FakeResponse(b"nope")
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k")

    def test_bad_api_base(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k", api_base="not a url")

    def test_network_failure(self):
        with self.assertRaises(deepseek.DeepSeekError):
            deepseek.fetch_balance("k", api_base="http://127.0.0.1:9", timeout=1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'deepseek'`

- [ ] **Step 3: 写最小实现**

创建 `deepseek.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 107（既有） + 16（新增） = **123 tests OK**

- [ ] **Step 5: 用真实 key 验证一次**

Run:
```bash
python3 - <<'EOF'
import json, os, deepseek
tok = json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"]["ANTHROPIC_AUTH_TOKEN"]
print("DeepSeek 余额: ¥%.2f" % deepseek.fetch_balance(tok))
EOF
```
Expected: 打印一个正数，例如 `DeepSeek 余额: ¥58.44`。

- [ ] **Step 6: 提交**

```bash
git add deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek balance client"
```

---

### Task 2: `deepseek.py` 金额格式化与页面组合

**Files:**
- Modify: `deepseek.py`
- Modify: `tests/test_deepseek.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_deepseek.py` 的 `if __name__ == "__main__":` 之前插入：

```python
class TestFormatAmount(unittest.TestCase):
    def test_small_with_decimal(self):
        self.assertEqual(deepseek.format_amount(3.24, allow_decimal=True), "3.2")
        self.assertEqual(deepseek.format_amount(0.04, allow_decimal=True), "0.0")
        self.assertEqual(deepseek.format_amount(9.99, allow_decimal=True), "10.0")

    def test_small_without_decimal(self):
        self.assertEqual(deepseek.format_amount(3.6, allow_decimal=False), "4")
        self.assertEqual(deepseek.format_amount(0.4, allow_decimal=False), "0")

    def test_large_always_integer(self):
        self.assertEqual(deepseek.format_amount(12.5, allow_decimal=True), "13")
        self.assertEqual(deepseek.format_amount(123.4, allow_decimal=True), "123")
        self.assertEqual(deepseek.format_amount(0.0, allow_decimal=True), "0.0")

    def test_negative_treated_as_zero(self):
        self.assertEqual(deepseek.format_amount(-5, allow_decimal=False), "0")


class TestAbbreviate(unittest.TestCase):
    def test_below_ten_thousand(self):
        self.assertEqual(deepseek.abbreviate(0), "0")
        self.assertEqual(deepseek.abbreviate(9999), "9999")

    def test_thousands_no_decimal(self):
        self.assertEqual(deepseek.abbreviate(10000), "10K")
        self.assertEqual(deepseek.abbreviate(12345), "12K")
        self.assertEqual(deepseek.abbreviate(999999), "1000K")

    def test_millions_one_decimal(self):
        self.assertEqual(deepseek.abbreviate(1000000), "1.0M")
        self.assertEqual(deepseek.abbreviate(1234567), "1.2M")


class TestTextWidth(unittest.TestCase):
    def test_widths(self):
        self.assertEqual(deepseek.text_width("3.2"), 9)
        self.assertEqual(deepseek.text_width("58"), 7)
        self.assertEqual(deepseek.text_width("123"), 11)
        self.assertEqual(deepseek.text_width("1234"), 15)
        self.assertEqual(deepseek.text_width("12345"), 19)
        self.assertEqual(deepseek.text_width("12K"), 11)
        self.assertEqual(deepseek.text_width("1.2M"), 13)


class TestComposePage(unittest.TestCase):
    def test_typical_side_by_side(self):
        mode, texts = deepseek.compose_page(3.24, 58.44)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3.2", "58"])

    def test_three_digit_spend_two_digit_balance_side(self):
        mode, texts = deepseek.compose_page(123.0, 58.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["123", "58"])

    def test_three_digit_both_alternates(self):
        mode, texts = deepseek.compose_page(123.0, 456.0)
        self.assertEqual(mode, "alternate")
        self.assertEqual(texts, ["123", "456"])

    def test_five_digit_balance_abbreviated_side(self):
        mode, texts = deepseek.compose_page(3.0, 12345.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3", "12K"])

    def test_spend_decimal_dropped_before_alternating(self):
        mode, texts = deepseek.compose_page(1.2, 12345.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["1", "12K"])

    def test_four_digit_balance_side(self):
        mode, texts = deepseek.compose_page(3.0, 1234.0)
        self.assertEqual(mode, "side")
        self.assertEqual(texts, ["3", "1234"])


class TestComposeWidthInvariant(unittest.TestCase):
    def test_every_mode_fits(self):
        cases = [
            (0, 0), (3.24, 58.44), (12.5, 99.9), (123, 456),
            (3, 1234), (3, 12345), (3, 1234567), (1.2, 12345),
            (999999, 9999999), (0.01, 0.01),
        ]
        for spend, balance in cases:
            mode, texts = deepseek.compose_page(spend, balance)
            for text in texts:
                self.assertLessEqual(
                    deepseek.text_width(text), deepseek.USABLE_WIDTH,
                    "『%s』超宽 (spend=%s balance=%s)" % (text, spend, balance))
            if mode == "side":
                total = (deepseek.text_width(texts[0]) + 1
                         + deepseek.text_width(texts[1]))
                self.assertLessEqual(
                    total, deepseek.USABLE_WIDTH,
                    "并排超宽 spend=%s balance=%s" % (spend, balance))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: module 'deepseek' has no attribute 'format_amount'`

- [ ] **Step 3: 写最小实现**

在 `deepseek.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— **138 tests OK**（123 + 15）

- [ ] **Step 5: 提交**

```bash
git add deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek amount formatting and page composition"
```

---

### Task 3: `deepseek.py` 页面渲染与配色隔离

**Files:**
- Modify: `deepseek.py`
- Modify: `tests/test_deepseek.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_deepseek.py` 的 `if __name__ == "__main__":` 之前插入：

```python
class TestRenderPage(unittest.TestCase):
    def test_returns_100_pixels(self):
        self.assertEqual(len(deepseek.render_page("side", ["3.2", "58"])), 100)

    def test_last_column_always_black(self):
        for mode, texts, index in (
            ("side", ["3.2", "58"], 0),
            ("alternate", ["123", "456"], 0),
            ("alternate", ["123", "456"], 1),
        ):
            grid = deepseek.render_page(mode, texts, index)
            for row in range(deepseek.ROWS):
                self.assertEqual(
                    grid[row * deepseek.COLS + deepseek.COLS - 1],
                    deepseek.BLACK, "%s/%s 的 col19 应为黑" % (mode, index))

    def test_side_uses_both_colors(self):
        grid = deepseek.render_page("side", ["3.2", "58"])
        colors = {px for px in grid if px != deepseek.BLACK}
        self.assertEqual(colors, {deepseek.SPEND_COLOR, deepseek.BALANCE_COLOR})

    def test_alternate_index_selects_color(self):
        spend_grid = deepseek.render_page("alternate", ["123", "456"], 0)
        balance_grid = deepseek.render_page("alternate", ["123", "456"], 1)
        spend_colors = {px for px in spend_grid if px != deepseek.BLACK}
        balance_colors = {px for px in balance_grid if px != deepseek.BLACK}
        self.assertEqual(spend_colors, {deepseek.SPEND_COLOR})
        self.assertEqual(balance_colors, {deepseek.BALANCE_COLOR})

    def test_empty_page_is_black(self):
        grid = deepseek.render_page("side", ["", ""])
        self.assertEqual(set(grid), {deepseek.BLACK})

    def test_glyphs_do_not_overflow(self):
        # 最宽的合法组合也不能画到 col19 之外
        grid = deepseek.render_page("side", ["123", "58"])
        for row in range(deepseek.ROWS):
            self.assertEqual(grid[row * deepseek.COLS + 19], deepseek.BLACK)


class TestPaletteDisjointFromMiniMax(unittest.TestCase):
    """DeepSeek 页的配色不得与 MiniMax 页的任何颜色重合"""

    def test_no_overlap_with_minimax_palette(self):
        import quota
        minimax_colors = {
            quota.GREEN, quota.YELLOW, quota.RED, quota.TEAL, quota.BLUE,
            quota.PURPLE, quota.BLACK, quota.RESET_TRACK,
        }
        for _, color in quota.RESET_STOPS:
            minimax_colors.add(color)

        deepseek_colors = {deepseek.SPEND_COLOR, deepseek.BALANCE_COLOR}
        overlap = deepseek_colors & minimax_colors
        self.assertEqual(overlap, set(),
                         "DeepSeek 配色与 MiniMax 重合: %s" % (overlap,))

    def test_rendered_pixels_never_match_minimax(self):
        import quota
        minimax_colors = {quota.GREEN, quota.YELLOW, quota.RED, quota.TEAL,
                          quota.BLUE, quota.PURPLE, quota.RESET_TRACK}
        for _, color in quota.RESET_STOPS:
            minimax_colors.add(color)

        grids = [
            deepseek.render_page("side", ["3.2", "58"]),
            deepseek.render_page("alternate", ["123", "456"], 0),
            deepseek.render_page("alternate", ["123", "456"], 1),
        ]
        for grid in grids:
            for px in grid:
                if px == deepseek.BLACK:
                    continue
                self.assertNotIn(px, minimax_colors)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: module 'deepseek' has no attribute 'render_page'`

- [ ] **Step 3: 写最小实现**

在 `deepseek.py` 的常量区（`BLACK = (0, 0, 0)` 之后）插入字形表：

```python
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
```

在 `deepseek.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— **146 tests OK**（138 + 8）

- [ ] **Step 5: 目视验证**

Run:
```bash
python3 - <<'EOF'
import deepseek
for mode, texts, idx, label in (
    ("side", ["3.2", "58"], 0, "并排: 消费 3.2 / 余额 58"),
    ("alternate", ["123", "456"], 0, "轮流-消费 123"),
    ("alternate", ["123", "456"], 1, "轮流-余额 456"),
):
    g = deepseek.render_page(mode, texts, idx)
    print("---", label, "---")
    for r in range(4, -1, -1):
        line = ""
        for c in range(20):
            px = g[r*20+c]
            line += "·" if px == deepseek.BLACK else ("M" if px == deepseek.SPEND_COLOR else "W")
        print("  |" + line + "|")
EOF
```
Expected：每个 5×20 网格里 `M`（品红）与 `W`（白）各自构成可辨认的数字，
col19 为 `·`。

- [ ] **Step 6: 提交**

```bash
git add deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek page rendering with disjoint palette"
```

---

### Task 4: `deepseek.py` `SpendTracker` 今日消费

**Files:**
- Modify: `deepseek.py`
- Modify: `tests/test_deepseek.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_deepseek.py` 的 `if __name__ == "__main__":` 之前插入：

```python
import tempfile


class TestSpendTracker(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "quota_state.json")

    def test_first_run_sets_baseline(self):
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(61.73, "2026-11-19"), 0.0)
        self.assertAlmostEqual(t.day_start, 61.73)

    def test_spend_accumulates_same_day(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        self.assertAlmostEqual(t.update(60.00, "2026-11-19"), 1.73)
        self.assertAlmostEqual(t.update(58.44, "2026-11-19"), 3.29)

    def test_top_up_adjusts_baseline(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        t.update(58.44, "2026-11-19")          # 花了 3.29
        self.assertAlmostEqual(t.update(108.44, "2026-11-19"), 3.29,
                               msg="充值 50 不应抵消已花的钱")
        self.assertAlmostEqual(t.update(100.00, "2026-11-19"), 11.73,
                               msg="充值后继续消费应继续累加")

    def test_new_day_resets(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        t.update(58.44, "2026-11-19")
        self.assertAlmostEqual(t.update(58.44, "2026-11-20"), 0.0)
        self.assertAlmostEqual(t.day_start, 58.44)

    def test_state_persists_across_instances(self):
        t1 = deepseek.SpendTracker(self.path)
        t1.update(61.73, "2026-11-19")
        t1.update(58.44, "2026-11-19")

        t2 = deepseek.SpendTracker(self.path)
        t2.load()
        self.assertAlmostEqual(t2.day_start, 61.73)
        self.assertAlmostEqual(t2.update(57.00, "2026-11-19"), 4.73)

    def test_corrupt_state_treated_as_fresh(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(50.0, "2026-11-19"), 0.0)
        self.assertAlmostEqual(t.day_start, 50.0)

    def test_non_dict_state_treated_as_fresh(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        t = deepseek.SpendTracker(self.path)
        self.assertAlmostEqual(t.update(50.0, "2026-11-19"), 0.0)

    def test_save_writes_readable_json(self):
        t = deepseek.SpendTracker(self.path)
        t.update(61.73, "2026-11-19")
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["date"], "2026-11-19")
        self.assertAlmostEqual(data["day_start"], 61.73)

    def test_spend_never_negative(self):
        t = deepseek.SpendTracker(self.path)
        t.update(50.0, "2026-11-19")
        # 余额上涨但没归零基线（例如浮点抖动）时不应出现负数
        self.assertGreaterEqual(t.spent(), 0.0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: module 'deepseek' has no attribute 'SpendTracker'`

- [ ] **Step 3: 写最小实现**

在 `deepseek.py` 末尾追加：

```python
class SpendTracker:
    """追踪今日消费：当天起点余额 - 当前余额"""

    def __init__(self, state_path):
        self.state_path = state_path
        self.date = ""
        self.day_start = 0.0
        self.last_balance = 0.0
        self.load()

    def load(self):
        """读取状态文件；不存在或损坏时视为首次运行"""
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self._reset()
            return
        if not isinstance(data, dict):
            self._reset()
            return
        try:
            self.date = str(data.get("date") or "")
            self.day_start = float(data.get("day_start") or 0.0)
            self.last_balance = float(data.get("last_balance") or 0.0)
        except (TypeError, ValueError, OverflowError):
            self._reset()

    def _reset(self):
        self.date = ""
        self.day_start = 0.0
        self.last_balance = 0.0

    def update(self, balance, today):
        """更新基线并返回今日消费"""
        try:
            balance = float(balance)
        except (TypeError, ValueError, OverflowError):
            return self.spent()

        if self.date != today:
            self.date = today
            self.day_start = balance
            self.last_balance = balance
        else:
            if balance > self.last_balance:
                # 充值 / 退款：基线等额上调，已花金额不受影响
                self.day_start += (balance - self.last_balance)
            self.last_balance = balance

        self.save()
        return self.spent()

    def spent(self):
        """今日消费，保证非负"""
        return max(0.0, self.day_start - self.last_balance)

    def save(self):
        """先写临时文件再原子替换；失败时只记日志，不影响内存中的数值"""
        temp_path = self.state_path + ".tmp"
        try:
            parent = os.path.dirname(self.state_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump({
                    "date": self.date,
                    "day_start": round(self.day_start, 2),
                    "last_balance": round(self.last_balance, 2),
                }, f)
            os.replace(temp_path, self.state_path)
        except OSError as e:
            import sys
            print("SpendTracker save failed: %s" % e, file=sys.stderr)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— **155 tests OK**（146 + 9）

- [ ] **Step 5: 提交**

```bash
git add deepseek.py tests/test_deepseek.py
git commit -m "feat: add today's-spend tracker with persistent baseline"
```

---

### Task 5: `config.py` deepseek / rotation 配置

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_config.py` 的 `if __name__ == "__main__":` 之前插入：

```python
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

    def test_config_values(self):
        cfg = {"deepseek": {
            "enabled": True,
            "api_base": "https://example.com",
            "api_key": "ds-key",
            "poll_interval": 60,
            "alternate_interval": 3,
            "state_path": "/tmp/state.json",
        }, "rotation": {"interval": 20}}
        s = app_config.resolve_settings(make_args(), cfg, env={}, claude_token="")
        self.assertEqual(s.deepseek_api_base, "https://example.com")
        self.assertEqual(s.deepseek_api_key, "ds-key")
        self.assertEqual(s.deepseek_poll_interval, 60)
        self.assertEqual(s.deepseek_alternate_interval, 3)
        self.assertEqual(s.deepseek_state_path, "/tmp/state.json")
        self.assertEqual(s.rotation_interval, 20)

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
```

同时修改 `make_args()`，加入新参数：

```python
    defaults = dict(
        ip=None, port=None, instance=None, shared=None,
        quota_api_key=None, quota_api_base=None, quota_interval=None,
        no_quota=False,
        deepseek_api_key=None, deepseek_api_base=None, no_deepseek=False,
        rotation_interval=None,
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError: 'Settings' object has no attribute 'deepseek_enabled'`

- [ ] **Step 3: 写实现**

在 `config.py` 顶部 import 之后加：

```python
import deepseek
```

`Settings` 增加字段（放在 `takeover_delay` 之后）：

```python
    deepseek_enabled: bool
    deepseek_api_base: str
    deepseek_api_key: str
    deepseek_poll_interval: int
    deepseek_alternate_interval: int
    deepseek_state_path: str
    rotation_interval: int
```

在 `read_claude_settings_token` 之后新增：

```python
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
```

`resolve_settings` 签名改为：

```python
def resolve_settings(args, config, env=None, claude_token="", claude_env=None):
```

在函数体末尾（`return Settings(` 之前）加入：

```python
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

    if getattr(args, "no_deepseek", False):
        deepseek_enabled = False
    elif "enabled" in ds_cfg:
        deepseek_enabled = bool(ds_cfg["enabled"])
    else:
        deepseek_enabled = True
```

并在 `return Settings(...)` 中追加：

```python
        deepseek_enabled=deepseek_enabled,
        deepseek_api_base=deepseek_api_base,
        deepseek_api_key=deepseek_api_key,
        deepseek_poll_interval=deepseek_poll_interval,
        deepseek_alternate_interval=deepseek_alternate_interval,
        deepseek_state_path=deepseek_state_path,
        rotation_interval=rotation_interval,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— **167 tests OK**（155 + 12）

- [ ] **Step 5: 提交**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add DeepSeek and rotation settings"
```

---

### Task 6: daemon 显示循环与轮播

**Files:**
- Modify: `yeelight-daemon.py`
- Modify: `tests/test_daemon.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_daemon.py` 的 `make_daemon()` 中加入新字段：

```python
    daemon.deepseek_enabled = False
    daemon.deepseek_api_key = ""
    daemon.deepseek_api_base = deepseek_module.DEFAULT_API_BASE
    daemon.deepseek_poll_interval = 300
    daemon.deepseek_alternate_interval = 5
    daemon.deepseek_balance = None
    daemon.deepseek_spend = 0.0
    daemon.deepseek_last_fetch_at = 0.0
    daemon.deepseek_subpage = 0
    daemon.deepseek_subpage_started_at = 0.0
    daemon.last_deepseek_rendered = None
    daemon.rotation_interval = 10
    daemon.page = "minimax"
    daemon.page_started_at = 0.0
```

并在文件顶部加入：

```python
import deepseek as deepseek_module
```

把现有测试里的 `d.quota_tick()` / `d.quota_should_paint(...)` 全部替换为
`d.display_tick()` / `d.display_should_paint(...)`（共 8 处，用编辑器批量替换）。

在 `if __name__ == "__main__":` 之前新增：

```python
class TestPageRotation(unittest.TestCase):
    def _daemon_with_both_pages(self, **overrides):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=58.0, deepseek_spend=3.2,
                        last_effect_finished_at=0.0, quota_needs_repaint=False)
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: (d.deepseek_spend,
                                                           d.deepseek_balance)
        d.painted_pages = []
        original = d.paint_current_page

        def record():
            d.painted_pages.append(d.page)
            original()
        d.paint_current_page = record
        for key, value in overrides.items():
            setattr(d, key, value)
        return d

    def test_single_page_never_rotates(self):
        d = make_daemon(deepseek_enabled=False, quota_needs_repaint=False,
                        last_rendered=quota.QuotaSnapshot(50, 50),
                        last_effect_finished_at=0.0)
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        self.assertFalse(d.display_should_paint(now=1000.0))
        self.assertEqual(d.page, "minimax")

    def test_rotates_after_interval(self):
        d = self._daemon_with_both_pages(page="minimax", page_started_at=0.0)
        self.assertTrue(d.display_should_paint(now=11.0))
        self.assertEqual(d.page, "deepseek")

    def test_does_not_rotate_before_interval(self):
        d = self._daemon_with_both_pages(
            page="minimax", page_started_at=0.0,
            last_rendered=quota.QuotaSnapshot(50, 50),
            last_reset_fill=None)
        self.assertFalse(d.display_should_paint(now=5.0))

    def test_rotation_stops_during_effect(self):
        d = self._daemon_with_both_pages(
            page="minimax", page_started_at=0.0,
            effect_thread=FakeThread(True))
        self.assertFalse(d.display_should_paint(now=11.0))
        self.assertEqual(d.page, "minimax")

    def test_effect_resets_to_first_page(self):
        d = self._daemon_with_both_pages(page="deepseek")
        # 直接验证效果结束时的字段重置逻辑
        d.reset_page_after_effect(now=500.0)
        self.assertEqual(d.page, "minimax")
        self.assertAlmostEqual(d.page_started_at, 500.0)
        self.assertEqual(d.deepseek_subpage, 0)

    def test_falls_back_when_deepseek_missing(self):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        quota_needs_repaint=False,
                        last_rendered=quota.QuotaSnapshot(50, 50),
                        last_effect_finished_at=0.0, page="deepseek")
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: None
        self.assertTrue(d.display_should_paint(now=1000.0))
        self.assertEqual(d.page, "minimax")


class TestDeepSeekSubpage(unittest.TestCase):
    def _daemon(self, **overrides):
        d = make_daemon(deepseek_enabled=True, deepseek_api_key="k",
                        deepseek_balance=456.0, deepseek_spend=123.0,
                        page="deepseek", page_started_at=0.0,
                        deepseek_subpage_started_at=0.0,
                        last_effect_finished_at=0.0,
                        quota_needs_repaint=False)
        d.quota_snapshot_if_available = lambda now=None: quota.QuotaSnapshot(50, 50)
        d.deepseek_values_if_available = lambda now=None: (d.deepseek_spend,
                                                           d.deepseek_balance)
        for key, value in overrides.items():
            setattr(d, key, value)
        return d

    def test_alternate_mode_switches_after_interval(self):
        d = self._daemon()
        self.assertTrue(d.display_should_paint(now=6.0))
        self.assertEqual(d.deepseek_subpage, 1)

    def test_alternate_mode_waits_for_interval(self):
        d = self._daemon(deepseek_subpage=0,
                         last_deepseek_rendered=("alternate", ("123", "456"), 0))
        self.assertFalse(d.display_should_paint(now=2.0))
        self.assertEqual(d.deepseek_subpage, 0)

    def test_side_by_side_mode_does_not_switch(self):
        d = self._daemon(deepseek_balance=58.0, deepseek_spend=3.2,
                         last_deepseek_rendered=("side", ("3.2", "58"), 0))
        self.assertFalse(d.display_should_paint(now=6.0))
        self.assertEqual(d.deepseek_subpage, 0)

    def test_new_values_trigger_repaint(self):
        d = self._daemon(deepseek_balance=58.0, deepseek_spend=3.2,
                         last_deepseek_rendered=("side", ("3.2", "58"), 0))
        d.deepseek_spend = 4.0
        self.assertTrue(d.display_should_paint(now=6.0))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: FAIL —— `AttributeError` / `NameError: display_tick`

- [ ] **Step 3: 写实现**

**3a. 顶部 import**，在 `import quota` 之后加：

```python
import deepseek
```

**3b. `__init__` 签名**，在 `takeover_delay` 参数之后追加：

```python
                 deepseek_enabled=False,
                 deepseek_api_base=deepseek.DEFAULT_API_BASE,
                 deepseek_api_key="",
                 deepseek_poll_interval=deepseek.POLL_INTERVAL_DEFAULT,
                 deepseek_alternate_interval=deepseek.ALTERNATE_INTERVAL_DEFAULT,
                 deepseek_state_path="",
                 rotation_interval=10):
```

**3c. `__init__` 末尾**（`self.last_effect_finished_at = time.time()` 之后）加：

```python
        # ===== DeepSeek 余额页 =====
        self.deepseek_enabled = deepseek_enabled and bool(deepseek_api_key)
        self.deepseek_api_base = deepseek_api_base
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_poll_interval = deepseek_poll_interval
        self.deepseek_alternate_interval = deepseek_alternate_interval
        self.rotation_interval = rotation_interval
        self.deepseek_tracker = None
        if self.deepseek_enabled:
            state_path = deepseek_state_path or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "quota_state.json")
            self.deepseek_tracker = deepseek.SpendTracker(state_path)
        self.deepseek_balance = None
        self.deepseek_spend = 0.0
        self.deepseek_last_fetch_at = 0.0
        self.page = "minimax"
        self.page_started_at = time.time()
        self.deepseek_subpage = 0
        self.deepseek_subpage_started_at = time.time()
        self.last_deepseek_rendered = None
```

**3d. 新增 DeepSeek 取数方法**，插入到 `quota_snapshot_if_available` 之后：

```python
    def deepseek_values_if_available(self, now=None):
        """取 (今日消费, 余额)；不可用时返回 None"""
        if not self.deepseek_enabled:
            return None
        if now is None:
            now = time.time()
        if (self.deepseek_balance is not None
                and now - self.deepseek_last_fetch_at < self.deepseek_poll_interval):
            return (self.deepseek_spend, self.deepseek_balance)

        try:
            balance = deepseek.fetch_balance(self.deepseek_api_key,
                                             self.deepseek_api_base)
        except deepseek.DeepSeekError as e:
            print("DeepSeek fetch failed: %s" % e, file=sys.stderr, flush=True)
            self.deepseek_last_fetch_at = now
            if self.deepseek_balance is None:
                return None
            return (self.deepseek_spend, self.deepseek_balance)

        today = time.strftime("%Y-%m-%d", time.localtime())
        self.deepseek_spend = self.deepseek_tracker.update(balance, today)
        self.deepseek_balance = balance
        self.deepseek_last_fetch_at = now
        return (self.deepseek_spend, self.deepseek_balance)

    def available_pages(self, now=None):
        """当前可显示的页面列表（顺序即轮播顺序）"""
        pages = []
        if self.quota_enabled and self.quota_snapshot_if_available(now) is not None:
            pages.append("minimax")
        if (self.deepseek_enabled
                and self.deepseek_values_if_available(now) is not None):
            pages.append("deepseek")
        return pages

    def reset_page_after_effect(self, now=None):
        """效果结束后回到第一页，并重置子页"""
        if now is None:
            now = time.time()
        self.page = "minimax"
        self.page_started_at = now
        self.deepseek_subpage = 0
        self.deepseek_subpage_started_at = now
```

**3e. 替换 `quota_should_paint` 为 `display_should_paint`**

```python
    def display_should_paint(self, now=None):
        """是否需要重绘当前屏幕（可能顺带切换页面）"""
        if now is None:
            now = time.time()
        if not self.quota_enabled and not self.deepseek_enabled:
            return False
        if self.effect_thread and self.effect_thread.is_alive():
            return False
        if now - self.last_effect_finished_at < self.takeover_delay:
            return False

        pages = self.available_pages(now)
        if not pages:
            return False

        # 当前页不再可用 → 回到第一页
        if self.page not in pages:
            self.page = pages[0]
            self.page_started_at = now
            return True

        # 轮播
        if len(pages) > 1 and now - self.page_started_at >= self.rotation_interval:
            index = pages.index(self.page)
            self.page = pages[(index + 1) % len(pages)]
            self.page_started_at = now
            self.deepseek_subpage = 0
            self.deepseek_subpage_started_at = now
            return True

        if self.page == "deepseek":
            values = self.deepseek_values_if_available(now)
            if values is None:
                return False
            mode, texts = deepseek.compose_page(values[0], values[1])
            if mode == "alternate":
                if (now - self.deepseek_subpage_started_at
                        >= self.deepseek_alternate_interval):
                    self.deepseek_subpage ^= 1
                    self.deepseek_subpage_started_at = now
                    return True
                key = (mode, tuple(texts), self.deepseek_subpage)
            else:
                key = (mode, tuple(texts), 0)
            return key != self.last_deepseek_rendered or self.quota_needs_repaint

        # MiniMax 页
        snapshot = self.quota_snapshot_if_available(now)
        if snapshot is None:
            return False
        if snapshot.differs_from(self.last_rendered) or self.quota_needs_repaint:
            return True
        reset_pct = quota.reset_progress_pct(snapshot.interval_reset_at,
                                             now_ms=int(now * 1000))
        return quota.reset_fill_columns(reset_pct) != self.last_reset_fill
```

**3f. 把 `paint_quota` 里的接管序列抽出来**

```python
    def _takeover_and_send(self, grid):
        """停掉设备端内置效果，回到 direct 模式并发送像素"""
        self.send_command("stop_cf", [])
        self.send_command("set_power", ["on"])
        self.send_command("activate_fx_mode", [{"mode": "direct"}])
        self.send_pixels_with_mark(grid)

    def paint_quota(self, snapshot):
        """接管屏幕并画出 MiniMax 配额页"""
        now = time.time()
        reset_pct = quota.reset_progress_pct(snapshot.interval_reset_at,
                                             now_ms=int(now * 1000))
        grid = quota.render_bar(snapshot.interval_pct, snapshot.weekly_pct,
                                reset_pct)
        self._takeover_and_send(grid)
        self.last_rendered = snapshot
        self.last_reset_fill = quota.reset_fill_columns(reset_pct)
        self.quota_needs_repaint = False

    def paint_current_page(self):
        """画出当前页"""
        now = time.time()
        if self.page == "deepseek":
            values = self.deepseek_values_if_available(now)
            if values is None:
                return
            mode, texts = deepseek.compose_page(values[0], values[1])
            index = self.deepseek_subpage if mode == "alternate" else 0
            grid = deepseek.render_page(mode, texts, index)
            self._takeover_and_send(grid)
            self.last_deepseek_rendered = (mode, tuple(texts), index)
            self.quota_needs_repaint = False
            return
        snapshot = self.quota_snapshot_if_available(now)
        if snapshot is not None:
            self.paint_quota(snapshot)
```

**3g. 替换 `quota_tick` / `quota_loop` / `start_quota_thread`**

```python
    def display_tick(self):
        """显示线程的一轮：判断并（必要时）绘制一次。返回是否绘制了"""
        if not self.display_should_paint():
            return False
        self.paint_current_page()
        return True

    def display_loop(self):
        """显示线程主循环"""
        while self.running:
            time.sleep(1)
            try:
                self.display_tick()
            except Exception as e:
                print("Display loop error: %s" % e, file=sys.stderr, flush=True)

    def start_display_thread(self):
        """启动显示线程（两个数据源都不可用时不启动）"""
        if not self.quota_enabled and not self.deepseek_enabled:
            print("Display disabled (no API key)", file=sys.stderr, flush=True)
            return
        self.quota_thread = threading.Thread(target=self.display_loop, daemon=True)
        self.quota_thread.start()
```

**3h. `run_effect` 的 `finally` 增加页面重置**

把：

```python
        finally:
            # 记录效果结束时间，配额线程据此判断保护期
            self.last_effect_finished_at = time.time()
```

改为：

```python
        finally:
            # 记录效果结束时间，显示线程据此判断保护期
            self.last_effect_finished_at = time.time()
            self.reset_page_after_effect(self.last_effect_finished_at)
```

**3i. `main()` 接入新参数**

argparse 增加：

```python
    parser.add_argument("--deepseek-api-key", default=None, help="DeepSeek API key")
    parser.add_argument("--deepseek-api-base", default=None, help="DeepSeek API 域名")
    parser.add_argument("--no-deepseek", action="store_true", help="关闭 DeepSeek 余额页")
    parser.add_argument("--rotation-interval", type=int, default=None,
                        help="两页轮播间隔（秒，默认 10）")
```

`--dry-run` 的掩码同时处理两个 key：

```python
    if args.dry_run:
        data = dataclasses.asdict(settings)
        for field in ("api_key", "deepseek_api_key"):
            key = data.get(field) or ""
            if key:
                data[field] = "%s...%s" % (key[:6], key[-4:])
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
```

`resolve_settings` 调用改为：

```python
    settings = app_config.resolve_settings(
        args, cfg,
        claude_token=app_config.read_claude_settings_token(),
        claude_env=app_config.read_claude_settings_env())
```

`YeelightDaemon(...)` 构造追加：

```python
        settings.deepseek_enabled, settings.deepseek_api_base,
        settings.deepseek_api_key, settings.deepseek_poll_interval,
        settings.deepseek_alternate_interval, settings.deepseek_state_path,
        settings.rotation_interval,
```

并把：

```python
    daemon.start_quota_thread()
```

改为：

```python
    daemon.start_display_thread()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— **177 tests OK**（167 + 10）

- [ ] **Step 5: 验证 `--dry-run`**

Run: `python3 yeelight-daemon.py --dry-run`
Expected：JSON 中同时出现 `api_key` 与 `deepseek_api_key`（均打码），
且 `deepseek_enabled`、`rotation_interval` 存在。

- [ ] **Step 6: 真机验证**

```bash
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
sleep 25
tail -10 /tmp/yeelight-daemon.log
```

Expected：日志无异常；灯上应先显示 MiniMax 页，约 10 秒后切到 DeepSeek 页。

- [ ] **Step 7: 提交**

```bash
git add yeelight-daemon.py tests/test_daemon.py
git commit -m "feat: rotate between MiniMax and DeepSeek pages"
```

---

### Task 7: 文档与配置模板

**Files:**
- Modify: `config.json.example`
- Modify: `.gitignore`
- Modify: `README.md` / `README_CN.md` / `EFFECTS.md`

- [ ] **Step 1: `.gitignore` 增加状态文件**

在 `# Local config (user-specific)` 段落下加：

```
quota_state.json
quota_state.json.tmp
```

- [ ] **Step 2: `config.json.example`**

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
  },
  "deepseek": {
    "enabled": true,
    "api_base": "https://api.deepseek.com",
    "api_key": "",
    "poll_interval": 300,
    "alternate_interval": 5,
    "state_path": ""
  },
  "rotation": {
    "interval": 10
  }
}
```

- [ ] **Step 3: `README_CN.md`**

在「配额进度条」一节之后新增：

````markdown
## DeepSeek 余额页

如果你用 DeepSeek 的按量计费 API，灯上会多一页，与 MiniMax 页每 10 秒轮播：

```
|███·███ ··███·███|    品红 = 今日消费
|··█···█ ····█·█·█|    白色 = 账户余额
|███·███ ··███·███|
|█·····█ ····█·█·█|
|███·█··█ ··███·███|
```

- **今日消费** = 当天第一次看到的余额 − 当前余额。DeepSeek 没有公开的消费查询接口，
  所以这个值是 daemon 自己按余额变化算出来的
- 基线保存在 `quota_state.json`（已 gitignore），重启 daemon 不会丢失
- 金额较大时（3 位数 + 3 位数放不下）会自动改为同一页内轮流显示
- 余额 5 位以上会缩写成 `12K` / `1.2M`

**配置**：在 `config.json` 里加 `deepseek.api_key`。如果 `~/.claude/settings.json`
已经把 Claude Code 指向 DeepSeek，会自动复用那个 key，不用额外配置。

```json
"deepseek": { "enabled": true, "api_key": "sk-your-deepseek-key" }
```

关闭这一页：`--no-deepseek` 或 `"deepseek": { "enabled": false }`。
````

- [ ] **Step 4: `README.md`**

在 Token Plan Meter 一节之后新增对应的英文版本：

````markdown
## DeepSeek Balance Page

If you use DeepSeek's pay-as-you-go API, the lamp gains a second page that
alternates with the MiniMax page every 10 seconds:

```
|███·███ ··███·███|    magenta = spent today
|··█···█ ····█·█·█|    white   = account balance
|███·███ ··███·███|
|█·····█ ····█·█·█|
|███·█··█ ··███·███|
```

- **Spent today** = the balance first seen today minus the current balance.
  DeepSeek has no public spend query API, so this is derived from balance changes.
- The baseline is stored in `quota_state.json` (git-ignored) and survives restarts.
- When both amounts are large, the page switches to alternating the two values.
- Balances of 10,000+ are abbreviated as `12K` / `1.2M`.

Configure `deepseek.api_key` in `config.json`. If Claude Code is already pointed at
DeepSeek in `~/.claude/settings.json`, that key is reused automatically.
Disable with `--no-deepseek` or `"deepseek": { "enabled": false }`.
````

- [ ] **Step 5: `EFFECTS.md`**

在 QUOTA 一节之后新增：

```markdown
### DEEPSEEK (余额页)

- **布局**: 占满 5 行，与 MiniMax 页每 10 秒轮播
- **颜色**: 品红 `(255,0,160)` = 今日消费；白 `(235,235,235)` = 余额
  （与 MiniMax 的绿/黄/红/青/蓝/紫完全错开）
- **内容**: 左=今日消费，右=余额，中间 1 列分隔；col19 留给实例标记
- **自适应**: 两个数字放不下时（如 3 位数 + 3 位数），改为页内轮流显示，各 5 秒
- **缩写**: 余额 ≥ 1 万显示 `12K`，≥ 100 万显示 `1.2M`
- **数据源**: `GET https://api.deepseek.com/user/balance`，默认每 5 分钟查询
- **今日消费**: 当天起点余额 − 当前余额；基线存 `quota_state.json`
```

- [ ] **Step 6: 跑全部测试**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS —— 177 tests OK

- [ ] **Step 7: 确认没有泄露密钥**

Run:
```bash
git status --short
git diff --cached | grep -iE "sk-[A-Za-z0-9]{10,}" || echo "  ✅ 无密钥"
git check-ignore quota_state.json config.json
```
Expected：`quota_state.json` 与 `config.json` 都被忽略。

- [ ] **Step 8: 提交**

```bash
git add config.json.example .gitignore README.md README_CN.md EFFECTS.md
git commit -m "docs: document DeepSeek balance page and configuration"
```

---

## 完成标准

```bash
python3 -m unittest discover -s tests -t .
python3 yeelight-daemon.py --dry-run
python3 -c "import ast; ast.parse(open('yeelight-daemon.py').read())"
```

**人工验收：**

- [ ] 灯在 MiniMax 页与 DeepSeek 页之间每 10 秒切换
- [ ] DeepSeek 页左边品红、右边白色，颜色与 MiniMax 页明显不同
- [ ] 消费与余额数值与 DeepSeek 控制台一致（允许几元误差：差值法按轮询时刻计算）
- [ ] 金额达到 3 位数 + 3 位数时切换为轮流显示
- [ ] 触发 THINK 等效果时轮播暂停，效果结束后 20 秒回到 MiniMax 页
- [ ] 重启 daemon 后今日消费不归零（基线持久化）
