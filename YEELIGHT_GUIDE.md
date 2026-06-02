# Yeelight Cube Lite 控制指南

> 本文档介绍如何通过 LAN 协议控制 Yeelight Cube Lite 设备
>
> **注意**：文档中的 IP 地址 `192.168.1.100` 为示例，请替换为你的设备实际 IP

## 设备信息

| 项目 | 值 |
|------|-----|
| 设备名称 | Yeelight Cube Lite |
| 点阵规格 | 5 行 × 20 列 = **100 RGB LEDs** |
| 连接方式 | TCP，端口 55443 |
| 协议 | JSON-RPC over TCP |

## 像素布局

```
Row 4 (top):  pixels 80-99 ← left to right
Row 3:        pixels 60-79
Row 2:        pixels 40-59
Row 1:        pixels 20-39
Row 0 (bot):  pixels 0-19  ← pixel 0 = bottom-left
```

## 核心 API

### 1. 基础命令

```python
import socket
import json

def send_command(ip, method, params):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((ip, 55443))
    
    cmd = {"id": 1, "method": method, "params": params}
    sock.send((json.dumps(cmd) + "\r\n").encode())
    
    try:
        sock.settimeout(1)
        response = sock.recv(4096).decode()
        return response
    except:
        return None
    finally:
        sock.close()

# 示例
IP = "192.168.1.100"
send_command(IP, "set_power", ["on"])           # 开灯
send_command(IP, "set_power", ["off"])          # 关灯
send_command(IP, "set_bright", [100])           # 设置亮度 1-100
send_command(IP, "toggle", [])                  # 切换开关
```

### 2. 点阵控制（FX Direct 模式）

**激活直接控制模式**：
```python
# 参数必须是字典 {"mode": "direct"}，不是字符串！
send_command(IP, "activate_fx_mode", [{"mode": "direct"}])
```

**发送像素数据**：
```python
import base64

def encode_pixel(r, g, b):
    """将 RGB 编码为 base64"""
    return base64.b64encode(bytes([r, g, b])).decode("ascii")

def send_pixels(ip, grid):
    """
    发送 5x20 像素网格
    grid: 100 个 (r, g, b) 元组的列表
    """
    payload = "".join(encode_pixel(*rgb) for rgb in grid)
    send_command(ip, "update_leds", [payload])

# 示例：全红
grid = [(255, 0, 0)] * 100
send_pixels(IP, grid)
```

### 3. 内置效果（颜色流）

```python
def start_effect(ip, flow_string):
    """启动颜色流效果，无限循环"""
    send_command(ip, "set_power", ["on"])
    send_command(ip, "start_cf", [0, 1, flow_string])

def stop_effect(ip):
    """停止当前效果"""
    send_command(ip, "stop_cf", [])
```

## 内置效果列表

| 效果名 | Flow 参数 | 描述 |
|--------|-----------|------|
| `candle` | `200,1,16744448,80,300,1,16729600,60,150,1,16755200,90,250,1,16740352,70,200,1,16748544,85,350,1,16724736,50` | 🔥 烛光闪烁 |
| `police` | `150,1,16711680,100,150,1,255,100` | 🚨 红蓝交替 |
| `rainbow` | `1000,1,16711680,100,1000,1,65280,100,1000,1,255,100,1000,1,16776960,100,1000,1,16711935,100,1000,1,65535,100` | 🌈 彩虹渐变 |
| `disco` | `200,1,16711680,100,200,1,65280,100,200,1,255,100,200,1,16776960,100,200,1,16711935,100,200,1,65535,100` | 💃 迪斯科 |
| `alarm` | `100,1,16711680,100,100,1,16711680,1` | ⚠️ 红色警报 |
| `sunset` | `3000,1,4915330,100,3000,1,14364480,100,3000,1,16727040,100,3000,1,16744960,100` | 🌅 日落 |
| `night` | `5000,2,3000,5,5000,2,2700,3` | 🌙 夜间暖光 |
| `breathe_red` | `2000,1,16711680,100,2000,1,16711680,1` | 💗 红色呼吸 |
| `breathe_green` | `2000,1,65280,100,2000,1,65280,1` | 💚 绿色呼吸 |
| `breathe_blue` | `2000,1,255,100,2000,1,255,1` | 💙 蓝色呼吸 |

## Flow 参数格式

```
duration,mode,value,brightness,duration,mode,value,brightness,...
```

| 参数 | 说明 | 取值范围 |
|------|------|----------|
| duration | 持续时间 (ms) | 任意正整数 |
| mode | 颜色模式 | 1=RGB, 2=色温 |
| value | 颜色/色温值 | RGB: 0-16777215, 色温: 2700-6500 |
| brightness | 亮度 | 1-100 |

**RGB 值计算**：
```python
rgb_value = (R << 16) + (G << 8) + B

# 常用颜色
RED     = (255 << 16) + (0 << 8) + 0   = 16711680
GREEN   = (0 << 16) + (255 << 8) + 0   = 65280
BLUE    = (0 << 16) + (0 << 8) + 255   = 255
YELLOW  = (255 << 16) + (255 << 8) + 0 = 16776960
CYAN    = (0 << 16) + (255 << 8) + 255 = 65535
MAGENTA = (255 << 16) + (0 << 8) + 255 = 16711935
WHITE   = (255 << 16) + (255 << 8) + 255 = 16777215
```

## 完整示例

### 示例 1: 显示时钟

```python
import socket
import json
import base64
import time
from datetime import datetime

IP = "192.168.1.100"
ROWS, COLS = 5, 20

# 5x3 数字点阵 (row 0 = 顶部)
DIGITS = {
    '0': [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    '1': [[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2': [[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '3': [[1,1,1],[0,0,1],[1,1,1],[0,0,1],[1,1,1]],
    '4': [[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5': [[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    '6': [[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    '7': [[1,1,1],[0,0,1],[0,0,1],[0,0,1],[0,0,1]],
    '8': [[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    '9': [[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    ':': [[0],[1],[0],[1],[0]],
}

def send_cmd(sock, method, params):
    cmd = {"id": 1, "method": method, "params": params}
    sock.send((json.dumps(cmd) + "\r\n").encode())
    time.sleep(0.1)

def draw_time(grid, time_str, color=(0, 255, 100)):
    col = 2
    for ch in time_str:
        if ch in DIGITS:
            pattern = DIGITS[ch]
            for row, line in enumerate(pattern):
                actual_row = ROWS - 1 - row  # 翻转
                for i, val in enumerate(line):
                    if val:
                        c = col + i
                        idx = actual_row * COLS + c
                        if idx < 100:
                            grid[idx] = color
            col += 4 if ch != ':' else 2

# 连接并发送时钟
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((IP, 55443))

send_cmd(sock, "set_power", ["on"])
send_cmd(sock, "activate_fx_mode", [{"mode": "direct"}])

for _ in range(60):  # 运行 60 秒
    grid = [(0, 0, 0)] * 100
    draw_time(grid, datetime.now().strftime("%H:%M"))
    
    payload = "".join(base64.b64encode(bytes(rgb)).decode() for rgb in grid)
    send_cmd(sock, "update_leds", [payload])
    time.sleep(1)

sock.close()
```

### 示例 2: 启动内置效果

```python
import socket
import json

IP = "192.168.1.100"

EFFECTS = {
    "candle": "200,1,16744448,80,300,1,16729600,60,150,1,16755200,90,250,1,16740352,70,200,1,16748544,85,350,1,16724736,50",
    "police": "150,1,16711680,100,150,1,255,100",
    "rainbow": "1000,1,16711680,100,1000,1,65280,100,1000,1,255,100,1000,1,16776960,100,1000,1,16711935,100,1000,1,65535,100",
    "disco": "200,1,16711680,100,200,1,65280,100,200,1,255,100,200,1,16776960,100,200,1,16711935,100,200,1,65535,100",
}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((IP, 55443))

# 启动效果
cmd = {"id": 1, "method": "set_power", "params": ["on"]}
sock.send((json.dumps(cmd) + "\r\n").encode())

cmd = {"id": 2, "method": "start_cf", "params": [0, 1, EFFECTS["candle"]]}
sock.send((json.dumps(cmd) + "\r\n").encode())

sock.close()
# 效果会持续运行，断开连接后不停止
```

### 示例 3: 彩虹动画

```python
import socket
import json
import base64
import time
import math

IP = "192.168.1.100"

def hsv_to_rgb(h, s, v):
    if s == 0:
        return (int(v*255), int(v*255), int(v*255))
    i = int(h * 6)
    f = (h * 6) - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    i %= 6
    if i == 0: return (int(v*255), int(t*255), int(p*255))
    if i == 1: return (int(q*255), int(v*255), int(p*255))
    if i == 2: return (int(p*255), int(v*255), int(t*255))
    if i == 3: return (int(p*255), int(q*255), int(v*255))
    if i == 4: return (int(t*255), int(p*255), int(v*255))
    return (int(v*255), int(p*255), int(q*255))

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((IP, 55443))

cmd = {"id": 1, "method": "activate_fx_mode", "params": [{"mode": "direct"}]}
sock.send((json.dumps(cmd) + "\r\n").encode())
time.sleep(0.3)

for frame in range(100):
    grid = []
    for col in range(20):
        h = ((col / 20) + frame * 0.02) % 1.0
        r, g, b = hsv_to_rgb(h, 1.0, 1.0)
        for _ in range(5):  # 5 行相同颜色
            grid.append((r, g, b))
    
    payload = "".join(base64.b64encode(bytes(rgb)).decode() for rgb in grid)
    cmd = {"id": 10, "method": "update_leds", "params": [payload]}
    sock.send((json.dumps(cmd) + "\r\n").encode())
    time.sleep(0.05)

sock.close()
```

## 故障排查

### 1. 连接失败
```bash
# 检查设备是否在线
ping 192.168.1.100

# 检查端口是否开放
nc -zv 192.168.1.100 55443
```

### 2. 命令无响应
- Yeelight 设备不会对 `get_prop` 命令返回响应
- 使用 `set_` 和 `toggle` 等命令时，会返回 `{"id":X,"result":["ok"]}`

### 3. activate_fx_mode 返回错误
- 确保参数是 `{"mode": "direct"}`（字典），不是 `"direct"`（字符串）

### 4. 时钟显示上下颠倒
- 像素 row 0 是底部，row 4 是顶部
- 点阵定义的 row 0 是顶部，需要翻转：`actual_row = ROWS - 1 - row`

## 项目文件

```
yeelight-controller/
├── cube_lite.py     # Cube Lite 控制器类
├── controller.py    # 通用 Yeelight 控制器
├── cli.py           # 命令行工具
├── config.json      # 设备配置
├── SUMMARY.md       # 完整探索记录
└── YEELIGHT_GUIDE.md # 本文档
```

## 参考资源

- [Yeelight 开发者文档](https://www.yeelight.com/en_US/developer)
- [danielp370-msft/yeelight-cube](https://github.com/danielp370-msft/yeelight-cube) - API 发现来源
- [Max-src/yeelight-cube-lite](https://github.com/Max-src/yeelight-cube-lite) - Home Assistant 集成
