# yeelight-claude-hook

> Visual feedback for Claude Code using Yeelight RGB lights

[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/jacobke/yeelight-claude-hook)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<img src="yeelight-cube-light.webp" alt="Yeelight Cube Lite" width="300">

**Yeelight Smart Lamp Cube Lite**

**English** | [中文](README_CN.md)

## Features

- 🌈 **Visual Effects** - Different light effects for different states
- 🕯️ **Candle Mode** - Flickering candle effect while thinking
- 💚 **Task Complete** - Green breathing light on completion
- ⚡ **Real-time Response** - Interruptible effects, new commands take effect immediately
- 🔌 **Long Connection** - Daemon mode avoids device connection quota limits
- 🔢 **Instance Marking** - Gold pixel shows Claude Code instance number (1-5)

## Demo

| State | Effect | Trigger |
|-------|--------|---------|
| START | Rainbow background + white text | User sends message |
| THINK | Candle flickering | Tool execution starts |
| DONE | Blue fade in/out | Tool execution ends |
| INPUT | Purple wave | Waiting for user input |
| Complete | Green breathing (infinite) | Task completed successfully |
| ERROR | Red flashing | Error occurred |

## Quick Start

### 1. Discover Device IP

```bash
python3 discover.py
```

### 2. Configure Auto-start

Edit `com.yeelight.daemon.plist.template`:
- Update path to `yeelight-daemon.py`
- Update device IP address
- (Optional) Set instance number (1-20) for pixel marking

```bash
cp com.yeelight.daemon.plist.template ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
```

**Instance Marking**: When running multiple Claude Code instances, set different `--instance` numbers (1-5). A gold pixel will appear at the rightmost column to identify which instance is active.

| Instance | Pixel Position |
|----------|----------------|
| 1 | Top-right corner (row 4) |
| 2 | 2nd row from top (row 3) |
| 3 | Middle row (row 2) |
| 4 | 4th row from top (row 1) |
| 5 | Bottom-right corner (row 0) |

### 3. Configure Claude Code Hooks

Add to `~/.claude/settings.json`:

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

### 4. Test

```bash
python3 yeelight-client.py --state done
```

## Files

| File | Description |
|------|-------------|
| `yeelight-daemon.py` | Background service with TCP connection |
| `yeelight-client.py` | Client for Unix Socket communication |
| `yeelight-hook.py` | Standalone script (not recommended) |
| `discover.py` | Discover Yeelight devices on LAN |
| `com.yeelight.daemon.plist.template` | launchd template |

## Architecture

```
Claude Code Hooks → yeelight-client.py → Unix Socket → yeelight-daemon
                                                        ↓
                                                   Yeelight Device
```

## Requirements

- Yeelight device with LAN Control enabled (Geek Mode)
- Python 3 (no additional dependencies)
- macOS or Linux

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

## Resources

- [TapHome Yeelight Compatibility](https://taphome.com/en/compatibility/yeelight/)
- [Yeelight Forum - Command Limits](https://forum.yeelight.com/t/topic/15756/15)

## License

[MIT License](LICENSE)
