# yeelight-claude-hook 演示脚本

> 拍摄时长：约 60 秒
> 拍摄设备：手机（横屏）
> 拍摄角度：电脑屏幕 + Yeelight 灯同框

---

## 准备工作

```bash
# 1. 确保 daemon 运行
launchctl list | grep yeelight

# 2. 如果未运行，启动它
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist

# 3. 准备命令窗口（保持打开）
cd /Users/jacob/Workspace/claude-work/yeelight
```

---

## 演示流程

### 场景 1：开场 (0-5秒)

**画面**：Yeelight 灯关闭状态

**动作**：无

---

### 场景 2：START - 发送消息 (5-15秒)

**命令**：
```bash
python3 yeelight-client.py --state start --duration 3
```

**效果**：彩虹背景 + 白字 "START" 流动

**旁白/字幕**：
> "当用户发送消息时，显示彩虹 START 效果"

---

### 场景 3：THINKING - 工具执行中 (15-30秒)

**命令**：
```bash
python3 yeelight-client.py --state thinking --duration 10
```

**效果**：蜡烛火焰闪烁 + "THINK" 文字

**旁白/字幕**：
> "Claude 思考时，显示蜡烛闪烁效果"

---

### 场景 4：DONE - 工具完成 (30-40秒)

**命令**：
```bash
python3 yeelight-client.py --state done
```

**效果**：柔和蓝色渐入渐出 + "DONE"

**旁白/字幕**：
> "工具执行完成，蓝色脉冲提示"

---

### 场景 5：COMPLETE - 任务完成 (40-55秒)

**命令**：
```bash
python3 yeelight-client.py --state complete
```

**效果**：绿色呼吸灯（无限循环）

**旁白/字幕**：
> "任务全部完成，绿色呼吸表示成功"

---

### 场景 6：结束 (55-60秒)

**命令**：
```bash
python3 yeelight-client.py --state end
```

**效果**：红色渐出关灯

**旁白/字幕**：
> "yeelight-claude-hook - 让 AI 编程更有仪式感"

---

## 拍摄检查清单

- [ ] Yeelight 设备已开机并联网
- [ ] daemon 服务运行中
- [ ] 命令窗口准备好
- [ ] 手机横屏拍摄
- [ ] 光线充足（但不要太亮影响灯效）
- [ ] 背景整洁

---

## 备用命令（出错时重置）

```bash
# 关灯
python3 yeelight-client.py --state off

# 重启 daemon
launchctl unload ~/Library/LaunchAgents/com.yeelight.daemon.plist
launchctl load ~/Library/LaunchAgents/com.yeelight.daemon.plist
```

---

## 字幕文案

```
yeelight-claude-hook

发送消息 → START 彩虹
Claude 思考 → 蜡烛闪烁
工具完成 → 蓝色脉冲
任务完成 → 绿色呼吸

让你的 Claude Code 会发光

GitHub: jacobke/yeelight-claude-hook
```

---

## 快捷演示（一条命令）

如果想一次性演示所有效果：

```bash
python3 yeelight-client.py --state start --duration 3 && \
sleep 2 && \
python3 yeelight-client.py --state thinking --duration 8 && \
sleep 1 && \
python3 yeelight-client.py --state done && \
sleep 3 && \
python3 yeelight-client.py --state complete && \
sleep 8 && \
python3 yeelight-client.py --state end
```

总时长约 25 秒，效果依次切换。
