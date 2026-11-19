# 设计：MiniMax Token Plan 余量进度条

- 日期：2026-11-19
- 状态：已确认
- 分支：`feat/token-plan-progress-bar`

## 1. 背景与目标

用户使用 MiniMax Token Plan 套餐，希望在 Yeelight Cube Lite（5×20 RGB 点阵）上常驻显示
**剩余配额余量**，形式为两条进度条：

- 上 2 行 = 5 小时滚动窗口剩余百分比
- 下 2 行 = 周窗口剩余百分比

配色随余量变化（绿→黄→红 / 青→蓝→紫），让灯本身表达紧迫感，无需读数字。

## 2. 约束

| 约束 | 来源 | 影响 |
|---|---|---|
| 屏幕只有 5×20 = 100 颗 LED | 硬件 | 两条 2px 厚的条 + 1 行分隔刚好占满 5 行 |
| 设备命令频率上限约 60 次/分钟 | 设备固件 | 配额条只在数值变化时重绘，约 1 次/5 分钟 |
| 同一块屏幕，被所有 hook 效果共用 | 现有架构 | 配额条与效果必须互斥，由 daemon 统一调度 |
| `start_cf` 内置效果在设备端无限循环 | 设备固件 | 配额条接管前必须先 `stop_cf` |
| 现有实例标记占用最右列 col19 | 现有约定 | 条宽定为 19px，col19 留给标记 |
| 项目承诺「Python 3，无需额外依赖」 | README | 测试用标准库 `unittest`，不引入 pytest |

## 3. 已确认的决策

| # | 决策 |
|---|---|
| D1 | 空闲时常驻显示；有 Claude Code 活动时让位给现有效果，活动结束后回落 |
| D2 | 同时显示 5h 与周两个窗口，上下各 2 行的纯进度条，不显示数字 |
| D3 | 颜色按余量变化：5h 走暖色阶（绿/黄/红），周走冷色阶（青/蓝/紫） |
| D4 | daemon 每 5 分钟轮询一次接口，数值未变则不重绘 |
| D5 | 架构 = daemon 内置配额线程（方案 A），逻辑抽成独立模块 `quota.py`（方案 C） |
| D6 | 任务完成的绿色呼吸灯保留 20 秒，之后被配额条覆盖 |
| D7 | 配置走 `config.json`（已 gitignore），并提供 `config.json.example` |

## 4. 架构

```
Claude Code Hooks ──► yeelight-client.py ──Unix Socket──► yeelight-daemon.py ──TCP 55443──► Cube Lite
                                                          ├── effect 线程（现有）
                                                          └── quota 线程（新增）
                                                               └── quota.py（新增模块）
```

`quota.py` 中除 `fetch_quota()` 外全部是纯函数，不触碰 socket 与设备，可直接单元测试。

### 4.1 `quota.py` 对外接口

```python
DEFAULT_API_BASE = "https://api.minimaxi.com"   # 国内站
POLL_INTERVAL_DEFAULT = 300                      # 秒
TAKEOVER_DELAY_DEFAULT = 20                      # 秒

class QuotaError(Exception): ...

@dataclass(frozen=True)
class QuotaSnapshot:
    interval_pct: int       # 5h 窗口剩余百分比，0..100
    weekly_pct: int         # 周窗口剩余百分比，0..100
    interval_reset_at: int  # 5h 窗口重置时间（epoch ms）
    weekly_reset_at: int    # 周窗口重置时间（epoch ms）

    def differs_from(self, other: "QuotaSnapshot | None") -> bool:
        """只比较百分比 —— 重置时间变化不必触发重绘"""
        ...

def fetch_quota(api_key: str, api_base: str = DEFAULT_API_BASE,
                timeout: float = 10.0) -> QuotaSnapshot:
    """GET {api_base}/v1/token_plan/remains；失败抛 QuotaError"""

def parse_remains(body: dict) -> QuotaSnapshot:
    """纯函数：解析响应 → QuotaSnapshot；结构不符抛 QuotaError"""

def level_color(pct: int, ramp: tuple) -> tuple[int, int, int]:
    """纯函数：按色阶取颜色"""

def render_bar(interval_pct: int, weekly_pct: int) -> list[tuple[int, int, int]]:
    """纯函数：返回 100 个 (r,g,b) 像素"""
```

### 4.2 配色

```python
GREEN  = (0, 255, 120)
YELLOW = (255, 200, 0)
RED    = (255, 40, 40)
TEAL   = (0, 220, 200)
BLUE   = (80, 140, 255)
PURPLE = (170, 80, 255)

WARM_RAMP = ((50, GREEN), (20, YELLOW), (0, RED))    # 5h
COOL_RAMP = ((50, TEAL),  (20, BLUE),  (0, PURPLE)) # 周
```

`level_color(pct, ramp)` 按 ramp 顺序取第一个满足 `pct >= threshold` 的颜色。
边界：`pct >= 50` → 绿/青；`pct >= 20` → 黄/蓝；否则 → 红/紫。`pct` 恒被 clamp 到 `0..100`。

## 5. 数据获取

### 5.1 接口

```
GET {api_base}/v1/token_plan/remains
Authorization: Bearer <api_key>
Content-Type: application/json
timeout 10s
```

| 站点 | api_base |
|---|---|
| 国内（默认） | `https://api.minimaxi.com` |
| 国际 | `https://api.minimax.io` |

实测（2026-11-19，本机 key）：

```json
{
  "model_remains": [{
    "model_name": "general",
    "current_interval_remaining_percent": 64,
    "current_weekly_remaining_percent": 23,
    "current_interval_total_count": 0,
    "current_weekly_total_count": 0,
    "end_time": 1795073698120,
    "weekly_end_time": 1795070409914
  }],
  "base_resp": {"status_code": 0, "status_msg": "success"}
}
```

关键事实（已实测确认）：

- Token Plan 返回**百分比形态**，`*_total_count` / `*_usage_count` 恒为 `0`，不可用于算比例
- `*_remaining_percent` 是**剩余**不是已用 —— 会话开始时 5h 为 74%，随本轮对话消耗降到 64%
- `model_name` 为 `"general"` 的条目是套餐级总量；账号可能返回多条（各模型），此时优先取 `general`
- `base_resp.status_code` 非 0 是业务错误（`2049` = invalid api key）

### 5.2 解析规则

1. `body` 必须是 dict，含 `base_resp` 且 `status_code == 0`，否则 `QuotaError`
2. `model_remains` 必须是非空 list，否则 `QuotaError`
3. 选中条目：`model_name == "general"` 的那条；没有则取列表第一条
4. 百分比取 `current_interval_remaining_percent` / `current_weekly_remaining_percent`，
   非数字按 0 处理，clamp 到 `0..100`
5. 重置时间取 `end_time` / `weekly_end_time`（epoch ms），缺失填 0

### 5.3 缓存

daemon 持有最后一次成功快照。`poll_interval`（默认 300 秒）内不重复请求接口。
快照的 `differs_from()` 只比较两个百分比 —— 重置时间变了不必重绘。

## 6. 渲染

### 6.1 物理行分配

```
物理行 4 ┐
物理行 3 ┘  5 小时条（2px 厚，19 列）
物理行 2     分隔行（空，仅最右列放实例标记）
物理行 1 ┐
物理行 0 ┘  周条（2px 厚，19 列）
```

- 条宽 `BAR_WIDTH = 19`，占用 col0..col18
- col19 专供实例标记，沿用现有约定（instance N → 物理行 `5 - N`），
  保持所有效果中 col19 的语义一致
- 填充像素数 `filled = int(BAR_WIDTH * pct / 100 + 0.5)`（四舍五入；50% → 10px，100% → 19px 刚好满格）
- 未填充部分纯黑 `(0, 0, 0)`

### 6.2 像素示例（5h 74% / 周 24%，instance 2）

```
row4 |██████████████·····|
row3 |██████████████····█|   ← instance 2 的金色标记落在 row3 col19（条的右端外侧）
row2 |····················|
row1 |█████···············|
row0 |█████···············|
```

instance N 的标记按现有约定落在物理行 `5 - N` 的 col19：instance 2 → row3、instance 3 → row2（分隔行内）、
instance 5 → row0。由于条只占 col0..col18，标记永远不与条重叠。

## 7. 调度与状态机

### 7.1 daemon 新增状态

| 字段 | 类型 | 说明 |
|---|---|---|
| `quota_thread` | `Thread \| None` | 配额轮询线程 |
| `last_effect_finished_at` | `float` | 最近一次效果结束的时间戳。**daemon 启动时初始化为 `time.time()`**，使启动后立即显示配额条 |
| `last_snapshot` | `QuotaSnapshot \| None` | 最近一次成功拉到的快照（缓存） |
| `last_rendered` | `QuotaSnapshot \| None` | 最近一次画到屏幕上的快照 |
| `quota_needs_repaint` | `bool` | 效果抢过屏幕后置位，提示配额线程在空闲时重绘一次 |
| `quota_enabled` | `bool` | 功能开关 |

### 7.2 配额线程主循环

```
while daemon.running:
    sleep(1)
    if not quota_enabled: continue
    if effect_thread 存活:            continue   # 有活动效果 → 让位
    if now - last_effect_finished_at < takeover_delay: continue  # 完成信号保护期
    snapshot = get_quota_if_stale()     # 5min 缓存；失败返回旧快照或 None
    if snapshot is None:                continue   # 无数据 → 屏幕留黑
    if snapshot.differs_from(last_rendered) or quota_needs_repaint:
        paint(snapshot)                 # 内部置 last_rendered = snapshot
                                       #      quota_needs_repaint = False
```

`get_quota_if_stale()` 的行为：快照缓存过期（距上次成功请求超过 `poll_interval`）时请求接口；
请求失败则**返回旧快照**（若有）而不是 None —— 这样接口临时故障时屏幕继续显示上次的值，
不会因为一次网络抖动就丢掉画面。只有「从未成功拿到过数据」时才返回 None。

### 7.3 效果与配额条的交接

- 效果启动时：`quota_needs_repaint = True`（效果抢过了屏幕，回来后需要重画一次配额条）
- 效果线程结束时（`finally`）：`last_effect_finished_at = now`
- 配额条每次绘制前**无条件**先执行接管序列：

```
stop_cf                  ← 停掉设备端绿色呼吸（complete 状态用的 start_cf）
set_power ["on"]
activate_fx_mode [{"mode":"direct"}]
```

  然后再 `update_leds` 画条。

接管序列无条件执行，而不是靠状态位判断设备当前处于什么模式 —— 接管本身很罕见
（每次效果结束才一次），多出的两条命令可以忽略，换来的是不必维护「设备当前是什么模式」
这类容易失真的状态。`stop_cf` 不可省：`complete` 状态的绿呼吸是设备端无限循环，
不先停掉则 `update_leds` 画不上去。

### 7.4 「完成」信号与常驻条的共存

```
Stop hook ──► complete（设备端绿色呼吸，无限循环）
              │
              ├─ 0~20s   绿呼吸可见，配额线程处于保护期不接管
              └─ 20s 后   配额线程接管 → stop_cf → 画双条
```

`takeover_delay` 默认 20 秒，可通过配置调整，设 0 即立即接管。

### 7.5 命令配额占用

配额条仅在「百分比变化」或「刚从效果切回」时绘制一次，约 1 次 / 5 分钟。
对比现有 `command_interval`（1 秒 1 条 = 60/分钟）的节流上限，占用可忽略。

## 8. 配置

### 8.1 `config.json`（已列入 `.gitignore`，本次接上实际读取）

```json
{
  "ip": "192.168.1.100",
  "port": 55443,
  "instance": 2,
  "shared": 1,
  "quota": {
    "enabled": true,
    "api_base": "https://api.minimaxi.com",
    "api_key": "sk-你的key",
    "poll_interval": 300,
    "takeover_delay": 20
  }
}
```

`config.json.example` 同步更新为相同结构，`api_key` 留空，提交到仓库。

### 8.2 优先级

命令行参数 > 环境变量 > `config.json` > 内置默认值。

| 配置项 | 解析顺序 |
|---|---|
| `api_key` | `--quota-api-key` → `MINIMAX_API_KEY` → `config.json.quota.api_key` → `~/.claude/settings.json` 的 `env.ANTHROPIC_AUTH_TOKEN` |
| `ip` | `--ip` → `config.json.ip` → `None`（启动即报错退出，与现状一致） |
| `port` | `--port` → `config.json.port` → `55443` |
| `instance` | `--instance` → `config.json.instance` → `0`（不标记） |
| `shared` | `--shared` → `config.json.shared` → `1` |
| `api_base` | `--quota-api-base` → `config.json.quota.api_base` → `https://api.minimaxi.com` |
| `poll_interval` | `--quota-interval` → `config.json.quota.poll_interval` → `300` |
| `takeover_delay` | `config.json.quota.takeover_delay` → `20` |
| 开关 | `--no-quota` → `config.json.quota.enabled` → `true` |

最后一级 fallback 到 `~/.claude/settings.json` 是为本机用户准备的零配置路径（该处本就是 MiniMax 的 key）；
其他用户走 `config.json` 或 `MINIMAX_API_KEY` 环境变量。

现有 CLI 参数全部保留，原 plist 不改也能继续运行。

### 8.3 新增命令行参数

```
--config PATH           配置文件路径（默认：脚本同目录的 config.json）
--quota-api-key KEY     MiniMax API key
--quota-api-base URL    接口域名
--quota-interval SEC    轮询间隔（秒）
--no-quota              关闭配额条功能
```

## 9. 错误处理

| 情况 | 行为 |
|---|---|
| `api_key` 解析为空 | 不启动配额线程，记一条警告，daemon 正常服务现有效果 |
| API 超时 / 连接失败 | 抛 `QuotaError` → 保留 `last_snapshot` 继续显示旧值，记日志，5 分钟后重试 |
| HTTP 401 / `status_code=2049` | 同上，日志明确提示 key 无效 |
| HTTP 非 200 | 同上，日志记状态码 |
| 首次就失败（无旧快照） | 屏幕保持黑，daemon 正常运行，继续重试 |
| `model_remains` 为空 | `QuotaError` → 同上 |
| 设备不可达 | 走现有 `reconnect()` 机制 |
| 渲染/绘制异常 | 捕获并记日志，daemon 继续运行（与现有 hook 脚本的静默容错风格一致） |

**不清屏**是原则：接口故障不应导致屏幕熄灭或显示错误数据。

## 10. 测试

标准库 `unittest`，不引入第三方依赖。新增 `tests/test_quota.py`：

| 测试对象 | 用例 |
|---|---|
| `parse_remains` | 正常响应；`status_code != 0`；缺 `base_resp`；`model_remains` 为空/缺失；多条目时选 `general`；无 `general` 时取第一条；百分比越界 clamp；非数字按 0 |
| `level_color` | 100/50/49/20/19/0 各档；暖色阶与冷色阶分别验证 |
| `render_bar` | 0% / 50% / 100% 的填充像素数；row4+row3 属 5h、row1+row0 属周；col19 恒为黑；未填充像素为纯黑 |
| 配置 | `config.json` 解析；CLI > env > config 的优先级；文件缺失时用默认值 |

运行：`python3 -m unittest discover tests`

## 11. 改动清单

| 文件 | 改动 |
|---|---|
| `quota.py` | **新增** —— MiniMax 客户端 + 渲染纯函数 + 配色 |
| `yeelight-daemon.py` | 新增配额线程与调度状态；接入 `quota.py`；配置加载；`quota` 状态处理；`--quota-*` 参数 |
| `tests/test_quota.py` | **新增** |
| `tests/__init__.py` | **新增**（便于 `unittest discover`） |
| `config.json.example` | 增加 `quota` 段 |
| `yeelight-client.py` | `--state` 选项增加 `quota` |
| `README.md` / `README_CN.md` | 增加配额条说明与配置章节 |
| `EFFECTS.md` | 增加配额条效果描述 |

## 12. `quota` 调试状态

`python3 yeelight-client.py --state quota` 立即中断当前效果并绘制一次配额条，用于验证布局与配色。

实现：作为 daemon 的一个普通状态处理（`handle_command` 的 `states` 列表加入 `"quota"`），
处理步骤：

1. 复用现有的「中断当前效果线程」逻辑
2. 执行接管序列（`stop_cf` → `set_power` → `activate_fx_mode`），与 §7.3 一致
3. 取快照（缓存新鲜则用缓存，否则拉取），`render_bar` 后 `update_leds`
4. 置 `last_rendered = snapshot`、`quota_needs_repaint = False`、`last_effect_finished_at = now`

因为 `last_rendered` 已等于当前快照，配额线程在保护期结束后不会重复绘制。
若接口此刻不可用，则该命令不改变屏幕（保持现状），记日志。

## 13. 不在本期范围

- 不做历史用量曲线 / 趋势记录
- 不做多账号多套餐切换
- 不支持 UDP 55444 通道（现有 daemon 走 TCP 55443，保持不变）
- 不修改现有各状态的视觉效果

## 14. 参考资料

- MiniMax Token Plan 配额接口调研：`me-speaker/token_manager` 仓库的 `minimax-token-plan-api.md`
- MiniMax provider 实现细节（百分比语义、count 兼容形态）：
  `tddworks/ClaudeBar` 仓库 `docs/providers/minimax/design.md`
- Yeelight Cube Lite 参考实现：
  - `Max-src/yeelight-cube-lite`（Home Assistant 集成，UDP 55444 + TCP 55443 双通道、流式帧率建议 ≤5fps）
  - `VladFlorinIlie/YeelightMatrix`（Python 库 + HA 集成）
