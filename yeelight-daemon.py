#!/usr/bin/env python3
"""
Yeelight Daemon - 保持 TCP 长连接，支持效果中断

使用方式:
1. 启动 daemon: python3 yeelight-daemon.py --ip <设备IP> &
2. 发送命令: echo '{"state": "done"}' | nc -U /tmp/yeelight.sock
"""

import socket
import json
import base64
import time
import math
import random
import argparse
import sys
import os
import signal
import struct
import threading

# ============================================================================
# 配置
# ============================================================================

DEFAULT_IP = None  # 必须通过 --ip 参数或配置文件指定
DEFAULT_PORT = 55443
SOCKET_PATH = "/tmp/yeelight.sock"
ROWS, COLS = 5, 20

# ============================================================================
# 3x5 字体
# ============================================================================

FONT_3X5 = {
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
    'A': [[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'B': [[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    'C': [[1,1,1],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'D': [[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    'E': [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    'F': [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    'G': [[1,1,1],[1,0,0],[1,0,1],[1,0,1],[1,1,1]],
    'H': [[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'I': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'J': [[1,1,1],[0,1,0],[0,1,0],[1,1,0],[1,0,0]],
    'K': [[1,0,1],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'L': [[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'M': [[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'N': [[1,0,1],[1,1,1],[1,1,1],[1,1,1],[1,0,1]],
    'O': [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    'P': [[1,1,1],[1,0,1],[1,1,1],[1,0,0],[1,0,0]],
    'Q': [[1,1,1],[1,0,1],[1,0,1],[1,1,1],[0,1,1]],
    'R': [[1,1,1],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'S': [[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    'T': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'U': [[1,0,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    'V': [[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'W': [[1,0,1],[1,0,1],[1,0,1],[1,1,1],[1,0,1]],
    'X': [[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'Y': [[1,0,1],[1,0,1],[0,1,0],[0,1,0],[0,1,0]],
    'Z': [[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    ' ': [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
    '.': [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[1,0,0]],
    '!': [[0,1,0],[0,1,0],[0,1,0],[0,0,0],[0,1,0]],
}

# ============================================================================
# 工具函数
# ============================================================================

def hsv_to_rgb(h, s, v):
    if s == 0:
        return int(v*255), int(v*255), int(v*255)
    i = int(h * 6)
    f = (h * 6) - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    i %= 6
    if i == 0: return int(v*255), int(t*255), int(p*255)
    if i == 1: return int(q*255), int(v*255), int(p*255)
    if i == 2: return int(p*255), int(v*255), int(t*255)
    if i == 3: return int(p*255), int(q*255), int(v*255)
    if i == 4: return int(t*255), int(p*255), int(v*255)
    return int(v*255), int(p*255), int(q*255)

def render_centered(text, color, grid=None):
    if grid is None:
        grid = [(0,0,0)] * 100
    char_width = 3
    char_gap = 1
    total_width = len(text) * char_width + (len(text) - 1) * char_gap
    start_col = (20 - total_width) // 2

    col = start_col
    for ch in text:
        if ch in FONT_3X5:
            for row_idx, row_data in enumerate(FONT_3X5[ch]):
                phys_row = 4 - row_idx
                for bit_idx, val in enumerate(row_data):
                    if val:
                        px_col = col + bit_idx
                        if 0 <= px_col < 20:
                            idx = phys_row * 20 + px_col
                            grid[idx] = color
        col += char_width + char_gap
    return grid

def render_centered_with_bg(text, text_color, bg_color):
    grid = [bg_color] * 100
    char_width = 3
    char_gap = 1
    total_width = len(text) * char_width + (len(text) - 1) * char_gap
    start_col = (20 - total_width) // 2

    col = start_col
    for ch in text:
        if ch in FONT_3X5:
            for row_idx, row_data in enumerate(FONT_3X5[ch]):
                phys_row = 4 - row_idx
                for bit_idx, val in enumerate(row_data):
                    if val:
                        px_col = col + bit_idx
                        if 0 <= px_col < 20:
                            idx = phys_row * 20 + px_col
                            grid[idx] = text_color
        col += char_width + char_gap
    return grid

# ============================================================================
# Yeelight 连接 (长连接)
# ============================================================================

class YeelightDaemon:
    def __init__(self, ip, port=55443):
        self.ip = ip
        self.port = port
        self.sock = None
        self.running = True
        self.interrupted = False  # 效果中断标志
        self.effect_thread = None  # 当前效果线程
        self.command_count = 0
        self.last_command_time = 0
        self.lock = threading.Lock()  # 保护 socket 操作

    def connect(self):
        """连接设备"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, self.port))
            print(f"Connected to {self.ip}:{self.port}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}", file=sys.stderr)
            return False

    def reconnect(self):
        """重连"""
        self.close()
        time.sleep(1)
        return self.connect()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def send_command(self, method, params):
        """发送命令（带频率限制）"""
        if not self.sock:
            return False

        with self.lock:
            # 频率限制：每秒最多 2 个命令
            now = time.time()
            if now - self.last_command_time < 0.5:
                time.sleep(0.5 - (now - self.last_command_time))

            cmd = {"id": int(time.time() * 1000) % 10000, "method": method, "params": params}
            try:
                self.sock.send((json.dumps(cmd) + "\r\n").encode())
                self.command_count += 1
                self.last_command_time = time.time()
                return True
            except Exception as e:
                print(f"Send failed: {e}", file=sys.stderr)
                return False

    def send_pixels(self, grid):
        """发送像素数据"""
        payload = "".join(base64.b64encode(bytes(rgb)).decode() for rgb in grid)
        return self.send_command("update_leds", [payload])

    def activate_direct_mode(self):
        self.send_command("set_power", ["on"])
        time.sleep(0.1)
        self.send_command("activate_fx_mode", [{"mode": "direct"}])
        time.sleep(0.2)

    def check_interrupted(self):
        """检查是否被中断"""
        return self.interrupted or not self.running

    def interrupt(self):
        """中断当前效果"""
        self.interrupted = True

    # ========================================================================
    # 效果方法
    # ========================================================================

    def effect_off(self):
        """关灯"""
        for _ in range(2):
            if self.check_interrupted():
                return
            self.send_pixels([(0, 0, 0)] * 100)
            time.sleep(0.1)

    def effect_start(self, duration=2.0):
        """彩虹背景 + 白字"""
        frames = int(duration * 2)
        for i in range(frames):
            if self.check_interrupted():
                return
            grid = []
            for col in range(20):
                h = ((col / 20) + i * 0.05) % 1.0
                r, g, b = hsv_to_rgb(h, 0.6, 0.15)
                for row in range(5):
                    grid.append((r, g, b))
            render_centered("START", (255, 255, 255), grid)
            self.send_pixels(grid)
            time.sleep(0.5)

    def effect_thinking(self, duration=300):
        """蜡烛效果"""
        random.seed()
        frames = int(duration * 2)
        for i in range(frames):
            if self.check_interrupted():
                return
            grid = []
            base_hue = 0.08
            for col in range(20):
                for row in range(5):
                    hue = base_hue + random.uniform(-0.03, 0.04)
                    hue = max(0.02, min(0.15, hue))
                    sat = random.uniform(0.8, 1.0)
                    base_brightness = 0.6 - row * 0.08
                    flicker = random.uniform(-0.15, 0.2)
                    if random.random() < 0.08:
                        flicker += random.uniform(0.1, 0.25)
                    brightness = max(0.15, min(0.95, base_brightness + flicker))
                    r, g, b = hsv_to_rgb(hue, sat, brightness)
                    grid.append((r, g, b))
            render_centered("THINK", (255, 240, 200), grid)
            self.send_pixels(grid)
            time.sleep(random.uniform(0.45, 0.55))

    def effect_done(self):
        """柔和蓝色渐入渐出"""
        color = (0, 60, 120)

        # 渐入
        steps_in = 8
        for i in range(1, steps_in + 1):
            if self.check_interrupted():
                return
            brightness = i / steps_in
            tc = (int(color[0] * brightness), int(color[1] * brightness), int(color[2] * brightness))
            grid = render_centered("DONE", tc)
            self.send_pixels(grid)
            time.sleep(0.15)

        # 保持显示 2 秒
        for _ in range(10):
            if self.check_interrupted():
                return
            grid = render_centered("DONE", color)
            self.send_pixels(grid)
            time.sleep(0.2)

        # 渐出
        steps_out = 8
        for i in range(steps_out, 0, -1):
            if self.check_interrupted():
                return
            brightness = i / steps_out
            tc = (int(color[0] * brightness), int(color[1] * brightness), int(color[2] * brightness))
            grid = render_centered("DONE", tc)
            self.send_pixels(grid)
            time.sleep(0.15)

    def effect_wait(self, duration=300):
        """紫色波浪"""
        frames = int(duration * 2)
        for i in range(frames):
            if self.check_interrupted():
                return
            t = i * 0.5
            grid = render_centered("INPUT", (170, 0, 255))
            wave_row = int((t * 1.5) % 6) - 1
            for row in range(5):
                distance = abs(row - wave_row)
                brightness = {0: 1.0, 1: 0.8, 2: 0.5}.get(distance, 0.3)
                for col in range(20):
                    idx = row * 20 + col
                    r, g, b = grid[idx]
                    if r > 0 or g > 0 or b > 0:
                        grid[idx] = (int(r * brightness), int(g * brightness), int(b * brightness))
            self.send_pixels(grid)
            time.sleep(0.5)

    def effect_interrupt(self):
        """红色快闪"""
        grid_on = render_centered("ERROR", (255, 0, 0))
        grid_off = [(0,0,0)] * 100
        for _ in range(5):
            if self.check_interrupted():
                return
            self.send_pixels(grid_on)
            time.sleep(0.5)
            if self.check_interrupted():
                return
            self.send_pixels(grid_off)
            time.sleep(0.4)

    def effect_complete(self):
        """任务完成 - 内置绿色呼吸效果"""
        # 退出 direct mode
        self.send_command("set_power", ["on"])
        time.sleep(0.1)

        # 使用内置绿色呼吸效果
        # flow_string: 2000ms 亮 100%, 2000ms 暗 1%
        flow_string = "2000,1,65280,50,2000,1,65280,1"
        # count=0 无限循环, action=1 保持最后状态（亮）
        self.send_command("start_cf", [0, 1, flow_string])

    def effect_end(self, duration=2.0):
        """红色渐出"""
        steps = 15
        for i in range(steps, 0, -1):
            if self.check_interrupted():
                return
            brightness = i / steps
            tc = (int(255 * brightness), int(50 * brightness), int(50 * brightness))
            bc = (int(40 * brightness), int(5 * brightness), int(5 * brightness))
            grid = render_centered_with_bg("END", tc, bc)
            self.send_pixels(grid)
            time.sleep(duration / steps)
        self.effect_off()

    # ========================================================================
    # 命令处理
    # ========================================================================

    def run_effect(self, state, duration=5.0):
        """运行效果（在独立线程中）"""
        self.interrupted = False  # 重置中断标志

        # 对于点阵效果，确保先进入 direct mode
        # complete 使用内置效果，不需要 direct mode
        if state not in ["complete", "off"]:
            self.send_command("stop_cf", [])  # 停止内置效果
            time.sleep(0.1)
            self.send_command("set_power", ["on"])
            time.sleep(0.1)
            self.send_command("activate_fx_mode", [{"mode": "direct"}])
            time.sleep(0.2)

        handlers = {
            "start": lambda: self.effect_start(duration),
            "thinking": lambda: self.effect_thinking(duration),
            "done": lambda: self.effect_done(),
            "wait": lambda: self.effect_wait(duration),
            "interrupt": lambda: self.effect_interrupt(),
            "complete": lambda: self.effect_complete(),
            "end": lambda: self.effect_end(duration),
            "off": lambda: self.effect_off(),
        }

        handler = handlers.get(state)
        if handler:
            handler()

    def handle_command(self, cmd):
        """处理命令"""
        state = cmd.get("state")
        duration = cmd.get("duration", 5.0)

        if state not in ["start", "thinking", "done", "wait", "interrupt", "complete", "end", "off"]:
            return {"status": "error", "message": f"Unknown state: {state}"}

        # 中断当前效果
        if self.effect_thread and self.effect_thread.is_alive():
            self.interrupt()
            self.effect_thread.join(timeout=1.0)  # 等待最多 1 秒

        # 启动新效果线程
        self.effect_thread = threading.Thread(target=self.run_effect, args=(state, duration))
        self.effect_thread.daemon = True
        self.effect_thread.start()

        return {"status": "ok"}

    # ========================================================================
    # Unix Socket 服务器
    # ========================================================================

    def run_server(self):
        """运行 Unix Socket 服务器"""
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(5)
        server.settimeout(1.0)
        print(f"Listening on {SOCKET_PATH}")

        try:
            while self.running:
                try:
                    client, _ = server.accept()
                    try:
                        data = client.recv(1024).decode()
                        if data:
                            cmd = json.loads(data)
                            result = self.handle_command(cmd)
                            client.send((json.dumps(result) + "\n").encode())
                    except Exception as e:
                        print(f"Client error: {e}")
                    finally:
                        client.close()
                except socket.timeout:
                    continue
        finally:
            server.close()
            os.unlink(SOCKET_PATH)
            self.close()
            print("Daemon stopped")

    def stop(self):
        self.running = False
        self.interrupted = True


def main():
    parser = argparse.ArgumentParser(description="Yeelight Daemon")
    parser.add_argument("--ip", default=DEFAULT_IP)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    daemon = YeelightDaemon(args.ip, args.port)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        daemon.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not daemon.connect():
        return 1

    daemon.activate_direct_mode()
    daemon.run_server()

    return 0


if __name__ == "__main__":
    sys.exit(main())
