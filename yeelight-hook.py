#!/usr/bin/env python3
"""
Yeelight Hook for Claude Code
为 Claude Code 的不同运行阶段显示灯光效果

效果列表:
- start:    彩虹背景 + 白字 "START"
- thinking: 暖色调呼吸灯 "THINK" (暖黄到橙色流动)
- done:     蓝色脉冲闪烁 "DONE"
- wait:     紫色波浪 "INPUT"
- interrupt: 红色脉冲闪烁 "ERROR"
- end:      红色渐暗 "END"
- off:      关闭
"""

import socket
import json
import base64
import time
import math
import argparse
import sys
import struct

# ============================================================================
# 配置
# ============================================================================

DEFAULT_IP = None  # 必须通过 --ip 参数指定
DEFAULT_PORT = 55443
ROWS, COLS = 5, 20

# ============================================================================
# 3x5 字体 (row 0 = 顶部)
# ============================================================================

FONT_3X5 = {
    # 数字
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
    # 字母
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
    # 符号
    ' ': [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
    '.': [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[1,0,0]],
    '!': [[0,1,0],[0,1,0],[0,1,0],[0,0,0],[0,1,0]],
}

# ============================================================================
# 工具函数
# ============================================================================

def hsv_to_rgb(h, s, v):
    """HSV 转 RGB"""
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
    """居中渲染文字"""
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
    """居中渲染文字带背景"""
    grid = [bg_color] * 100  # 先填充背景
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

def render_centered_rainbow_soft(text, hue_offset, saturation, base_brightness):
    """渲染柔和暖色调文字 - 暖黄到橙色系"""
    grid = [(0, 0, 0)] * 100
    char_width = 3
    char_gap = 1
    total_width = len(text) * char_width + (len(text) - 1) * char_gap
    start_col = (20 - total_width) // 2

    col = start_col
    for ch in text:
        if ch in FONT_3X5:
            # 暖色调：黄-橙色系 (hue: 0.1-0.25)
            h = 0.1 + (hue_offset + col * 0.01) % 0.15
            r, g, b = hsv_to_rgb(h, saturation, base_brightness)

            for row_idx, row_data in enumerate(FONT_3X5[ch]):
                phys_row = 4 - row_idx
                for bit_idx, val in enumerate(row_data):
                    if val:
                        px_col = col + bit_idx
                        if 0 <= px_col < 20:
                            idx = phys_row * 20 + px_col
                            grid[idx] = (r, g, b)
        col += char_width + char_gap
    return grid

# ============================================================================
# Yeelight 连接
# ============================================================================

class Yeelight:
    def __init__(self, ip, port=55443):
        self.ip = ip
        self.port = port
        self.sock = None

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(2)  # 缩短超时，快速失败
            self.sock.connect((self.ip, self.port))
            return True
        except socket.timeout:
            # 静默失败，网络不可达是正常情况
            return False
        except OSError as e:
            # 网络不可达、主机不存在等，静默失败
            if e.errno in (51, 65, 113, 10065, 101):  # ENETUNREACH, EHOSTUNREACH, etc.
                return False
            # 其他错误也静默处理
            return False
        except Exception:
            # 任何其他错误都静默失败，不影响 Claude Code 运行
            return False

    def close(self):
        if self.sock:
            try:
                # 强制立即关闭连接，不等待
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                     struct.pack('ii', 1, 0))  # linger=0, 立即关闭
                self.sock.close()
            except:
                pass
            self.sock = None

    def send_command(self, method, params):
        if not self.sock:
            return
        cmd = {"id": int(time.time() * 1000) % 10000, "method": method, "params": params}
        try:
            self.sock.send((json.dumps(cmd) + "\r\n").encode())
        except:
            pass

    def activate_direct_mode(self):
        self.send_command("set_power", ["on"])
        time.sleep(0.05)
        self.send_command("activate_fx_mode", [{"mode": "direct"}])
        time.sleep(0.1)

    def send_pixels(self, grid):
        payload = "".join(base64.b64encode(bytes(rgb)).decode() for rgb in grid)
        self.send_command("update_leds", [payload])

# ============================================================================
# 动画效果
# ============================================================================

def effect_rainbow_text(yeelight, text, duration=3.0):
    """彩虹背景 + 白色文字（降低帧率避免命令限制）"""
    frames = int(duration * 2)  # 每秒约 2 帧

    for i in range(frames):
        # 彩虹背景 (暗)
        grid = []
        for col in range(20):
            h = ((col / 20) + i * 0.05) % 1.0  # 加快颜色变化补偿低帧率
            r, g, b = hsv_to_rgb(h, 0.6, 0.15)
            for row in range(5):
                grid.append((r, g, b))

        # 亮白色文字
        render_centered(text, (255, 255, 255), grid)
        yeelight.send_pixels(grid)
        time.sleep(0.5)  # 增加帧间隔

def effect_breathing(yeelight, text, color, duration=5.0):
    """呼吸灯效果 - 柔和暖色调，duration=0 时无限循环"""
    if duration <= 0:
        duration = 999999  # 无限循环
    frames = int(duration * 5)
    i = 0

    while i < frames:
        # 色相偏移（暖黄到橙色）
        hue_offset = i * 0.01
        # 低饱和度
        saturation = 0.5
        # 亮度呼吸 20%-60%
        brightness = 0.2 + 0.4 * (0.5 + 0.5 * math.sin(i * 0.25))

        grid = render_centered_rainbow_soft(text, hue_offset, saturation, brightness)
        yeelight.send_pixels(grid)
        time.sleep(0.2)
        i += 1

def effect_candle(yeelight, text, duration=300):
    """蜡烛灯效果 - 暖色调随机闪烁，模拟火焰，duration=0 时无限循环

    注意：Yeelight 设备有命令频率限制（约每分钟 60 次）
    所以帧率设置为每秒约 2 帧，避免 quota exceeded
    """
    import random
    random.seed()  # 使用系统时间初始化随机种子

    if duration <= 0:
        duration = 999999
    # 每秒约 2 帧，避免命令频率限制
    frames = int(duration * 2)

    for i in range(frames):
        grid = []

        # 基础火焰颜色：暖黄到橙红 (hue: 0.05-0.12)
        base_hue = 0.08

        for col in range(20):
            for row in range(5):
                # 随机色相偏移：模拟火焰颜色变化
                hue = base_hue + random.uniform(-0.03, 0.04)
                hue = max(0.02, min(0.15, hue))  # 限制在暖色范围

                # 随机饱和度：80%-100%
                sat = random.uniform(0.8, 1.0)

                # 随机亮度：模拟火焰闪烁
                # 底部稍亮，顶部更暗（模拟火焰形态）
                base_brightness = 0.6 - row * 0.08
                flicker = random.uniform(-0.15, 0.2)

                # 偶尔更亮的闪烁（模拟火焰爆燃）
                if random.random() < 0.08:
                    flicker += random.uniform(0.1, 0.25)

                brightness = base_brightness + flicker
                brightness = max(0.15, min(0.95, brightness))

                r, g, b = hsv_to_rgb(hue, sat, brightness)
                grid.append((r, g, b))

        # 渲染文字：亮黄白色，与火焰对比
        text_color = (255, 240, 200)
        render_centered(text, text_color, grid)

        yeelight.send_pixels(grid)

        # 增加帧间隔到约 0.5 秒，避免命令频率限制
        time.sleep(random.uniform(0.45, 0.55))

    return grid

def effect_pulse(yeelight, text, color, pulses=3, pulse_duration=0.8):
    """脉冲闪烁（增加间隔避免命令限制）"""
    grid_on = render_centered(text, color)
    grid_off = [(0,0,0)] * 100

    for _ in range(pulses):
        yeelight.send_pixels(grid_on)
        time.sleep(pulse_duration)
        yeelight.send_pixels(grid_off)
        time.sleep(pulse_duration * 0.8)

def effect_fade_out(yeelight, text, color, duration=2.0, bg_color=(40, 5, 5)):
    """渐出效果 - 带背景，最后关灯（减少帧数避免命令限制）"""
    steps = 15  # 减少帧数

    for i in range(steps, 0, -1):
        brightness = i / steps
        r, g, b = color
        tc = (int(r * brightness), int(g * brightness), int(b * brightness))
        bc = (int(bg_color[0] * brightness), int(bg_color[1] * brightness), int(bg_color[2] * brightness))

        grid = render_centered_with_bg(text, tc, bc)
        yeelight.send_pixels(grid)
        time.sleep(duration / steps)

    # 最后发送全黑像素（direct mode 下这就是"关灯"）
    for _ in range(2):  # 发送 2 次确保生效
        yeelight.send_pixels([(0, 0, 0)] * 100)
        time.sleep(0.1)

def effect_wave(yeelight, text, color, duration=300):
    """波浪效果 - 波浪从顶部向底部扫过（降低帧率避免命令限制）"""
    frames = int(duration * 2)  # 每秒约 2 帧
    r0, g0, b0 = color

    for i in range(frames):
        t = i * 0.5  # 时间，补偿低帧率

        # 渲染文字
        grid = render_centered(text, color)

        # 波浪位置：从顶部(row4)向底部(row0)移动
        wave_row = int((t * 1.5) % 6) - 1  # 范围 -1 到 4

        # 对每行应用波浪亮度调制
        for row in range(5):
            distance = abs(row - wave_row)

            if distance == 0:
                brightness = 1.0   # 波浪中心行最亮
            elif distance == 1:
                brightness = 0.8   # 相邻行较亮
            elif distance == 2:
                brightness = 0.5   # 较远行中等
            else:
                brightness = 0.3   # 远行较暗

            for col in range(20):
                idx = row * 20 + col
                r, g, b = grid[idx]
                if r > 0 or g > 0 or b > 0:
                    grid[idx] = (int(r * brightness), int(g * brightness), int(b * brightness))

        yeelight.send_pixels(grid)
        time.sleep(0.5)  # 增加帧间隔

# ============================================================================
# 状态处理
# ============================================================================

def state_start(yeelight, duration=2.0):
    """开始状态 - 彩虹背景 + 白字"""
    effect_rainbow_text(yeelight, "START", duration)

def state_thinking(yeelight, duration=300):
    """思考状态 - 蜡烛灯效果，默认 5 分钟"""
    effect_candle(yeelight, "THINK", duration)

def state_done(yeelight, duration=1.0):
    """完成状态 - 蓝色脉冲 3 次"""
    effect_pulse(yeelight, "DONE", (0, 100, 180), pulses=3, pulse_duration=0.8)

def state_wait(yeelight, duration=300):
    """等待状态 - 紫色波浪"""
    effect_wave(yeelight, "INPUT", (170, 0, 255), duration)

def state_interrupt(yeelight, duration=1.0):
    """中断状态 - 红色快闪 5 次"""
    effect_pulse(yeelight, "ERROR", (255, 0, 0), pulses=5, pulse_duration=0.5)

def state_end(yeelight, duration=2.0):
    """结束状态 - 红色渐出 2 秒，最后全黑"""
    effect_fade_out(yeelight, "END", (255, 50, 50), duration)

def state_off(yeelight):
    """关闭"""
    yeelight.send_pixels([(0,0,0)] * 100)

# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Yeelight Hook for Claude Code")
    parser.add_argument("--state", "-s", required=True,
                        choices=['start', 'thinking', 'done', 'wait', 'interrupt', 'end', 'off'])
    parser.add_argument("--ip", default=DEFAULT_IP)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--duration", "-d", type=float, default=5.0)

    args = parser.parse_args()

    yeelight = Yeelight(args.ip, args.port)
    if not yeelight.connect():
        # 静默退出，不影响 Claude Code 正常运行
        # 设备不可达是正常情况（切换网络、设备关闭等）
        return 0

    try:
        yeelight.activate_direct_mode()

        handlers = {
            'start': lambda: state_start(yeelight, args.duration),
            'thinking': lambda: state_thinking(yeelight, args.duration),
            'done': lambda: state_done(yeelight, args.duration),
            'wait': lambda: state_wait(yeelight, args.duration),
            'interrupt': lambda: state_interrupt(yeelight, args.duration),
            'end': lambda: state_end(yeelight, args.duration),
            'off': lambda: state_off(yeelight),
        }

        handler = handlers.get(args.state)
        if handler:
            handler()

    except Exception:
        # 任何运行时错误都静默处理，不影响 Claude Code
        pass
    finally:
        yeelight.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())