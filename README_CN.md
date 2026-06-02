# yeelight-claude-hook

> Yeelight 灯光效果 for Claude Code - 在不同运行阶段显示视觉反馈

[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/jacobke/yeelight-claude-hook)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<img src="yeelight-cube-light.webp" alt="Yeelight Cube Lite" width="300">

**Yeelight Smart Lamp Cube Lite**

[English](README.md) | **中文**

## 功能特性

- 🌈 **视觉效果** - 不同状态显示不同灯光效果
- 🕯️ **蜡烛模式** - 思考时显示蜡烛闪烁效果
- 💚 **任务完成** - 绿色呼吸灯表示任务完成
- ⚡ **实时响应** - 效果可中断，新命令立即生效
- 🔌 **长连接** - Daemon 模式避免设备连接配额限制
- 🔢 **实例标记** - 土豪金像素显示 Claude Code 实例编号 (1-5)

## 效果预览

| 状态 | 效果 | 颜色 | 触发时机 |
|------|------|------|----------|
| start | START | 彩虹背景+白字 | 用户发送消息 |
| thinking | THINK | 暖黄-橙色 | 蜡烛火焰闪烁 |
| done | DONE | 柔和蓝色 | 渐入→保持→渐出 |
| wait | INPUT | 紫色 | 波浪效果 |
| complete | 绿色呼吸 | 绿色 | 内置呼吸效果（无限循环） |
| interrupt | ERROR | 红色 | 快闪 5 次 |
| end | END | 红色 | 渐出关灯 |

## 快速开始

### 1. 发现设备 IP

```bash
python3 discover.py
```

### 2. 配置开机自启

编辑 `com.yeelight.daemon.plist.template`：
- 修改 `/path/to/yeelight-daemon.py` 为实际路径
- 修改 `YOUR_YEELIGHT_IP` 为设备 IP
- （可选）设置实例编号 (1-20) 用于像素标记

```bash
cp com.yeelight.daemon.plist.template ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
```

**实例标记**：当运行多个 Claude Code 实例时，设置不同的 `--instance` 编号 (1-5)。最右边列会显示土豪金像素来标识当前活跃的实例。

| 实例 | 像素位置 |
|------|----------|
| 1 | 右上角 (第4行) |
| 2 | 右数第二行 (第3行) |
| 3 | 中间行 (第2行) |
| 4 | 右数第四行 (第1行) |
| 5 | 右下角 (第0行) |

### 3. 配置 Claude Code Hooks

在 `~/.claude/settings.json` 中添加：

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state start --duration 2", "type": "command" }]
    }],
    "PreToolUse": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state thinking", "type": "command" }]
    }],
    "PostToolUse": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state done", "type": "command" }]
    }],
    "Notification": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state wait", "type": "command" }]
    }],
    "Stop": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state complete", "type": "command" }]
    }],
    "StopFailure": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state interrupt", "type": "command" }]
    }],
    "PostToolUseFailure": [{
      "hooks": [{ "command": "python3 /path/to/yeelight-client.py --state interrupt", "type": "command" }]
    }]
  }
}
```

### 4. 验证

```bash
python3 yeelight-client.py --state done
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `yeelight-daemon.py` | 后台服务，保持 TCP 长连接 |
| `yeelight-client.py` | 客户端，通过 Unix Socket 通信 |
| `yeelight-hook.py` | 独立脚本模式（备用） |
| `discover.py` | 发现局域网内的 Yeelight 设备 |
| `com.yeelight.daemon.plist.template` | launchd 配置模板 |

## 架构说明

```
Claude Code Hooks → yeelight-client.py → Unix Socket → yeelight-daemon
                                                        ↓
                                                   Yeelight 设备
```

## 要求

- Yeelight 设备需开启"极客模式" (LAN Control / Developer Mode)
- Python 3（无需额外依赖）
- macOS 或 Linux

## 故障排查

详见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

### 快速排查

```bash
# 检查 daemon 是否运行
ls -la /tmp/yeelight.sock

# 重启 daemon
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 设备不可达
ping <设备IP>

# 手动测试
echo '{"state": "done"}' | nc -U /tmp/yeelight.sock
```

## 相关资源

- [TapHome Yeelight 兼容性说明](https://taphome.com/en/compatibility/yeelight/)
- [Yeelight 论坛 - 命令限制讨论](https://forum.yeelight.com/t/topic/15756/15)

## 许可证

[MIT License](LICENSE)
