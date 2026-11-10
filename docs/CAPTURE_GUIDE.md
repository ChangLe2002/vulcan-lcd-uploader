# GIF 上传协议抓包指南

目标：抓到 **iGame Center 上传一张 GIF 时 COM4 上的完整字节流**，用 `tools/decode_capture.py`
切帧分析，从而补齐 `gif_upload` 缺失的四项协议事实（分包结构、分包大小、图片帧校验范围、像素格式）。

---

## 0. 为什么必须在 USB 层抓

`COM4` 被 `iGameCenterService` **独占**。任何用户态程序——包括本项目的嗅探器、
常见的串口监视器——打开它都会得到 `PermissionError 13`。
唯一的观察点是 USB 层：智屏是 USB 串口设备（`VID 1B3F / PID 0123`），
bulk 传输里就是串口字节流。

---

## 1. 安装（管理员 PowerShell）

```powershell
winget install --id desowin.USBPcap --exact --accept-package-agreements --accept-source-agreements
winget install --id WiresharkFoundation.Wireshark --exact --accept-package-agreements --accept-source-agreements
```

> **装完必须重启一次。**
> USBPcap 是 USB 根集线器的**上层过滤驱动**，注册表里 `UpperFilters` 虽然立刻写入，
> 但只有开机枚举 USB 时才会真正挂上去。没重启时 `\\.\USBPcap1` 这个控制设备根本不存在，
> `USBPcapCMD` 会报 `Couldn't open device - 2`。

验证（重启后）：

```powershell
Get-Service USBPcap                    # 应为 Running
Test-Path \\.\USBPcap1                 # 应为 True
```

**不需要 Npcap。** Wireshark 静默安装不会带 Npcap，`dumpcap` 会报
`Unable to load Npcap (wpcap.dll)`；但我们只用 `tshark` **读 pcap 文件**，这一步不依赖 Npcap。

---

## 2. 一条命令完成抓包 + 分析

```powershell
powershell -ExecutionPolicy Bypass -File F:\shuchu\scripts\capture_usb.ps1 -Seconds 25
```

脚本会依次做：

1. 检查管理员权限、`USBPcapCMD`、`tshark`、项目虚拟环境；
2. 自动探测 `USBPcap1..4` 哪个 root hub 上挂着 `VID 1B3F`（每个试 5 秒）；
3. 在选中的接口上抓 25 秒 —— **这 25 秒内请到 iGame Center 完成一次 GIF 上传**；
4. 用 `tshark` 过滤出该设备的 bulk 载荷，写成 `capture.txt`；
5. 调用 `tools/decode_capture.py` 切帧并打印结构分析。

---

## 3. 手动等价步骤（脚本失败时的退路）

```powershell
# 抓包（Ctrl+C 结束）
& "C:\Program Files\USBPcap\USBPcapCMD.exe" -d \\.\USBPcap2 -o F:\shuchu\capture.pcap -A -s 65535

# 提取载荷
& "C:\Program Files\Wireshark\tshark.exe" -r F:\shuchu\capture.pcap `
    -Y "usb.idVendor == 0x1b3f && usb.data_len > 0" `
    -T fields -e usb.capdata > F:\shuchu\capture.txt

# 切帧分析
.\.venv_local\python\Scripts\python.exe tools\decode_capture.py capture.txt --format tshark --dump-dir frames
```

---

## 4. 输出怎么读

`decode_capture.py` 会告诉你三件事：

1. **切出多少帧**、每帧多长、按固定 ID 分组的分布
   （`DD 22` = 时间/标题帧、`E0 1F` = 握手应答，**其余 ID 很可能就是图像通道**）；
2. **校验和是大端还是小端成立** —— 直接回答"图片帧是否沿用文字帧的大端"；
3. 每帧 payload 的长度分布 —— 用来反推分包大小。

把这段输出（以及 `capture.txt`）发回来即可。

---

## 5. 注意事项

- **抓包前关掉本项目的 GUI**，避免它去抢端口；
- 上传动作**只做一次**，多次上传混在一起会让帧边界难对齐；
- 选**小 GIF**（≤1 MB、≤20 帧），便于人工比对分包；
- 若四个接口都抓不到载荷：确认屏幕当时在刷新（服务在运行）、确认重启过、确认设备确实是 `VID 1B3F`；
- pcap 含你机器的 USB 流量，只提供该设备相关的部分。
