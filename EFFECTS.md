# Yeelight Hook 效果说明

> Claude Code 运行阶段与 Yeelight 灯光效果的映射

## Hook 绑定

| Claude Code Hook | 触发时机 | Yeelight 状态 |
|------------------|----------|---------------|
| `UserPromptSubmit` | 用户发送消息 | `start` |
| `PreToolUse` | 工具执行前 | `thinking` |
| `PostToolUse` | 工具执行后 | `done` |
| `Notification` | 等待用户输入 | `wait` |
| `Stop` | 对话结束 | `end` |
| `StopFailure` | 停止失败 | `interrupt` |
| `PostToolUseFailure` | 工具执行失败 | `interrupt` |

> **注意**: THINK 默认持续 5 分钟，足够覆盖大多数操作。下一个 hook 会覆盖当前显示。

## 效果详情

### START (开始)
- **颜色**: 彩虹背景 + 白色文字
- **文字**: `START`
- **动画**: 背景彩虹色缓慢流动，文字静止居中
- **持续**: 5秒

### THINK (思考中)
- **颜色**: 柔和暖色调（暖黄到橙色），低饱和度
- **文字**: `THINK`
- **动画**: 每个字符不同颜色，颜色缓慢流动，亮度 20%-60% 呼吸变化
- **持续**: 由 hook 参数决定，默认 5 分钟

### DONE (完成一步)
- **颜色**: 蓝色 `(0, 100, 180)`
- **文字**: `DONE`
- **动画**: 脉冲闪烁，亮-暗循环 3 次
- **持续**: 约 3.6 秒 (每次脉冲 0.6 秒)

### WAIT (等待用户)
- **颜色**: 紫色 `(170, 0, 255)`
- **文字**: `INPUT`
- **动画**: 波浪效果，亮带从顶部向底部扫过
- **持续**: 由 hook 参数决定，默认 5 分钟

### STOP (中断/错误)
- **颜色**: 纯红色 `(255, 0, 0)`
- **文字**: `ERROR`
- **动画**: 脉冲闪烁 5 次，每次 0.4 秒
- **持续**: 约 4 秒
- **触发**: 工具执行失败 (`PostToolUseFailure`) 或停止失败 (`StopFailure`)

### END (结束)
- **颜色**: 红色文字 `(255, 80, 80)` + 暗红背景 `(40, 5, 5)`
- **文字**: `END`
- **动画**: 文字和背景同时渐出，最后关灯
- **持续**: 3 秒
- **触发**: 对话结束 (正常/错误/Token限制)

---

## 设计演进

### 原始设计 vs 最终实现

| 状态 | 原始设计 | 最终实现 | 变更原因 |
|------|----------|----------|----------|
| **start** | 滚动 ">START>" + 彩虹 | 静态居中 + 彩虹背景 | 设备处理连续命令有瓶颈 |
| **thinking** | 滚动 "THINKING..." + 呼吸 | 柔和暖色调流动 + 呼吸 | 更动感、更柔和 |
| **done** | 脉冲 "DONE" | 脉冲 3 次 0.6 秒 | 效果更明显 |
| **wait** | 波浪 "WAIT INPUT" | 波浪 "INPUT" | 文字过长，波浪效果保留 |
| **interrupt** | 橙色脉冲 "STOP" 3 次 | 红色脉冲 "ERROR" 5 次 | 颜色更明显，语义更清晰 |
| **end** | 渐出 "END" | 渐出 + 暗红背景 + 关灯 | 视觉效果更完整 |

### 关键发现

1. **滚动效果不可行**
   - 设备处理连续命令有瓶颈
   - 每秒最多稳定处理 5 帧
   - 循环滚动时会在第 2 遍卡住

2. **文字宽度限制**
   - 矩阵只有 20 列
   - 3x5 字体 + 1 列间距 = 每字符 4 列
   - 最多显示 5 个字符：`20 / 4 = 5`

3. **居中计算**
   - `起始列 = (20 - 总宽度) // 2`
   - 总宽度需要微调才能完美居中

### Bug 修复记录

| 日期 | 问题 | 修复 |
|------|------|------|
| 2026-06-02 | `effect_breathing` 函数第 262-264 行残留代码引用未定义变量 `c`，导致 THINK 效果失败 | 删除残留代码 |
| 2026-06-02 | INTERRUPT 橙色 `(255,100,0)` 视觉效果不明显 | 改为纯红色 `(255,0,0)`，脉冲从 3 次增加到 5 次 |

---

## 字体定义

使用 3x5 点阵字体，每个字符占 3 列，字符间距 1 列。

```
T:      H:      I:      N:      K:      W:      A:
███     █ █     ███     █ █     █ █     █ █     ███
 █      █ █      █      ███     █ █     █ █     █ █
 █      ███      █      ███     ██      █ █     ███
 █      █ █      █      ███     █ █     ███     █ █
 █      █ █     ███     █ █     █ █     █ █     █ █
```

---

## 配置示例

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/yeelight-hook.py --state thinking"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/yeelight-hook.py --state start"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/yeelight-hook.py --state done"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/yeelight-hook.py --state wait"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/yeelight-hook.py --state end"
          }
        ]
      }
    ]
  }
}
```

## 手动测试

```bash
python3 yeelight-hook.py --state start --duration 3
python3 yeelight-hook.py --state thinking --duration 5
python3 yeelight-hook.py --state done
python3 yeelight-hook.py --state wait --duration 5
python3 yeelight-hook.py --state interrupt
python3 yeelight-hook.py --state end
python3 yeelight-hook.py --state off
```
