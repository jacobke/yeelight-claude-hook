#!/usr/bin/env python3
"""Unix Socket 服务端的客户端健壮性测试

覆盖三个真实缺陷：

1. 客户端发完就关、不读响应（yeelight-client.py 的设计）—— daemon 回包时拿到
   EPIPE，这属于合法用法，不应打印 "Client error: Broken pipe" 噪音。
2. 客户端连上但不发数据 —— accept 返回的是阻塞 socket（不继承监听 socket 的
   超时），一个沉默客户端就会永久占住单线程的 accept 循环，整个 daemon 卡死。
3. listen backlog 太小 —— 突发 hook 调用会被 ECONNREFUSED 拒绝，而
   yeelight-client.py 静默吞掉异常，命令直接丢失且日志无痕。

daemon 文件名带连字符，不能直接 import，用 importlib 按路径加载。
"""

import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_daemon_module():
    path = os.path.join(ROOT, "yeelight-daemon.py")
    spec = importlib.util.spec_from_file_location("yeelight_daemon_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


daemon_module = load_daemon_module()


class UnixSocketServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="yeelight-test-")
        self.sock_path = os.path.join(self.tmpdir, "test.sock")
        self._orig_socket_path = daemon_module.SOCKET_PATH
        daemon_module.SOCKET_PATH = self.sock_path

        # 只填 run_server / handle_command 用得到的字段，不连设备
        d = daemon_module.YeelightDaemon.__new__(daemon_module.YeelightDaemon)
        d.running = True
        d.sock = None
        d.direct_mode_ready = False
        d.effect_thread = None
        d.lock = threading.Lock()
        self.daemon = d

        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self._orig_stdout, self._orig_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = self.stdout, self.stderr

        self.thread = threading.Thread(target=d.run_server, daemon=True)
        self.thread.start()

        deadline = time.time() + 5
        while not os.path.exists(self.sock_path) and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(os.path.exists(self.sock_path), "daemon 未能创建 socket")

    def tearDown(self):
        self.daemon.running = False
        self.thread.join(timeout=10)
        sys.stdout, sys.stderr = self._orig_stdout, self._orig_stderr
        daemon_module.SOCKET_PATH = self._orig_socket_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _connect(self, timeout=5):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(self.sock_path)
        return s

    def _request(self, state="__not_a_valid_state__", timeout=8):
        """发一条命令并读回响应"""
        s = self._connect(timeout=timeout)
        try:
            s.send(json.dumps({"state": state}).encode())
            return s.recv(1024)
        finally:
            s.close()

    def test_client_closing_without_reading_is_not_an_error(self):
        """客户端不等响应直接关闭（yeelight-client.py 的正常用法），不该产生噪音日志"""
        s = self._connect()
        s.send(json.dumps({"state": "__not_a_valid_state__"}).encode())
        s.close()  # 不读响应直接关闭 -> daemon 回包时拿到 EPIPE

        time.sleep(0.5)
        output = self.stdout.getvalue() + self.stderr.getvalue()
        self.assertNotIn("Broken pipe", output)
        self.assertNotIn("Client error", output)

    def test_silent_client_does_not_block_server(self):
        """只连上但不发数据的客户端，不应把整个 daemon 永久卡住"""
        silent = self._connect()
        try:
            started = time.time()
            reply = self._request()
            elapsed = time.time() - started
            self.assertIn(b'"status"', reply)
            self.assertLess(
                elapsed, 8,
                "daemon 被沉默客户端阻塞了 %.1fs（accept 返回的是阻塞 socket）" % elapsed,
            )
        finally:
            silent.close()

    def test_listen_backlog_is_large_enough_for_hook_bursts(self):
        """突发 hook 调用不能因为 backlog 太小被直接拒绝"""
        backlog = getattr(daemon_module, "LISTEN_BACKLOG", 5)
        self.assertGreaterEqual(
            backlog, 64,
            "listen backlog=%d 太小，突发 hook 调用会 ECONNREFUSED" % backlog,
        )

    def test_runtime_logs_go_to_stderr(self):
        """运行期日志必须走 stderr —— stdout 是块缓冲的，launchd 重定向到文件时
        会攒在 8KB 缓冲里，导致日志看起来「卡住」且和 stderr 内容交错乱序"""
        s = self._connect()
        s.send(b"{not valid json")
        s.recv(1024)
        s.close()

        time.sleep(0.3)
        self.assertEqual(self.stdout.getvalue(), "", "运行期日志不应写到 stdout")
        self.assertIn("Client error", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
