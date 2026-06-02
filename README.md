# yeelight-claude-hook

> Yeelight 灯光效果 for Claude Code - 在不同运行阶段显示视觉反馈

![Demo](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

![Yeelight Cube Lite](yeelight-cube-light.webp)

**English** | [中文文档](README_CN.md)

## 功能特性

- 🌈 **视觉效果**：不同状态显示不同灯光效果
- 🕯️ **蜡烛模式**：思考时显示蜡烛闪烁效果
- 💚 **任务完成**：绿色呼吸灯表示任务完成
- ⚡ **实时响应**：效果可中断，新命令立即生效
- 🔌 **长连接**：Daemon 模式避免设备连接配额限制

## 效果预览

| 状态 | 效果 | 触发时机 |
|------|------|----------|
| START | 彩虹背景 + 白字 | 用户发送消息 |
| THINK | 蜡烛火焰闪烁 | 工具执行前 |
| DONE | 柔和蓝色渐变 | 工具执行后 |
| INPUT | 紫色波浪 | 等待用户输入 |
| 绿色呼吸 | 内置呼吸效果 | 任务完成 |
| ERROR | 红色快闪 | 异常中断 |
| END | 红色渐出关灯 | 手动关闭 |

---

## 新机器配置步骤

### 1. 克隆项目

```bash
git clone <repo_url> /path/to/yeelight
cd /path/to/yeelight
```

### 2. 发现设备 IP

```bash
python3 discover.py
```

### 3. 配置 launchd

编辑 `com.yeelight.daemon.plist.template`：

1. 修改 `/path/to/yeelight-daemon.py` 为实际路径
2. 修改 `YOUR_YEELIGHT_IP` 为设备 IP

复制到 LaunchAgents：

```bash
cp com.yeelight.daemon.plist.template ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
```

### 4. 配置 Claude Code Hooks

编辑 `~/.claude/settings.json`，添加 hooks 配置（见下方）

### 5. 验证

```bash
python3 yeelight-client.py --state done
```

---

## 快速配置

### 1. 确认灯的 IP 地址

```bash
python3 discover.py
```

### 2. 配置开机自启

复制 launchd 配置文件：

```bash
# 编辑 plist 文件，修改 IP 地址
cp com.yeelight.daemon.plist ~/Library/LaunchAgents/

# 加载服务
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 查看状态
launchctl list | grep yeelight
```

**手动启动（调试）：**

```bash
python3 yeelight-daemon.py --ip <设备IP>
```

### 3. Claude Code Hooks 配置

在 `~/.claude/settings.json` 中添加：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state start --duration 2",
            "type": "command"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state thinking",
            "type": "command"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state done",
            "type": "command"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state wait",
            "type": "command"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state complete",
            "type": "command"
          }
        ]
      }
    ],
    "StopFailure": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state interrupt",
            "type": "command"
          }
        ]
      }
    ],
    "PostToolUseFailure": [
      {
        "hooks": [
          {
            "command": "python3 /path/to/yeelight-client.py --state interrupt",
            "type": "command"
          }
        ]
      }
    ]
  }
}
```

### 4. 测试效果

```bash
# 测试各效果（需要 daemon 运行）
python3 yeelight-client.py --state start --duration 2
python3 yeelight-client.py --state thinking --duration 10
python3 yeelight-client.py --state done
python3 yeelight-client.py --state wait --duration 10
python3 yeelight-client.py --state complete
python3 yeelight-client.py --state interrupt
python3 yeelight-client.py --state end
python3 yeelight-client.py --state off

# 或直接使用 Unix socket
echo '{"state": "done"}' | nc -U /tmp/yeelight.sock
```

## 效果说明

| 状态 | 效果 | 颜色 | 动画 | 触发时机 |
|------|------|------|------|----------|
| start | START | 彩虹背景+白字 | 彩虹流动 2 秒 | 用户发送消息 |
| thinking | THINK | 暖黄-橙色 | 蜡烛火焰闪烁 | 工具执行前 |
| done | DONE | 柔和蓝色 | 渐入→保持→渐出 | 工具执行后 |
| wait | INPUT | 紫色 | 波浪效果 | 等待用户输入 |
| complete | 绿色呼吸 | 绿色 | 内置呼吸效果（无限循环） | 对话正常结束（任务完成） |
| interrupt | ERROR | 红色 | 快闪 5 次 | 工具失败/异常 |
| end | END | 红色 | 渐出关灯 | 手动关闭 |
| off | - | - | 关灯 | 手动关闭 |

**效果特点：**

- 效果之间**自然过渡**，不主动关灯
- 只有 `end` 和 `off` 才会真正熄灭
- `complete` 使用 Yeelight 内置效果，其他使用点阵 direct mode
- 新命令会**立即中断**当前效果

## 文件清单

| 文件 | 说明 |
|------|------|
| `yeelight-daemon.py` | 后台服务，保持 TCP 长连接 |
| `yeelight-client.py` | 客户端，通过 Unix Socket 通信 |
| `yeelight-hook.py` | 独立脚本模式（备用，不推荐日常使用） |
| `discover.py` | 发现局域网内的 Yeelight 设备 |
| `com.yeelight.daemon.plist` | launchd 配置文件（开机自启） |
| `YEELIGHT_GUIDE.md` | Yeelight API 开发指南 |
| `TROUBLESHOOTING.md` | "quota exceeded" 问题解决指南 |

## 架构说明

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code Hooks                                       │
│    ↓                                                     │
│  yeelight-client.py ──→ Unix Socket ──→ yeelight-daemon │
│    (轻量调用)                    (单个 TCP 长连接)         │
│                                        ↓                 │
│                                   Yeelight 设备           │
└─────────────────────────────────────────────────────────┘
```

**优势：**

- 单个 TCP 长连接，不消耗连接配额
- 命令频率限制在 daemon 内部处理（每秒最多 2 命令）
- client 调用快速返回，不阻塞 hook
- 支持效果中断，新命令立即生效

## 管理命令

```bash
# 查看服务状态
launchctl list | grep yeelight

# 重启服务
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 查看日志
tail -f /tmp/yeelight-daemon.log

# 检查 daemon 是否运行
ls -la /tmp/yeelight.sock
pgrep -f yeelight-daemon
```

## 要求

- Yeelight 设备需开启 "极客模式" (LAN Control / Developer Mode)
- Python 3（无需额外依赖，仅使用标准库）
- macOS（使用 launchd 自启）

## 故障排查

详见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

### 快速排查

```bash
# Daemon 未运行
ls -la /tmp/yeelight.sock

# 重启 daemon
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 设备不可达（切换网络后）
ping <设备IP>

# 手动测试
echo '{"state": "done"}' | nc -U /tmp/yeelight.sock
```

## 相关资源

- [TapHome Yeelight 兼容性说明](https://taphome.com/en/compatibility/yeelight/)
- [Yeelight 论坛 - 命令限制讨论](https://forum.yeelight.com/t/topic/15756/15)

## 致谢

- Yeelight 开发者 API
- [Claude Code](https://claude.ai/code) by Anthropic

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

[MIT License](LICENSE)