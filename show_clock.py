#!/usr/bin/env python3
"""
实时时钟 - 显示当前时间
"""

import socket
import json
import base64
import time
from datetime import datetime

IP = "192.168.1.100  # 示例 IP，请修改为实际设备 IP"
PORT = 55443
ROWS, COLS = 5, 20

# 5x3 字体 (row 0 = 顶部)
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

def draw_time(time_str, hour_color=(255,100,100), minute_color=(100,255,100), colon_color=(255,255,100)):
    """绘制时间到网格"""
    grid = [(0, 0, 0)] * (ROWS * COLS)

    char_width = 3
    char_gap = 1

    # 计算总宽度
    total_width = 0
    for i, ch in enumerate(time_str):
        if ch == ':':
            total_width += 1
        else:
            total_width += char_width
        if i < len(time_str) - 1:
            total_width += char_gap

    start_col = (COLS - total_width) // 2
    col = start_col

    for i, ch in enumerate(time_str):
        if ch in DIGITS:
            pattern = DIGITS[ch]

            if ch == ':':
                color = colon_color
            elif i < 2:
                color = hour_color
            else:
                color = minute_color

            width = 1 if ch == ':' else 3

            for row_idx, row_data in enumerate(pattern):
                physical_row = ROWS - 1 - row_idx
                for col_offset, val in enumerate(row_data):
                    if val:
                        pixel_col = col + col_offset
                        idx = physical_row * COLS + pixel_col
                        if 0 <= idx < ROWS * COLS:
                            grid[idx] = color

            col += width + char_gap

    return grid

def print_grid(grid):
    """可视化网格"""
    print("\n网格显示:")
    for row in range(ROWS - 1, -1, -1):
        line = ""
        for col in range(COLS):
            idx = row * COLS + col
            r, g, b = grid[idx]
            if r > 200 and g < 150:
                line += "🔴"
            elif g > 200 and r < 150:
                line += "🟢"
            elif r > 100 and g > 100:
                line += "🟡"
            elif r > 0 or g > 0 or b > 0:
                line += "⚪"
            else:
                line += "⚫"
        print(line)

def send_pixels(sock, grid):
    """发送像素数据"""
    payload = "".join(base64.b64encode(bytes(rgb)).decode() for rgb in grid)
    cmd = {"id": 1, "method": "update_leds", "params": [payload]}
    sock.send((json.dumps(cmd) + "\r\n").encode())

def main():
    # 连接设备
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((IP, PORT))

    # 激活 direct mode
    cmd = {"id": 1, "method": "set_power", "params": ["on"]}
    sock.send((json.dumps(cmd) + "\r\n").encode())
    time.sleep(0.1)

    cmd = {"id": 2, "method": "activate_fx_mode", "params": [{"mode": "direct"}]}
    sock.send((json.dumps(cmd) + "\r\n").encode())
    time.sleep(0.2)

    print("✅ 已连接，显示时间...")
    print("按 Ctrl+C 停止\n")

    try:
        while True:
            now = datetime.now()
            time_str = now.strftime("%H:%M")

            grid = draw_time(time_str)
            send_pixels(sock, grid)

            print(f"\r⏰ {time_str}  ", end="", flush=True)
            print_grid(grid)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n⏹️ 停止")
    finally:
        sock.close()

if __name__ == "__main__":
    main()