#!/usr/bin/env python3
"""
Yeelight Client - 通过 Unix Socket 与 daemon 通信

使用方式:
    python3 yeelight-client.py --state done
    python3 yeelight-client.py --state thinking --duration 300
"""

import socket
import json
import argparse
import sys

SOCKET_PATH = "/tmp/yeelight.sock"

def send_command(state, duration=5.0):
    """发送命令到 daemon"""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)  # 快速失败
        sock.connect(SOCKET_PATH)

        cmd = {"state": state, "duration": duration}
        sock.send((json.dumps(cmd) + "\n").encode())

        # 不等待响应，daemon 可能正在执行长时间效果
        sock.close()
        return True
    except Exception:
        # 静默失败，daemon 可能未运行或网络不可达
        return False

def main():
    parser = argparse.ArgumentParser(description="Yeelight Client")
    parser.add_argument("--state", "-s", required=True,
                        choices=['start', 'thinking', 'done', 'wait', 'interrupt', 'complete', 'end', 'off'])
    parser.add_argument("--duration", "-d", type=float, default=5.0)

    args = parser.parse_args()

    send_command(args.state, args.duration)
    return 0

if __name__ == "__main__":
    sys.exit(main())