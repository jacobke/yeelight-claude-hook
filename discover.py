#!/usr/bin/env python3
"""
Yeelight 设备发现 - 多种方法搜索设备 IP

方法:
1. SSDP (UPnP) 发现
2. mDNS/Bonjour 发现 (需要 zeroconf 库)
3. 局域网扫描
"""

import socket
import time
import re
import subprocess
import sys

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1982
YEELIGHT_PORT = 55443

def discover_ssdp(timeout=5):
    """方法1: SSDP 发现"""
    print("\n📡 方法1: SSDP 发现...")

    devices = []
    MSEARCH = b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1982\r\nMAN: "ssdp:discover"\r\nMX: 3\r\nST: yeelight\r\n\r\n'

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    # 发送多次请求
    for _ in range(3):
        sock.sendto(MSEARCH, (SSDP_ADDR, SSDP_PORT))

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            data, addr = sock.recvfrom(4096)
            response = data.decode('utf-8', errors='ignore')

            if 'yeelight' in response.lower():
                device = {'ip': addr[0], 'port': YEELIGHT_PORT}

                # 解析响应
                location = re.search(r'Location: yeelight://([0-9.]+):(\d+)', response)
                if location:
                    device['ip'] = location.group(1)
                    device['port'] = int(location.group(2))

                for line in response.split('\n'):
                    if line.startswith('id:'):
                        device['id'] = line.split(':', 1)[1].strip()
                    elif line.startswith('model:'):
                        device['model'] = line.split(':', 1)[1].strip()
                    elif line.startswith('name:'):
                        device['name'] = line.split(':', 1)[1].strip()

                if device not in devices:
                    devices.append(device)
                    print(f"  ✅ {device['ip']} - {device.get('name', 'unknown')}")

        except socket.timeout:
            break

    sock.close()
    return devices

def discover_mdns(timeout=5):
    """方法2: mDNS 发现 (使用系统命令)"""
    print("\n📡 方法2: mDNS/Bonjour 发现...")

    devices = []

    # macOS: 使用 dns-sd 命令
    try:
        result = subprocess.run(
            ['dns-sd', '-B', '_yeelight._tcp', 'local'],
            capture_output=True, text=True, timeout=timeout
        )
        # 解析输出...
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 尝试 avahi-browse (Linux)
    try:
        result = subprocess.run(
            ['avahi-browse', '-rpt', '_yeelight._tcp'],
            capture_output=True, text=True, timeout=timeout
        )
        for line in result.stdout.split('\n'):
            if '=' in line:
                parts = line.split(';')
                if len(parts) > 7:
                    device = {
                        'ip': parts[7],
                        'name': parts[3] if len(parts) > 3 else 'unknown'
                    }
                    devices.append(device)
                    print(f"  ✅ {device['ip']} - {device['name']}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  ⚠️ avahi-browse 未安装")

    return devices

def discover_arp_scan():
    """方法3: ARP 扫描查找 Yeelight 设备"""
    print("\n📡 方法3: ARP 扫描...")

    devices = []

    # 获取本机网段
    try:
        # macOS/Linux
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True)

        # 查找 Yeelight 设备 (通过 MAC 地址前缀或主机名)
        for line in result.stdout.split('\n'):
            if 'yeelight' in line.lower() or 'yeelink' in line.lower():
                ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                if ip_match:
                    ip = ip_match.group(1)
                    print(f"  ✅ {ip} (从 ARP 表)")
                    devices.append({'ip': ip, 'port': YEELIGHT_PORT})

    except Exception as e:
        print(f"  ⚠️ ARP 扫描失败: {e}")

    return devices

def check_port(ip, port=55443, timeout=1):
    """检查设备端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

def get_device_info(ip, port=55443):
    """获取设备信息"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect((ip, port))

        # 发送查询命令
        cmd = '{"id":1,"method":"get_prop","params":["name","model","power","bright"]}\r\n'
        sock.send(cmd.encode())

        response = sock.recv(4096).decode()
        sock.close()

        return response

    except Exception as e:
        return None

def discover_all(timeout=5):
    """尝试所有发现方法"""
    print("=" * 50)
    print("Yeelight 设备发现")
    print("=" * 50)

    all_devices = []

    # 方法1: SSDP
    devices = discover_ssdp(timeout)
    all_devices.extend(devices)

    # 方法2: mDNS
    devices = discover_mdns(timeout)
    all_devices.extend(devices)

    # 方法3: ARP
    devices = discover_arp_scan()
    all_devices.extend(devices)

    # 去重
    seen = set()
    unique_devices = []
    for d in all_devices:
        if d['ip'] not in seen:
            seen.add(d['ip'])
            unique_devices.append(d)

    return unique_devices

def find_cube_lite(timeout=5):
    """专门查找 Cube Lite 设备"""
    devices = discover_all(timeout)

    cube_devices = []
    for d in devices:
        model = d.get('model', '').lower()
        name = d.get('name', '').lower()
        if 'clt' in model or 'cube' in model or 'clt' in name:
            cube_devices.append(d)

    return cube_devices


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Yeelight 设备发现")
    parser.add_argument("--timeout", type=int, default=5, help="发现超时时间/秒")
    parser.add_argument("--check", type=str, help="检查指定 IP 是否为 Yeelight 设备")

    args = parser.parse_args()

    if args.check:
        # 检查指定 IP
        ip = args.check
        print(f"检查 {ip}:{YEELIGHT_PORT}...")

        if check_port(ip, YEELIGHT_PORT):
            print(f"✅ 端口开放")
            info = get_device_info(ip)
            if info:
                print(f"设备信息: {info}")
        else:
            print(f"❌ 端口不可达")
    else:
        # 发现设备
        devices = discover_all(args.timeout)

        print("\n" + "=" * 50)
        print(f"发现结果: {len(devices)} 个设备")
        print("=" * 50)

        for i, d in enumerate(devices):
            print(f"\n[{i+1}] {d.get('name', 'Unknown')}")
            print(f"    IP:   {d['ip']}")
            print(f"    Port: {d.get('port', YEELIGHT_PORT)}")
            print(f"    Model: {d.get('model', 'unknown')}")
            print(f"    ID:   {d.get('id', 'unknown')}")

        if not devices:
            print("\n❌ 未发现设备")
            print("\n💡 提示:")
            print("   1. 确保设备已开机")
            print("   2. 确保设备和电脑在同一局域网")
            print("   3. 确保设备开启了 LAN 控制")
            print("   4. 如果知道 IP，可用 --check <ip> 验证")