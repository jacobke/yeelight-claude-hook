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

## 设备假死（无响应）的诊断与缓解

### 症状

设备接受 TCP 连接、TCP socket 仍是 `ESTABLISHED`，但对所有 LAN 命令**完全无响应**：

- `get_prop` / `set_power` / `toggle` / `set_music` 全部超时
- App 控制正常
- 唯一恢复办法：**断电重启**

### 根因（假说）：TCP 接收缓冲区填满

Yeelight 设备会对每个命令回 `{"id":X,"result":["ok"]}`，并在状态变化时主动推送 `props` 通知。但当前代码的两个发送端都**只 send、不 recv**：

| 文件 | 函数 | 行为 |
|------|------|------|
| `yeelight-daemon.py:205` | `send_command` | `sock.send(...)` 后立即返回，不读响应 |
| `yeelight-hook.py:214` | `send_command` | 同上 |

设备端的 TCP 发送缓冲区是有限的（macOS 默认 ~64KB）。每个响应约 30-50 字节，每个 `props` 通知约 50-100 字节。**长时间运行后，设备端的 send buffer 被填满，TCP 流量控制会阻止设备继续处理新命令**，表现为"假死"。`lsof` 看到连接还是 ESTABLISHED，但其实设备已经停止处理。

### 缓解措施

**临时缓解**：电源重启（每次都管用，但治标不治本）。

**代码层修复**（建议但未实施）：在 daemon 里加一个 reader 线程，循环 `sock.recv()` 清空缓冲区并丢弃响应：

```python
def _reader_loop(self):
    """后台读取响应，防止设备端 send buffer 填满导致假死"""
    while self.running:
        try:
            self.sock.settimeout(1.0)
            data = self.sock.recv(4096)
            if not data:
                # 设备关闭了连接，重连
                self.reconnect()
        except socket.timeout:
            continue
        except Exception:
            self.reconnect()

# 在 connect() 成功后启动：
self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
self.reader_thread.start()
```

### 排查注意事项

**用错探针会被误判为"假死"。** Yeelight 协议规定：
- ✅ `set_*` / `toggle` 会返回响应
- ❌ `get_prop` **不会**返回响应（设备协议设计如此，见 `YEELIGHT_GUIDE.md:304-305`）

所以**正确的连通性测试**是：

```bash
python3 -c "
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
s.connect(('192.168.2.6', 55443))
s.send((json.dumps({'id':1,'method':'set_power','params':['on','smooth',500]}) + '\r\n').encode())
print(s.recv(1024).decode().strip())  # 期望: {\"id\":1,\"result\":[\"ok\"]}
"
```

如果 `set_power` 也不响应，才是真正的"假死"。

## 多台电脑 / 多个 daemon 共享同一设备

如果多台电脑（或同一台电脑上跑多个 daemon 实例）共享同一台 Yeelight 灯，需要用 `--shared N` 参数让每个 daemon 按数量均分命令配额：

```bash
# 2 台电脑共享 → 每台 daemon 加 --shared 2（每 daemon 30 命令/分钟）
# 注意：每台电脑都需要手动设置相同的 N 值（daemon 之间无自动协商）
python3 yeelight-daemon.py --ip 192.168.x.x --shared 2
```

plist 中：

```xml
<string>--shared</string>
<string>2</string>
```

**计算方式**：`每 daemon 命令间隔 = N 秒`，因此 `每 daemon 命令速率 = 60/N 命令/分钟`。Yeelight 设备总配额约 60 命令/分钟，多 daemon 总和不应超过这个值。

**未设置 `--shared` 的后果**：每 daemon 按默认 60/分钟发送，2 台合计 120/分钟，会触发设备的命令频率限制并加速假死。