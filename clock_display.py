#!/usr/bin/env python3
"""
Yeelight Cube Lite 时钟显示
基于 YEELIGHT_GUIDE.md 的像素控制方法

用法:
    python clock_display.py                    # 默认冒号闪烁模式，60秒
    python clock_display.py --mode 3 --time 30 # 显示秒数，30秒
    python clock_display.py --help             # 查看帮助
"""

import socket
import json
import base64
import time
import argparse
from datetime import datetime

# 设备配置
IP = "192.168.1.100  # 示例 IP，请修改为实际设备 IP"
PORT = 55443
ROWS, COLS = 5, 20

# 5x5 数字点阵 (更大更清晰的字体)
# row 0 = 顶部, row 4 = 底部
DIGITS_5X5 = {
    '0': [
        [0,1,1,1,0],
        [1,0,0,0,1],
        [1,0,0,0,1],
        [1,0,0,0,1],
        [0,1,1,1,0],
    ],
    '1': [
        [0,0,1,0,0],
        [0,1,1,0,0],
        [0,0,1,0,0],
        [0,0,1,0,0],
        [0,1,1,1,0],
    ],
    '2': [
        [0,1,1,1,0],
        [1,0,0,0,1],
        [0,0,1,1,0],
        [0,1,0,0,0],
        [1,1,1,1,1],
    ],
    '3': [
        [0,1,1,1,0],
        [1,0,0,0,1],
        [0,0,1,1,0],
        [1,0,0,0,1],
        [0,1,1,1,0],
    ],
    '4': [
        [0,0,0,1,0],
        [0,0,1,1,0],
        [0,1,0,1,0],
        [1,1,1,1,1],
        [0,0,0,1,0],
    ],
    '5': [
        [1,1,1,1,1],
        [1,0,0,0,0],
        [1,1,1,1,0],
        [0,0,0,0,1],
        [1,1,1,1,0],
    ],
    '6': [
        [0,1,1,1,0],
        [1,0,0,0,0],
        [1,1,1,1,0],
        [1,0,0,0,1],
        [0,1,1,1,0],
    ],
    '7': [
        [1,1,1,1,1],
        [0,0,0,0,1],
        [0,0,1,1,0],
        [0,1,0,0,0],
        [0,1,0,0,0],
    ],
    '8': [
        [0,1,1,1,0],
        [1,0,0,0,1],
        [0,1,1,1,0],
        [1,0,0,0,1],
        [0,1,1,1,0],
    ],
    '9': [
        [0,1,1,1,0],
        [1,0,0,0,1],
        [0,1,1,1,1],
        [0,0,0,0,1],
        [0,1,1,1,0],
    ],
    ':': [
        [0,0,0,0,0],
        [0,0,1,0,0],
        [0,0,0,0,0],
        [0,0,1,0,0],
        [0,0,0,0,0],
    ],
}

# 颜色配置
COLOR_HOUR = (255, 100, 100)    # 红色调 - 小时
COLOR_MINUTE = (100, 255, 100)  # 绿色调 - 分钟
COLOR_COLON = (255, 255, 100)   # 黄色 - 冒号
COLOR_OFF = (0, 0, 0)           # 关闭


class YeelightClock:
    def __init__(self, ip, port=55443):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False

    def connect(self):
        """建立 TCP 连接"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, self.port))
            self.connected = True
            print(f"✅ 已连接到 {self.ip}:{self.port}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    def disconnect(self):
        """关闭连接"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None
        self.connected = False
        print("🔌 已断开连接")

    def send_command(self, method, params, wait_response=False):
        """发送 JSON-RPC 命令"""
        if not self.connected:
            return None

        cmd = {"id": int(time.time() * 1000) % 10000, "method": method, "params": params}
        try:
            self.sock.send((json.dumps(cmd) + "\r\n").encode())
            if wait_response:
                self.sock.settimeout(1)
                response = self.sock.recv(4096).decode()
                return response
        except Exception as e:
            print(f"⚠️ 发送命令失败: {e}")
            self.connected = False
        return None

    def activate_direct_mode(self):
        """激活 FX Direct 模式"""
        self.send_command("set_power", ["on"])
        time.sleep(0.1)
        self.send_command("activate_fx_mode", [{"mode": "direct"}])
        time.sleep(0.2)
        print("🎨 已激活 Direct 模式")

    def encode_pixel(self, r, g, b):
        """将 RGB 编码为 base64"""
        return base64.b64encode(bytes([r, g, b])).decode("ascii")

    def draw_time(self, time_str, color_hour=None, color_minute=None, color_colon=None):
        """
        在矩阵上绘制时间
        time_str: 格式如 "12:34" 或 "12:34:56"
        """
        if color_hour is None:
            color_hour = COLOR_HOUR
        if color_minute is None:
            color_minute = COLOR_MINUTE
        if color_colon is None:
            color_colon = COLOR_COLON

        # 创建空白网格
        grid = [COLOR_OFF] * (ROWS * COLS)

        # 使用紧凑的 5x3 字体
        char_width = 3
        char_gap = 1

        # 紧凑版 5x3 字体
        digits_3x5 = self._compress_font(DIGITS_5X5, char_width)

        # 计算起始列（居中）
        total_width = len(time_str) * char_width + (len(time_str) - 1) * char_gap
        start_col = (COLS - total_width) // 2

        col = start_col
        for i, ch in enumerate(time_str):
            if ch in digits_3x5:
                pattern = digits_3x5[ch]

                # 确定颜色
                if ch == ':':
                    color = color_colon
                elif i < 2:  # 小时部分
                    color = color_hour
                else:  # 分钟部分
                    color = color_minute

                # 绘制字符
                for row, line in enumerate(pattern):
                    # 像素索引计算：row 0 是底部，需要翻转
                    actual_row = ROWS - 1 - row
                    for bit_idx, val in enumerate(line):
                        if val:
                            pixel_col = col + bit_idx
                            pixel_idx = actual_row * COLS + pixel_col
                            if pixel_idx < ROWS * COLS:
                                grid[pixel_idx] = color

            col += char_width + char_gap

        # 发送像素数据
        self._send_pixels(grid)

    def _compress_font(self, font_5x5, target_width=3):
        """将 5x5 字体压缩为更窄的版本"""
        compressed = {}
        for char, pattern in font_5x5.items():
            if char == ':':
                # 冒号保持简单
                compressed[char] = [[0], [1], [0], [1], [0]]
                continue

            new_pattern = []
            for row in pattern:
                # 取关键列：0, 2, 4 -> 0, 1, 2
                new_row = [row[0], row[2], row[4]]
                new_pattern.append(new_row)
            compressed[char] = new_pattern
        return compressed

    def _send_pixels(self, grid):
        """发送像素网格到设备"""
        payload = "".join(self.encode_pixel(*rgb) for rgb in grid)
        self.send_command("update_leds", [payload])

    def run_clock(self, duration_seconds=60, show_seconds=False):
        """
        运行时钟显示
        duration_seconds: 运行时长（秒）
        show_seconds: 是否显示秒数
        """
        print(f"⏰ 开始时钟显示 ({duration_seconds}秒)...")

        for i in range(duration_seconds):
            now = datetime.now()
            if show_seconds:
                time_str = now.strftime("%H:%M:%S")
            else:
                time_str = now.strftime("%H:%M")

            self.draw_time(time_str)

            # 显示剩余时间
            remaining = duration_seconds - i - 1
            print(f"\r   {time_str} (剩余 {remaining}秒)  ", end="", flush=True)
            time.sleep(1)

        print("\n⏰ 时钟显示结束")

    def run_clock_with_pulse(self, duration_seconds=60):
        """
        运行时钟显示，带冒号闪烁效果
        """
        print(f"⏰ 开始时钟显示（冒号闪烁）({duration_seconds}秒)...")

        colon_visible = True
        for i in range(duration_seconds):
            now = datetime.now()
            time_str = now.strftime("%H:%M")

            # 每秒切换冒号显示
            if colon_visible:
                self.draw_time(time_str)
                display_str = time_str
            else:
                # 隐藏冒号
                self.draw_time(time_str, color_colon=COLOR_OFF)
                display_str = time_str.replace(':', ' ')

            colon_visible = not colon_visible

            remaining = duration_seconds - i - 1
            print(f"\r   {display_str} (剩余 {remaining}秒)  ", end="", flush=True)
            time.sleep(1)

        print("\n⏰ 时钟显示结束")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Yeelight Cube Lite 时钟显示")
    parser.add_argument("--ip", default=IP, help=f"设备IP地址 (默认: {IP})")
    parser.add_argument("--mode", type=int, choices=[1, 2, 3, 4], default=2,
                        help="显示模式: 1=基础, 2=冒号闪烁(默认), 3=显示秒数, 4=彩虹模式")
    parser.add_argument("--time", type=int, default=60, help="运行时长/秒 (默认: 60)")
    parser.add_argument("--hour-color", type=str, default="255,100,100",
                        help="小时颜色 R,G,B (默认: 255,100,100)")
    parser.add_argument("--minute-color", type=str, default="100,255,100",
                        help="分钟颜色 R,G,B (默认: 100,255,100)")

    args = parser.parse_args()

    # 解析颜色
    hour_color = tuple(int(x) for x in args.hour_color.split(","))
    minute_color = tuple(int(x) for x in args.minute_color.split(","))

    clock = YeelightClock(args.ip, PORT)

    if not clock.connect():
        print("无法连接设备，退出")
        return 1

    try:
        clock.activate_direct_mode()

        if args.mode == 1:
            clock.run_clock(args.time)
        elif args.mode == 2:
            clock.run_clock_with_pulse(args.time)
        elif args.mode == 3:
            clock.run_clock(args.time, show_seconds=True)
        elif args.mode == 4:
            # 彩虹模式 - 颜色渐变
            print(f"🌈 彩虹时钟模式 ({args.time}秒)...")
            for i in range(args.time):
                now = datetime.now()
                time_str = now.strftime("%H:%M")

                # 根据时间调整颜色
                hour = now.hour
                minute = now.minute

                # 早晨: 暖色, 中午: 亮色, 晚上: 冷色
                if 6 <= hour < 12:
                    h_col = (255, 200, 100)  # 暖橙色
                    m_col = (100, 255, 200)  # 青绿色
                elif 12 <= hour < 18:
                    h_col = (255, 255, 100)  # 明黄色
                    m_col = (100, 255, 100)  # 亮绿色
                elif 18 <= hour < 22:
                    h_col = (255, 150, 100)  # 橙色
                    m_col = (150, 100, 255)  # 紫色
                else:
                    h_col = (100, 100, 255)  # 蓝色
                    m_col = (150, 150, 255)  # 浅蓝色

                clock.draw_time(time_str, color_hour=h_col, color_minute=m_col)

                remaining = args.time - i - 1
                print(f"\r   {time_str} (剩余 {remaining}秒)  ", end="", flush=True)
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断")
    finally:
        clock.disconnect()

    return 0


if __name__ == "__main__":
    exit(main())