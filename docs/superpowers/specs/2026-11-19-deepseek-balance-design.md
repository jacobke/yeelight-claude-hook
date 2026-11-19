# 设计：DeepSeek 今日消费与余额显示

- 日期：2026-11-19
- 状态：已确认
- 前置：MiniMax 配额进度条（已完成）

## 1. 背景与目标

用户同时使用 MiniMax Token Plan（按套餐）和 DeepSeek API（按量计费）。
MiniMax 的余量已经显示在灯上，现在还需要看到：

- 今天 DeepSeek 花了多少钱
- DeepSeek 账户还剩多少钱

5×20 点阵的 5 行已经全部被 MiniMax 占用，因此采用**两页轮播**：
同一块屏幕每 10 秒在 MiniMax 页和 DeepSeek 页之间切换。

## 2. 约束

| 约束 | 来源 | 影响 |
|---|---|---|
| 屏幕 5×20 已被 MiniMax 占满 | 现有功能 | 只能整页轮播，不能分屏 |
| 3×5 字体，每字 3 列、间距 1 列 | 现有字体 | 一行最多 4~5 个字符；19 列可用（col19 留给实例标记） |
| 设备命令上限约 60 次/分钟 | 设备固件 | 每 10 秒切页 = 6 次/分钟，可接受 |
| DeepSeek 无公开「今日消费」接口 | 官方 API | 必须用余额差值自行计算 |
| MiniMax 已占用大部分色环 | 现有配色 | DeepSeek 必须使用不重叠的色系 |
| 项目承诺无第三方依赖 | README | 只用标准库 |

## 3. 已确认的决策

| # | 决策 |
|---|---|
| D1 | 两页轮播（MiniMax 页 ↔ DeepSeek 页），每页默认 10 秒 |
| D2 | DeepSeek 页并排显示两个数字：左=今日消费，右=余额 |
| D3 | 今日消费 = 当天起点余额 − 当前余额（余额差值法） |
| D4 | DeepSeek 色系：品红 `(255,0,160)` = 消费，白 `(235,235,235)` = 余额；与 MiniMax 色系不重叠 |
| D5 | 余额取整显示；消费小于 10 时保留一位小数 |
| D6 | 基线状态持久化到 `quota_state.json` |
| D7 | 有 hook 效果时暂停轮播，效果结束后 20 秒回到 MiniMax 页 |

## 4. 架构

```
yeelight-daemon.py
├── quota_loop（现有，扩展为显示循环）
│   ├── MiniMax 页 ← quota.py（现有）
│   └── DeepSeek 页 ← deepseek.py（新增）
├── deepseek.py
│   ├── fetch_balance()        网络请求
│   ├── parse_balance()        纯函数：响应 → 余额
│   ├── SpendTracker           状态：今日基线 / 今日消费
│   ├── format_amount()        纯函数：金额 → 数字字符串
│   ├── compose_page()         纯函数：两段数字 → 布局
│   └── render_page()          纯函数：→ 100 个像素
└── config.py（扩展）
```

`deepseek.py` 中除了 `fetch_balance()` 和 `SpendTracker` 的读写，全部是纯函数。
数字字形（0-9 与窄小数点）内联在 `deepseek.py` 中，只有这一个消费者，不新建公共字体模块。

### 4.1 `deepseek.py` 对外接口

```python
class DeepSeekError(Exception): ...

def fetch_balance(api_key, api_base=DEFAULT_API_BASE, timeout=10.0) -> float:
    """GET /user/balance → 余额（float，CNY）；任何失败抛 DeepSeekError"""

def parse_balance(body) -> float:
    """纯函数：响应体 → 余额；结构不符抛 DeepSeekError"""

def format_amount(value, allow_decimal=True) -> str:
    """纯函数：金额 → 数字字符串（是否保留 1 位小数由 allow_decimal 决定）"""

def abbreviate(value) -> str:
    """纯函数：大额缩写 → '12.3K' / '1.2M'；< 10000 返回整数串"""

def text_width(text) -> int:
    """纯函数：数字串占用的列数（数字 3 列、小数点 1 列、间距 1 列）"""

def compose_page(spend, balance) -> tuple[str, list[str]]:
    """纯函数：→ (mode, texts)

    mode = "side"  → texts = [消费串, 余额串]，两段并排
    mode = "alternate" → texts = [消费串, 余额串]，轮流显示
    """

def render_page(mode, texts, index=0) -> list[tuple[int, int, int]]:
    """纯函数：→ 100 个像素

    mode == "side" 时忽略 index，两段并排；
    mode == "alternate" 时按 index 取 texts[index] 单段居中。
    """

class SpendTracker:
    def __init__(self, state_path): ...
    def update(self, balance: float, today: str) -> float:
        """更新基线并返回今日消费"""
    def load(self) -> None: ...
    def save(self) -> None:
        """写临时文件后 os.replace()"""
```

`format_amount` 的宽度计算：字符宽度之总和 + 字符间距（1 列）之总和；
小数点按 1 列宽计，其余数字按 3 列宽计。

## 5. 数据获取

### 5.1 接口

```
GET {api_base}/user/balance
Authorization: Bearer <api_key>
Accept: application/json
timeout 10s
```

实测响应（2026-11-19）：

```json
{
  "is_available": true,
  "balance_infos": [
    {"currency": "CNY", "total_balance": "58.44",
     "granted_balance": "1.47", "topped_up_balance": "56.97"}
  ]
}
```

解析规则：

1. 响应必须是 dict，`balance_infos` 必须是非空 list，否则抛 `DeepSeekError`
2. 优先取 `currency == "CNY"` 的条目，没有则取第一条
3. `total_balance` 必须是可转成 float 的数字字符串，否则抛 `DeepSeekError`
4. 余额 clamp 到 `[0, 10_000_000]`

### 5.2 今日消费

`SpendTracker` 持有并持久化三个字段：

```json
{"date": "2026-11-19", "day_start": 61.73, "last_balance": 58.44}
```

每次成功拿到余额 `b`（本地日期 `d`）时：

| 情况 | 处理 |
|---|---|
| 无状态文件 / 文件损坏 | `date = d`，`day_start = b`，`last_balance = b` |
| `state.date != d`（跨天） | `date = d`，`day_start = b`，`last_balance = b` |
| `b > last_balance`（充值/退款） | `day_start += (b - last_balance)`，`last_balance = b` |
| 其他（正常消费） | `last_balance = b` |

今日消费 = `max(0.0, day_start - last_balance)`。

**已知局限**：如果 daemon 在午夜没有运行，基线会在午夜后第一次成功轮询时建立，
这段空档内的消费无法计入。launchd 配置为 KeepAlive 常驻，正常情况不会发生。

### 5.3 状态文件写入

路径与 `config.json` 同目录，默认 `quota_state.json`，已加入 `.gitignore`。
写入方式：先写 `quota_state.json.tmp`，再 `os.replace()` 覆盖正式文件，避免写一半被中断导致损坏。

## 6. 渲染

### 6.1 布局

DeepSeek 页占满 5 行，左右并排两组数字，中间留 1 列分隔：

```
|███·███ ··███·███|     左边：品红，今日消费
|··█···█ ····█·█·█|     右边：白色，余额
|███·███ ··███·███|     中间：1 列空白
|█·····█ ····█·█·█|     col19：留给实例标记，恒为黑
|███·█··█ ··███·███|
```

- 数字使用 3×5 字形，垂直居中于 5 行（天然填满整个高度）
- 小数点使用**窄字形**：宽 1 列，只点亮最底部一个像素
- 字符间距 1 列；两组数字之间再留 1 列

### 6.2 配色

```python
SPEND_COLOR = (255, 0, 160)      # 品红：今日消费
BALANCE_COLOR = (235, 235, 235)  # 白：余额
```

选择理由：MiniMax 页使用绿 / 黄 / 红 / 青 / 蓝 / 紫，以及蓝→青→绿→黄→橙的渐变，
均不包含品红与白色。两页的整体色相因此显著不同。

**这条约束由单元测试锁定**：断言 DeepSeek 页出现的每个非黑色都不等于 MiniMax 配色中的任何颜色。

### 6.3 宽度预算

可用宽度 19 列（col0..col18）。

数字串宽度 = Σ字符宽度 + (字符数 − 1) × 1 列间距，其中数字 3 列、窄小数点 1 列。
例：`3.2` = 3+1+3 + 2 = 9；`1234` = 3×4 + 3 = 15；`12K` = 3×3 + 2 = 11。

两组数字之间另留 1 列分隔。

| 场景 | 今日消费 | 余额 | 总宽 | 模式 |
|---|---|---|---|---|
| 消费 < 10，余额 < 100 | `3.2`（9） | `58`（7） | 9+1+7 = 17 ✓ | 并排 |
| 消费 ≥ 10，余额 < 100 | `12`（7） | `58`（7） | 15 ✓ | 并排 |
| 消费 3 位，余额 2 位 | `123`（11） | `58`（7） | 19 ✓ | 并排 |
| 消费 3 位，余额 3 位 | `123`（11） | `456`（11） | 23 ✗ → 缩写后 11+1+11=23 ✗ | **轮流** |
| 余额 4 位 | `3`（3） | `1234`（15） | 19 ✓ | 并排 |
| 余额 5 位 | `3`（3） | `12345`（19） | 23 ✗ → 缩写 `12K`（11）→ 15 ✓ | 并排 |
| 余额 7 位 | `3`（3） | `1.2M`（13） | 17 ✓ | 并排 |

**降级顺序**：

1. 消费保留 1 位小数（若 < 10），余额取整 → 两段并排
2. 总宽 > 19 → 消费改为取整，重试
3. 仍 > 19 → 余额改用缩写（见下），重试
4. 仍 > 19 → **切换为轮流模式**（这一页内先显示消费，再显示余额）

**余额缩写规则**（仅在前两步都放不下时才启用）：

| 范围 | 形式 | 例 | 宽度 |
|---|---|---|---|
| < 10,000 | 整数 | `1234` | 15 |
| 10,000 ~ 999,999 | `{v/1000:.0f}K`（**不带小数**） | `12345` → `12K` | 11 |
| ≥ 1,000,000 | `{v/1e6:.1f}M` | `1234567` → `1.2M` | 13 |

K 一定不带小数：带上小数后 `12.3K` 是 17 列，比原数字 `12345`（19 列）只省 2 列，
起不到作用；不带小数时 `12K` 只有 11 列。M 保留 1 位小数是因为 7 位数字本身太大，
而 `1.2M` 仍在 13 列。

字母 `K` 与 `M` 使用 3×5 字形（与数字同高）。

**轮流模式**：

- 消费占满 19 列，品红，显示 `alternate_interval`（默认 5 秒）
- 余额占满 19 列，白，显示同样时长
- 两个数字各自居中
- 单个数最多 5 位整数（19 列）；6 位及以上走缩写规则

## 7. 调度与轮播

### 7.1 daemon 新增状态

| 字段 | 说明 |
|---|---|
| `page` | 当前页：`"minimax"` 或 `"deepseek"` |
| `page_started_at` | 当前页开始显示的时间戳 |
| `rotation_interval` | 切页间隔（秒），默认 10 |
| `deepseek_enabled` | 是否启用 |
| `deepseek_tracker` | `SpendTracker` 实例 |
| `deepseek_last_fetch_at` | 上次请求余额的时间戳 |
| `last_deepseek_rendered` | 上次画出的（模式, 两段文本, 索引），用于判断是否需要重绘 |
| `deepseek_subpage` | 轮流模式下的当前索引（0=消费，1=余额） |
| `deepseek_subpage_started_at` | 当前子页开始显示的时间戳 |
| `deepseek_alternate_interval` | 轮流模式下的子页切换间隔，默认 5 秒 |

### 7.2 显示循环

```
while running:
    sleep(1)
    if 有 effect 线程存活:            continue
    if 距上次效果结束 < takeover_delay: continue

    pages = 可用页面列表
      # minimax 可用 = 已成功拿到过配额快照
      # deepseek 可用 = 已配置 key 且成功拿到过余额
      # 两页都不可用 → 屏幕保持现状
    if 空: continue

    if len(pages) > 1 and now - page_started_at >= rotation_interval:
        切到下一页；置需要重绘

    if 当前页 == deepseek and 当前模式 == alternate:
        if now - deepseek_subpage_started_at >= deepseek_alternate_interval:
            deepseek_subpage ^= 1；置需要重绘

    if 当前页数据过期:
        拉取（失败则保留旧值）

    if 当前页的数据与上次绘制不同 or 需要重绘:
        接管屏幕并绘制
```

模式由 `compose_page()` 根据当前金额决定；模式变化时索引重置为 0（先显示消费）。

### 7.3 与效果的交界

- 效果启动时：暂停轮播（沿用现有的「效果线程存活」判断）
- 效果线程结束时（`finally`）：记录 `last_effect_finished_at`
- 保护期结束后：`page` 重置为可用页面列表的第一页（MiniMax 优先），重新开始计时

### 7.4 命令占用

每次切页 1 条 `update_leds`。10 秒间隔 = 6 条/分钟，加上数据变化时的重绘，仍远低于 60 次/分钟。

## 8. 配置

```json
{
  "quota": { "...MiniMax 现有配置..." },
  "deepseek": {
    "enabled": true,
    "api_base": "https://api.deepseek.com",
    "api_key": "",
    "poll_interval": 300,
    "state_path": "",
    "alternate_interval": 5
  },
  "rotation": {
    "interval": 10
  }
}
```

| 配置项 | 解析顺序 |
|---|---|
| `api_key` | `--deepseek-api-key` → `DEEPSEEK_API_KEY` → `config.json.deepseek.api_key` → 若 `~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL` 含 `deepseek`，则用其 `ANTHROPIC_AUTH_TOKEN` |
| `api_base` | `--deepseek-api-base` → `config.json.deepseek.api_base` → `https://api.deepseek.com` |
| `enabled` | `--no-deepseek` → `config.json.deepseek.enabled` → `true`（但有 key 才真正启用） |
| `poll_interval` | `config.json.deepseek.poll_interval` → `300` |
| `state_path` | `config.json.deepseek.state_path` → 与 config 同目录的 `quota_state.json` |
| `alternate_interval` | `config.json.deepseek.alternate_interval` → `5` |
| `rotation.interval` | `--rotation-interval` → `config.json.rotation.interval` → `10` |

新增命令行参数：`--deepseek-api-key`、`--deepseek-api-base`、`--no-deepseek`、`--rotation-interval`。

`config.json.example` 同步更新，`api_key` 留空。

## 9. 错误处理

| 情况 | 行为 |
|---|---|
| 余额接口失败 | 保留上次数值继续显示；从未成功过则跳过 DeepSeek 页 |
| 状态文件损坏 / 不存在 | 当作首次运行，基线 = 当前余额 |
| 状态文件写入失败 | 记日志，内存中的数值继续使用；下次轮询再尝试写入 |
| 余额上涨（充值） | 基线等额上调，已花金额不受影响 |
| 跨天 | 基线重置，今日消费归零 |
| 数字超宽 | 按 §6.3 降级 |
| 设备不可达 | 走现有重连机制 |
| 渲染异常 | 捕获并记日志，daemon 继续运行 |

**不清屏**原则沿用：接口故障不应让屏幕熄灭或显示错误数据。

## 10. 测试

新增 `tests/test_deepseek.py`，标准库 `unittest`：

| 对象 | 用例 |
|---|---|
| `parse_balance` | 正常；多币种时选 CNY；无 CNY 时取第一条；缺 `balance_infos`；空列表；`total_balance` 非数字；负数；超大值 |
| `format_amount` | 0、0.04、3.2、12.5、99.9、100、1234、12345 的取整规则 |
| `abbreviate` | 9999→`9999`；10000→`10K`；12345→`12K`；999999→`1000K`；1000000→`1.0M`；1234567→`1.2M` |
| `text_width` | `3.2`=9；`58`=7；`1234`=15；`12K`=11；`1.2M`=13 |
| `compose_page` | §6.3 表中所有场景：模式选择正确、两段宽度 ≤ 19；3 位+3 位 → alternate；大额缩写后仍能并排 |
| `render_page` | 返回 100 像素；col19 恒黑；只有品红与白两种非黑色；与 MiniMax 配色无交集；alternate 模式下 index 0/1 分别只出现对应颜色 |
| 轮播子页 | alternate 模式下按间隔切换索引；side 模式不切换 |
| `SpendTracker` | 首次运行；同日消费；充值调整；跨天重置；状态文件损坏；写入后能读回 |
| 轮播 | 到点切页；效果期间不切；效果结束后回到第一页；只有一页时不轮播 |

## 11. 改动清单

| 文件 | 改动 |
|---|---|
| `deepseek.py` | **新增** —— 余额客户端、SpendTracker、金额格式化、页面渲染 |
| `tests/test_deepseek.py` | **新增** |
| `config.py` | 新增 deepseek / rotation 配置解析 |
| `tests/test_config.py` | 补充新配置项的优先级测试 |
| `yeelight-daemon.py` | 轮播状态机、DeepSeek 轮询、按页绘制 |
| `tests/test_daemon.py` | 补充轮播相关测试 |
| `config.json.example` | 增加 deepseek / rotation 段 |
| `.gitignore` | 增加 `quota_state.json` |
| `README.md` / `README_CN.md` / `EFFECTS.md` | 补充 DeepSeek 页说明 |

## 12. 不在本期范围

- 不做 DeepSeek 的 token 明细或按模型拆分
- 不做消费趋势 / 历史曲线
- 不改动 MiniMax 页的现有视觉
- 不抓取 platform 私有接口（需要网页登录态）

## 13. 参考资料

- DeepSeek 余额接口：`GET https://api.deepseek.com/user/balance`
- 每日消费无公开接口的说明：[CodexBar DeepSeek 文档](https://github.com/steipete/codexbar/blob/main/docs/deepseek.md)
