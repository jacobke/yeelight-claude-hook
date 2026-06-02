# Yeelight "Client Quota Exceeded" 问题解决指南

## 问题背景

Yeelight 设备在 LAN（局域网）控制模式下有严格的命令频率限制：

- **每分钟命令数量限制**：约 60 次
- **并发连接数限制**：通常 4-5 个
- **超出限制时**：返回错误 `"client quota exceeded"`

### 错误表现

```json
{"id": 123, "error": {"code": -1, "message": "client quota exceeded"}}
```

## 问题原因

### 1. 频繁创建 TCP 连接

每次脚本调用都会创建新的 TCP 连接：

```
Hook 调用 → 新进程 → 新 TCP 连接 → 执行效果 → 关闭连接
```

Yeelight 设备的连接池有限，频繁创建/关闭连接会快速消耗配额。

### 2. 高帧率动画

点阵动画（如蜡烛效果、彩虹效果）如果帧率过高：

```
蜡烛效果: 10 fps × 60 秒 = 600 命令/分钟
彩虹效果: 5 fps × 60 秒 = 300 命令/分钟
```

远超设备限制。

## 解决方案

### 方案一：Daemon 模式（推荐）

使用单一长连接，避免频繁连接消耗：

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

**架构优势：**

| 特性 | 独立脚本模式 | Daemon 模式 |
|------|-------------|-------------|
| TCP 连接数 | 每次调用新建 | 单个长连接 |
| 连接配额消耗 | 高 | 低 |
| 命令频率控制 | 无 | 内置限制 |
| Hook 阻塞 | 可能 | 快速返回 |

**实现方式：**

1. **Daemon 服务** (`yeelight-daemon.py`)：
   - 保持 TCP 长连接
   - 通过 Unix Socket 接收命令
   - 内置频率限制（每秒最多 2 命令）

2. **Client 脚本** (`yeelight-client.py`)：
   - 快速调用，不阻塞
   - 静默失败（daemon 未运行时不报错）

3. **Launchd 自启**：
   ```xml
   <!-- ~/Library/LaunchAgents/com.yeelight.daemon.plist -->
   <key>RunAtLoad</key>
   <true/>
   <key>KeepAlive</key>
   <true/>
   ```

### 方案二：降低帧率

如果使用独立脚本模式，必须降低帧率：

```python
# 修改前
frames = int(duration * 10)  # 10 fps - 会触发 quota exceeded

# 修改后
frames = int(duration * 2)   # ~2 fps - 安全范围
time.sleep(0.5)              # 增加帧间隔
```

**帧率建议：**

| 效果类型 | 安全帧率 | 帧间隔 |
|----------|----------|--------|
| 蜡烛/呼吸 | 2 fps | 0.45-0.55s |
| 彩虹 | 2 fps | 0.5s |
| 波浪 | 2 fps | 0.5s |
| 渐出 | 15 帧 | 分散执行 |

## 实战案例：Claude Code Hooks

### 问题场景

为 Claude Code 配置 Yeelight 灯光效果，hooks 在不同阶段触发：

- `UserPromptSubmit` → start
- `PreToolUse` → thinking
- `PostToolUse` → done
- `Notification` → wait
- `Stop` → end

每个 hook 调用都会创建新连接，thinking 效果（蜡烛）更是长时间运行。

### 解决步骤

1. **创建 Daemon 服务**

   ```bash
   python3 yeelight-daemon.py --ip <设备IP> &
   ```

2. **配置 Hooks 使用 Client**

   ```json
   {
     "hooks": {
       "PreToolUse": [{
         "hooks": [{
           "command": "python3 yeelight-client.py --state thinking",
           "type": "command"
         }]
       }]
     }
   }
   ```

3. **配置开机自启**

   ```bash
   launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
   ```

## 相关资源

### TapHome Yeelight 兼容性说明

> **https://taphome.com/en/compatibility/yeelight/**

TapHome 是一个智能家居集成平台，提供了 Yeelight 设备的兼容性说明：

- Yeelight 支持 LAN 控制（极客模式）
- 设备需要开启 "LAN Control" 或 "Developer Mode"
- 同样受 API 限制影响，建议使用单一连接管理

### Yeelight 官方论坛讨论

> **https://forum.yeelight.com/t/topic/15756/15**

官方论坛确认了命令频率限制的存在，建议开发者：

- 控制命令发送频率
- 使用长连接而非频繁连接
- 避免在短时间内发送大量命令

## 最佳实践总结

| 实践 | 说明 |
|------|------|
| ✅ 使用单一长连接 | Daemon 模式复用 TCP 连接 |
| ✅ 内置频率限制 | 每秒最多 2 个命令 |
| ✅ 降低动画帧率 | 独立脚本时使用 2 fps |
| ✅ 静默失败 | Hook 不应阻塞或报错 |
| ✅ 快速重连机制 | 连接断开后自动重连 |
| ❌ 频繁创建连接 | 每次调用新建 TCP |
| ❌ 高帧率动画 | 超过 5 fps |
| ❌ 忽略错误响应 | quota exceeded 需处理 |

## 文件结构

```
yeelight/
├── yeelight-daemon.py           # Daemon 服务（长连接）
├── yeelight-client.py           # Client（Unix Socket）
├── yeelight-hook.py             # 独立脚本（备用）
├── discover.py                  # 设备发现工具
├── com.yeelight.daemon.plist    # launchd 配置（开机自启）
├── TROUBLESHOOTING.md           # 本文档
├── README.md                    # 使用说明
└── YEELIGHT_GUIDE.md            # API 指南
```

## 快速排查清单

```bash
# 1. 检查 daemon 是否运行
pgrep -f yeelight-daemon
ls -la /tmp/yeelight.sock

# 2. 检查设备网络
ping <设备IP>

# 3. 重启 daemon
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 4. 查看日志
tail -f /tmp/yeelight-daemon.log

# 5. 测试连接
echo '{"state": "done"}' | nc -U /tmp/yeelight.sock
```