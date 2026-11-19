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
import dataclasses
import time
import math
import random
import argparse
import sys
import os
import signal
import struct
import threading

import config as app_config
import minimax
import deepseek

# ============================================================================
# 配置
# ============================================================================

DEFAULT_IP = None  # 必须通过 --ip 参数或配置文件指定
DEFAULT_PORT = 55443
SOCKET_PATH = "/tmp/yeelight.sock"
ROWS, COLS = 5, 20

# 所有可用的效果状态
VALID_STATES = [
    "start", "thinking", "done", "wait", "interrupt",
    "complete", "end", "off", "minimax",
]

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
    def __init__(self, ip, port=55443, instance=0, shared=1,
                 minimax_enabled=False,
                 minimax_api_base=minimax.DEFAULT_API_BASE,
                 minimax_api_key="",
                 minimax_poll_interval=minimax.POLL_INTERVAL_DEFAULT,
                 takeover_delay=minimax.TAKEOVER_DELAY_DEFAULT,
                 deepseek_enabled=False,
                 deepseek_api_base=deepseek.DEFAULT_API_BASE,
                 deepseek_api_key="",
                 deepseek_poll_interval=deepseek.POLL_INTERVAL_DEFAULT,
                 deepseek_alternate_interval=deepseek.ALTERNATE_INTERVAL_DEFAULT,
                 deepseek_state_path="",
                 rotation_interval=10):
        self.ip = ip
        self.port = port
        self.instance = instance  # 实例编号 (0=不显示, 1-20=显示位置)
        self.shared = max(1, shared)  # 同时连接此设备的 daemon 数量，用于分摊命令配额
        self.sock = None
        self.running = True
        self.interrupted = False  # 效果中断标志
        self.effect_thread = None  # 当前效果线程
        self.command_count = 0
        self.last_command_time = 0
        self.lock = threading.Lock()  # 保护 socket 操作
        self.reader_thread = None  # 后台读取线程，防止设备 send buffer 填满导致假死
        # 命令间隔：默认 1 秒（每秒 1 命令 = 60/分钟）。
        # 共享模式下按 daemon 数量均分：shared=2 → 每 2 秒 1 命令（30/分钟）
        self.command_interval = float(self.shared)

        # ===== MiniMax 配额条 =====
        self.minimax_enabled = minimax_enabled and bool(minimax_api_key)
        self.minimax_api_base = minimax_api_base
        self.minimax_api_key = minimax_api_key
        self.minimax_poll_interval = minimax_poll_interval
        self.takeover_delay = takeover_delay
        self.display_thread = None              # 显示线程（轮播两个页面）
        self.minimax_snapshot = None             # 最近一次成功拉到的配额快照（缓存）
        self.last_minimax_rendered = None        # 最近一次画出的 MiniMax 页
        self.last_minimax_reset_fill = None      # 最近一次画出的重置倒计时列数
        self.display_needs_repaint = True        # 效果抢过屏幕后置位
        self.minimax_last_fetch_at = 0.0         # 最近一次尝试拉取的时间戳
        self.last_effect_finished_at = time.time()  # 启动后立即允许显示

        # ===== DeepSeek 余额页 =====
        self.deepseek_enabled = deepseek_enabled and bool(deepseek_api_key)
        self.deepseek_api_base = deepseek_api_base
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_poll_interval = deepseek_poll_interval
        self.deepseek_alternate_interval = deepseek_alternate_interval
        self.rotation_interval = rotation_interval
        self.deepseek_tracker = None
        if self.deepseek_enabled:
            state_path = deepseek_state_path or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "deepseek_state.json")
            self.deepseek_tracker = deepseek.SpendTracker(state_path)
        self.direct_mode_ready = False
        self.deepseek_balance = None
        self.deepseek_spend = 0.0
        self.deepseek_last_fetch_at = 0.0
        self.page = "minimax"
        self.page_started_at = time.time()
        self.deepseek_subpage = 0
        self.deepseek_subpage_started_at = time.time()
        self.last_deepseek_rendered = None

    def mark_instance(self, grid, color=(255, 200, 50)):
        """在 grid 上标记实例编号（土豪金像素）

        实例编号 1-5，标记在最右边列从上到下：
        1 = 最右上角 (pixel 99, row 4)
        2 = 右上角往下 (pixel 79, row 3)
        3 = pixel 59 (row 2)
        4 = pixel 39 (row 1)
        5 = 最右下角 (pixel 19, row 0)
        """
        if self.instance < 1 or self.instance > 5:
            return grid

        # 最右边列：从上往下
        # row 4 → pixel 99, row 3 → pixel 79, row 2 → pixel 59, row 1 → pixel 39, row 0 → pixel 19
        pixel_index = 99 - (self.instance - 1) * 20
        if 0 <= pixel_index <= 99:
            grid[pixel_index] = color

        return grid

    def connect(self):
        """连接设备"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, self.port))
            print(f"Connected to {self.ip}:{self.port}", flush=True)
            # 连接成功后启动后台 reader 线程，持续清空设备 TCP send buffer
            # 否则长时间运行后设备会因 send buffer 填满而假死
            self._start_reader()
            return True
        except Exception as e:
            print(f"Connection failed: {e}", file=sys.stderr, flush=True)
            return False

    def _start_reader(self):
        """启动后台 reader 线程"""
        if self.reader_thread and self.reader_thread.is_alive():
            return
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def _reader_loop(self):
        """后台循环读取设备响应，防止设备端 send buffer 填满导致假死

        Yeelight 设备会对每个命令返回响应，状态变化时还会主动推送 props 通知。
        这些数据如果一直不读取，设备 TCP send buffer 会被填满，触发 TCP 流量控制，
        设备会停止处理新命令 —— 表现为「连接还在但所有命令超时」，只能断电恢复。
        """
        while self.running:
            sock = self.sock
            if sock is None:
                time.sleep(0.5)
                continue
            try:
                sock.settimeout(1.0)
                data = sock.recv(4096)
                if not data:
                    # 设备主动关闭连接，让 send_command 的重连逻辑接管
                    print("Device closed connection (reader detected)", file=sys.stderr, flush=True)
                    self.close()
                    time.sleep(1)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Reader error: {e}", file=sys.stderr, flush=True)
                time.sleep(1)

    def reconnect(self):
        """重连"""
        self.close()
        self.direct_mode_ready = False
        time.sleep(1)
        return self.connect()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.direct_mode_ready = False

    def send_command(self, method, params, retry=True):
        """发送命令（带频率限制和自动重连）"""
        with self.lock:
            # 频率限制：间隔由 self.command_interval 决定（默认 1 秒）
            # 多 daemon 共享同一台设备时，按 shared 数均分配额
            now = time.time()
            wait = self.command_interval - (now - self.last_command_time)
            if wait > 0:
                time.sleep(wait)

            cmd = {"id": int(time.time() * 1000) % 10000, "method": method, "params": params}

            # 尝试发送（最多尝试 3 次）
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    # 检查并建立连接
                    if not self.sock:
                        if not self.connect():
                            if attempt < max_attempts - 1:
                                time.sleep(1)
                                continue
                            return False

                    self.sock.send((json.dumps(cmd) + "\r\n").encode())
                    self.command_count += 1
                    self.last_command_time = time.time()
                    return True

                except Exception as e:
                    print(f"Send failed (attempt {attempt + 1}): {e}", file=sys.stderr, flush=True)
                    self.close()
                    if attempt < max_attempts - 1:
                        print(f"Reconnecting in 1 second...", file=sys.stderr, flush=True)
                        time.sleep(1)
                    continue

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

    def send_pixels_with_mark(self, grid):
        """发送像素并标记实例编号"""
        grid = self.mark_instance(grid)
        self.send_pixels(grid)

    # ========================================================================
    # MiniMax 配额条
    # ========================================================================

    def minimax_snapshot_if_available(self, now=None):
        """取当前可用的配额快照（带缓存）。

        缓存新鲜时直接复用；过期时请求接口。请求失败时返回上一次成功的快照
        （可能为 None），这样接口临时故障不会让画面消失。
        """
        if now is None:
            now = time.time()
        if (self.minimax_snapshot is not None
                and now - self.minimax_last_fetch_at < self.minimax_poll_interval):
            return self.minimax_snapshot

        try:
            snapshot = minimax.fetch_quota(self.minimax_api_key, self.minimax_api_base)
        except minimax.MinimaxError as e:
            print("MiniMax fetch failed: %s" % e, file=sys.stderr, flush=True)
            # 失败也要等一个轮询周期再重试
            self.minimax_last_fetch_at = now
            return self.minimax_snapshot

        self.minimax_snapshot = snapshot
        self.minimax_last_fetch_at = now
        return snapshot

    def deepseek_values_if_available(self, now=None):
        """取 (今日消费, 余额)；不可用时返回 None"""
        if not self.deepseek_enabled:
            return None
        if now is None:
            now = time.time()
        if now - self.deepseek_last_fetch_at < self.deepseek_poll_interval:
            if self.deepseek_balance is None:
                return None
            return (self.deepseek_spend, self.deepseek_balance)

        try:
            balance = deepseek.fetch_balance(self.deepseek_api_key,
                                             self.deepseek_api_base)
        except deepseek.DeepSeekError as e:
            print("DeepSeek fetch failed: %s" % e, file=sys.stderr, flush=True)
            self.deepseek_last_fetch_at = now
            if self.deepseek_balance is None:
                return None
            return (self.deepseek_spend, self.deepseek_balance)

        today = time.strftime("%Y-%m-%d", time.localtime())
        self.deepseek_spend = self.deepseek_tracker.update(balance, today)
        self.deepseek_balance = balance
        self.deepseek_last_fetch_at = now
        return (self.deepseek_spend, self.deepseek_balance)

    def available_pages(self, now=None):
        """当前可显示的页面列表（顺序即轮播顺序）"""
        pages = []
        if self.minimax_enabled and self.minimax_snapshot_if_available(now) is not None:
            pages.append("minimax")
        if (self.deepseek_enabled
                and self.deepseek_values_if_available(now) is not None):
            pages.append("deepseek")
        return pages

    def reset_page_after_effect(self, now=None):
        """效果结束后回到第一页，并重置子页"""
        if now is None:
            now = time.time()
        self.page = "minimax"
        self.page_started_at = now
        self.deepseek_subpage = 0
        self.deepseek_subpage_started_at = now

    def display_should_paint(self, now=None):
        """是否需要重绘当前屏幕（可能顺带切换页面）"""
        if now is None:
            now = time.time()
        if not self.minimax_enabled and not self.deepseek_enabled:
            return False
        if self.effect_thread and self.effect_thread.is_alive():
            return False
        if now - self.last_effect_finished_at < self.takeover_delay:
            return False

        pages = self.available_pages(now)
        if not pages:
            return False

        # 当前页不再可用 → 回到第一页
        if self.page not in pages:
            self.page = pages[0]
            self.page_started_at = now
            return True

        # 轮播
        if len(pages) > 1 and now - self.page_started_at >= self.rotation_interval:
            index = pages.index(self.page)
            self.page = pages[(index + 1) % len(pages)]
            self.page_started_at = now
            self.deepseek_subpage = 0
            self.deepseek_subpage_started_at = now
            return True

        if self.page == "deepseek":
            values = self.deepseek_values_if_available(now)
            if values is None:
                return False
            mode, texts = deepseek.compose_page(values[0], values[1])
            if mode == "alternate":
                if (now - self.deepseek_subpage_started_at
                        >= self.deepseek_alternate_interval):
                    self.deepseek_subpage ^= 1
                    self.deepseek_subpage_started_at = now
                    return True
                key = (mode, tuple(texts), self.deepseek_subpage)
            else:
                key = (mode, tuple(texts), 0)
            return key != self.last_deepseek_rendered or self.display_needs_repaint

        # MiniMax 页
        snapshot = self.minimax_snapshot_if_available(now)
        if snapshot is None:
            return False
        if snapshot.differs_from(self.last_minimax_rendered) or self.display_needs_repaint:
            return True
        reset_pct = minimax.reset_progress_pct(snapshot.interval_reset_at,
                                             now_ms=int(now * 1000))
        return minimax.reset_fill_columns(reset_pct) != self.last_minimax_reset_fill

    def _takeover_and_send(self, grid):
        """必要时接管设备（停内置效果、进 direct 模式），然后发像素"""
        if not self.direct_mode_ready:
            self.send_command("stop_cf", [])
            self.send_command("set_power", ["on"])
            self.send_command("activate_fx_mode", [{"mode": "direct"}])
            self.direct_mode_ready = True
        self.send_pixels_with_mark(grid)

    def paint_minimax(self, snapshot):
        """接管屏幕并画出 MiniMax 配额页"""
        now = time.time()
        reset_pct = minimax.reset_progress_pct(snapshot.interval_reset_at,
                                             now_ms=int(now * 1000))
        grid = minimax.render_bar(snapshot.interval_pct, snapshot.weekly_pct,
                                reset_pct)
        self._takeover_and_send(grid)
        self.last_minimax_rendered = snapshot
        self.last_minimax_reset_fill = minimax.reset_fill_columns(reset_pct)
        self.display_needs_repaint = False

    def paint_current_page(self):
        """画出当前页"""
        now = time.time()
        if self.page == "deepseek":
            values = self.deepseek_values_if_available(now)
            if values is None:
                return
            mode, texts = deepseek.compose_page(values[0], values[1])
            index = self.deepseek_subpage if mode == "alternate" else 0
            grid = deepseek.render_page(mode, texts, index)
            self._takeover_and_send(grid)
            self.last_deepseek_rendered = (mode, tuple(texts), index)
            self.display_needs_repaint = False
            return
        snapshot = self.minimax_snapshot_if_available(now)
        if snapshot is not None:
            self.paint_minimax(snapshot)

    def display_tick(self):
        """显示线程的一轮：判断并（必要时）绘制一次。返回是否绘制了"""
        if not self.display_should_paint():
            return False
        self.paint_current_page()
        return True

    def display_loop(self):
        """显示线程主循环"""
        while self.running:
            time.sleep(1)
            try:
                self.display_tick()
            except Exception as e:
                print("Display loop error: %s" % e, file=sys.stderr, flush=True)

    def start_display_thread(self):
        """启动显示线程（两个数据源都不可用时不启动）"""
        if not self.minimax_enabled and not self.deepseek_enabled:
            print("Display disabled (no API key)", file=sys.stderr, flush=True)
            return
        self.display_thread = threading.Thread(target=self.display_loop, daemon=True)
        self.display_thread.start()

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
            self.send_pixels_with_mark(grid)
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
            self.send_pixels_with_mark(grid)
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
            self.send_pixels_with_mark(grid)
            time.sleep(0.15)

        # 保持显示 2 秒
        for _ in range(10):
            if self.check_interrupted():
                return
            grid = render_centered("DONE", color)
            self.send_pixels_with_mark(grid)
            time.sleep(0.2)

        # 渐出
        steps_out = 8
        for i in range(steps_out, 0, -1):
            if self.check_interrupted():
                return
            brightness = i / steps_out
            tc = (int(color[0] * brightness), int(color[1] * brightness), int(color[2] * brightness))
            grid = render_centered("DONE", tc)
            self.send_pixels_with_mark(grid)
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
            self.send_pixels_with_mark(grid)
            time.sleep(0.5)

    def effect_interrupt(self):
        """红色快闪"""
        grid_on = render_centered("ERROR", (255, 0, 0))
        grid_off = [(0,0,0)] * 100
        for _ in range(5):
            if self.check_interrupted():
                return
            self.send_pixels_with_mark(grid_on)
            time.sleep(0.5)
            if self.check_interrupted():
                return
            self.send_pixels(grid_off)  # 关灯不显示实例标记
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

    def effect_minimax(self):
        """立即绘制一次配额条（调试 / 手动刷新用）"""
        snapshot = self.minimax_snapshot_if_available()
        if snapshot is None:
            print("No MiniMax data available", file=sys.stderr, flush=True)
            return
        self.paint_minimax(snapshot)

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
            self.send_pixels_with_mark(grid)
            time.sleep(duration / steps)
        self.effect_off()

    # ========================================================================
    # 命令处理
    # ========================================================================

    def run_effect(self, state, duration=5.0):
        """运行效果（在独立线程中）"""
        self.interrupted = False  # 重置中断标志
        # 效果抢过了屏幕，回来后需要重画一次配额条
        self.display_needs_repaint = True
        # 效果会重配设备模式（尤其 complete 的 start_cf），需要重新接管
        self.direct_mode_ready = False

        try:
            # 对于点阵效果，确保先进入 direct mode
            # complete 使用内置效果，不需要 direct mode
            if state not in ["complete", "off", "minimax"]:
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
                "minimax": lambda: self.effect_minimax(),
            }

            handler = handlers.get(state)
            if handler:
                handler()
        finally:
            # 记录效果结束时间，显示线程据此判断保护期
            self.last_effect_finished_at = time.time()
            self.reset_page_after_effect(self.last_effect_finished_at)

    def handle_command(self, cmd):
        """处理命令"""
        state = cmd.get("state")
        duration = cmd.get("duration", 5.0)

        if state not in VALID_STATES:
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
    parser.add_argument("--ip", default=None, help="设备 IP 地址")
    parser.add_argument("--port", type=int, default=None, help="设备端口 (默认 55443)")
    parser.add_argument("--instance", type=int, default=None,
                        help="Instance number (1-5) for pixel marking, 0=disabled")
    parser.add_argument("--shared", type=int, default=None,
                        help="Number of daemons sharing this device (default 1). "
                             "Each daemon will limit to 60/shared commands per minute.")
    parser.add_argument("--config", default=None,
                        help="配置文件路径 (默认: 脚本同目录的 config.json)")
    parser.add_argument("--minimax-api-key", default=None, help="MiniMax API key")
    parser.add_argument("--minimax-api-base", default=None, help="MiniMax API 域名")
    parser.add_argument("--minimax-interval", type=int, default=None,
                        help="配额轮询间隔（秒，默认 300）")
    parser.add_argument("--no-minimax", action="store_true", help="关闭配额条功能")
    parser.add_argument("--deepseek-api-key", default=None, help="DeepSeek API key")
    parser.add_argument("--deepseek-api-base", default=None, help="DeepSeek API 域名")
    parser.add_argument("--no-deepseek", action="store_true", help="关闭 DeepSeek 余额页")
    parser.add_argument("--rotation-interval", type=int, default=None,
                        help="两页轮播间隔（秒，默认 10）")
    parser.add_argument("--dry-run", action="store_true",
                        help="打印解析后的配置后退出，不连接设备")
    args = parser.parse_args()

    cfg = app_config.load_config(args.config)
    settings = app_config.resolve_settings(
        args, cfg,
        claude_token=app_config.read_claude_settings_token(),
        claude_env=app_config.read_claude_settings_env())

    if args.dry_run:
        data = dataclasses.asdict(settings)
        for field in ("minimax_api_key", "deepseek_api_key"):
            key = data.get(field) or ""
            if key:
                # 打码，避免把完整 key 留在终端记录里
                data[field] = "%s...%s" % (key[:6], key[-4:])
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if not settings.ip:
        print("Error: device IP not specified (use --ip or config.json)",
              file=sys.stderr)
        return 1

    daemon = YeelightDaemon(
        settings.ip, settings.port, settings.instance, settings.shared,
        settings.minimax_enabled, settings.minimax_api_base,
        settings.minimax_api_key, settings.minimax_poll_interval,
        settings.takeover_delay,
        settings.deepseek_enabled, settings.deepseek_api_base,
        settings.deepseek_api_key, settings.deepseek_poll_interval,
        settings.deepseek_alternate_interval, settings.deepseek_state_path,
        settings.rotation_interval)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        daemon.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not daemon.connect():
        return 1

    daemon.activate_direct_mode()
    daemon.start_display_thread()
    daemon.run_server()

    return 0


if __name__ == "__main__":
    sys.exit(main())
