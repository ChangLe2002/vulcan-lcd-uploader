# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
    抓一次 USB 流量并自动分析协议帧（无需 Npcap）。

.DESCRIPTION
    为什么不用 dumpcap：Wireshark 静默安装不带 Npcap，dumpcap 会报
    "Unable to load Npcap (wpcap.dll)"。而 **tshark 读 pcap 文件不需要 Npcap**，
    所以用 USBPcapCMD 抓包、tshark 只做解析。

    为什么不用 VID 过滤：``usb.idVendor`` 只出现在**设备枚举的描述符**里。
    抓包开始时设备早已枚举完成，按 VID 过滤会得到 0 条 —— 这是本项目踩过的坑。
    这里改为按**协议帧头 5A 9F A9** 识别设备流量。

    前置条件：
      1. 已安装 USBPcap 并**重启过一次**（过滤驱动开机时才挂到根集线器）；
      2. 以管理员身份运行；
      3. 抓包期间先关掉本项目 GUI。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\capture_usb.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\capture_usb.ps1 -Seconds 30
#>
[CmdletBinding()]
param(
    [string]$Interface = "",
    [int]$Seconds = 25,
    [string]$Out = "capture"
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { $null = & chcp.com 65001 2>&1 } catch { }
# 让 Python 子进程也按 UTF-8 输出，否则中文在控制台会变乱码
$env:PYTHONIOENCODING = "utf-8"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv_local\python\Scripts\python.exe"
$UsbCmd = "C:\Program Files\USBPcap\USBPcapCMD.exe"
$Tshark = "C:\Program Files\Wireshark\tshark.exe"
$Header = "5a9fa9"

function Fail($msg) { Write-Host "[错误] $msg" -ForegroundColor Red; exit 1 }

function Get-PayloadLines([string]$pcap) {
    $raw = & $Tshark -r $pcap -Y "usb.capdata" -T fields -e usb.capdata 2>$null
    $filtered = @($raw | Where-Object { $_ -and $_.Trim() })
    # 逗号运算符：保证空数组也按数组返回，不会被"展开"成 $null
    return ,$filtered
}

function Count-FrameLines($lines) {
    if ($null -eq $lines) { return 0 }
    $hits = @($lines | Where-Object { $_ -and $_.ToLower().Contains($Header) })
    return $hits.Count
}

Write-Host "=== 环境检查 ==="
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "需要管理员权限。" }
if (-not (Test-Path $UsbCmd)) { Fail "未找到 USBPcapCMD：$UsbCmd" }
if (-not (Test-Path $Tshark)) { Fail "未找到 tshark：$Tshark" }
if (-not (Test-Path $Python)) { Fail "未找到项目虚拟环境：$Python" }

$svc = Get-Service USBPcap -ErrorAction SilentlyContinue
if (-not $svc) { Fail "USBPcap 服务未安装。" }
if ($svc.Status -ne "Running") { Start-Service USBPcap; Start-Sleep -Seconds 1 }
Write-Host "  USBPcap 服务: $((Get-Service USBPcap).Status)"

if (Get-Process VulcanLCDUploader -ErrorAction SilentlyContinue) {
    Write-Host "  [提示] 本工具仍在运行，建议先关闭。" -ForegroundColor Yellow
}

function Test-Interface([string]$name, [int]$sec = 5) {
    $probe = Join-Path $Root "probe_$name.pcap"
    Remove-Item $probe -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $UsbCmd `
        -ArgumentList @("-d", "\\.\$name", "-o", $probe, "-A", "-s", "65535") `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds $sec
    if (-not $proc.HasExited) { $proc | Stop-Process -Force }
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path $probe)) { return @{ Ok = $false; Reason = "控制设备不存在（未重启？）" } }
    $lines = Get-PayloadLines $probe
    $frames = Count-FrameLines $lines
    Remove-Item $probe -ErrorAction SilentlyContinue
    return @{ Ok = ($frames -gt 0); Reason = ("{0} 个包，其中 {1} 个含协议帧头" -f $lines.Count, $frames) }
}

if (-not $Interface) {
    Write-Host ""
    Write-Host "=== 探测智屏挂在哪个根集线器（每个 5 秒，按帧头 5A9FA9 识别）==="
    foreach ($i in 1..4) {
        $name = "USBPcap$i"
        $r = Test-Interface $name
        Write-Host ("  {0}: {1}" -f $name, $r.Reason)
        if ($r.Ok) { $Interface = $name; break }
    }
    if (-not $Interface) {
        Fail "四个接口都没找到协议帧。确认 iGameCenterService 正在运行（它会每秒发时间帧）。"
    }
}

Write-Host ""
Write-Host ("=== 开始抓包 {0} 秒（{1}）===" -f $Seconds, $Interface) -ForegroundColor Cyan
Write-Host "  现在切到 iGame Center，完成一次 GIF 上传。" -ForegroundColor Yellow
Write-Host ""

$pcap = Join-Path $Root "$Out.pcap"
$txt = Join-Path $Root "$Out.txt"
Remove-Item $pcap -ErrorAction SilentlyContinue

$capture = Start-Process -FilePath $UsbCmd `
    -ArgumentList @("-d", "\\.\$Interface", "-o", $pcap, "-A", "-s", "65535") `
    -PassThru -WindowStyle Hidden
Start-Sleep -Seconds $Seconds
if (-not $capture.HasExited) { $capture | Stop-Process -Force }
Start-Sleep -Seconds 1
if (-not (Test-Path $pcap)) { Fail "抓包失败：未生成 $pcap" }
Write-Host ("  抓包完成: {0}  ({1:N1} KB)" -f $pcap, ((Get-Item $pcap).Length / 1KB))

Write-Host ""
Write-Host "=== 提取载荷（不做 VID 过滤）==="
$lines = Get-PayloadLines $pcap
Write-Host ("  数据包: " + $lines.Count + "，含帧头: " + (Count-FrameLines $lines))
$lines | Set-Content -Path $txt -Encoding UTF8
if ($lines.Count -eq 0) { Fail "没有抓到任何 USB 数据包。" }

Write-Host ""
Write-Host "=== 切帧分析 ==="
& $Python (Join-Path $Root "tools\decode_capture.py") $txt --format tshark --dump-dir (Join-Path $Root "frames")

Write-Host ""
Write-Host ("下一步：把上面的输出发给我（$txt 已保存在项目根目录）。") -ForegroundColor Green
