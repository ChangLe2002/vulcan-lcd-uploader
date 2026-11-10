# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
    按回车才开始抓包；自动探测接口；抓完自动分析。

.DESCRIPTION
    两个改进：
    * ``-Interface`` 留空时自动探测哪个 USBPcapN 上有智屏流量（按协议帧头 5A9FA9 判断）。
      重启/插拔后根集线器编号会变，硬编码接口会抓到空文件（本项目踩过）。
    * 抓不到数据时给出明确结论，而不是抛异常。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\capture_ready.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\capture_ready.ps1 -Seconds 150
#>
[CmdletBinding()]
param(
    [int]$Seconds = 150,
    [string]$Out = "captureA",
    [string]$Interface = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { $null = & chcp.com 65001 2>&1 } catch { }
$env:PYTHONIOENCODING = "utf-8"

$Root   = Split-Path -Parent $PSScriptRoot
$UsbCmd = "C:\Program Files\USBPcap\USBPcapCMD.exe"
$Tshark = "C:\Program Files\Wireshark\tshark.exe"
$Python = Join-Path $Root ".venv_local\python\Scripts\python.exe"
$Header = "5a9fa9"

function Fail($m) { Write-Host "[错误] $m" -ForegroundColor Red; exit 1 }

function Get-Payload([string]$pcap) {
    if (-not (Test-Path $pcap)) { return @() }
    $lines = & $Tshark -r $pcap -Y "usb.capdata" -T fields -e usb.capdata 2>$null
    return @($lines | Where-Object { $_ -and $_.Trim() })
}

function Count-Frames($lines) {
    if ($null -eq $lines) { return 0 }
    return @($lines | Where-Object { $_ -and $_.ToLower().Contains($Header) }).Count
}

if (-not (Test-Path $UsbCmd)) { Fail "未找到 USBPcapCMD" }
if (-not (Test-Path $Tshark)) { Fail "未找到 tshark" }
if (-not (Test-Path $Python)) { Fail "未找到项目虚拟环境" }

$svc = Get-Service iGameCenterService -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne 'Running') { Fail "iGameCenterService 未运行，请先打开 iGame Center" }

$dev = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.InstanceId -like "*VID_1B3F*" }
if (-not $dev) { Fail "未检测到智屏设备（VID_1B3F），请检查 USB 线" }

if (-not $Interface) {
    Write-Host ""
    Write-Host "=== 自动探测接口（每个 4 秒，按帧头 5A9FA9 判断）===" -ForegroundColor Cyan
    foreach ($i in 1..4) {
        $name = "USBPcap$i"
        $probe = Join-Path $Root "probe_$name.pcap"
        Remove-Item $probe -ErrorAction SilentlyContinue
        $proc = Start-Process -FilePath $UsbCmd `
            -ArgumentList @("-d", "\\.\$name", "-o", $probe, "-A", "-s", "65535") `
            -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 4
        if (-not $proc.HasExited) { $proc | Stop-Process -Force }
        Start-Sleep -Milliseconds 400
        $lines = Get-Payload $probe
        $hits = Count-Frames $lines
        Remove-Item $probe -ErrorAction SilentlyContinue
        Write-Host ("  {0}: {1} 个包，{2} 个含协议帧头" -f $name, $lines.Count, $hits)
        if ($hits -gt 0) { $Interface = $name; break }
    }
    if (-not $Interface) { Fail "四个接口都没有协议流量。确认 iGame Center 在运行、屏幕在刷新。" }
    Write-Host ("  使用接口: " + $Interface) -ForegroundColor Green
}

Write-Host ""
Write-Host "=========== 操作清单（分配流程，不是上传）===========" -ForegroundColor Cyan
Write-Host "  1. 先别动 10 秒（基线：只有心跳）"
Write-Host "  2. 点【1 号槽位】-> 弹窗选【自定义图片】-> 确定"
Write-Host "     -> 我的图库里选【img2】-> 选择 -> 确定"
Write-Host "  3. 看屏幕：是否切到 img2"
Write-Host "  4. 再点【1 号槽位】-> 同样流程 -> 选【img1】-> 确定"
Write-Host "  5. 看屏幕：是否切回 img1"
Write-Host "  说明：上传只是进图库；要抓的是「把某张图分配给槽位」这一步"
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host ("准备好了就按回车开始抓包（{0} 秒）… 按 Ctrl+C 取消" -f $Seconds) -ForegroundColor Yellow
$null = Read-Host

$pcap = Join-Path $Root "$Out.pcap"
$txt  = Join-Path $Root "$Out.txt"
Remove-Item $pcap, $txt -ErrorAction SilentlyContinue

Write-Host ""
Write-Host ">>> 开始抓包，现在按上面的步骤操作 <<<" -ForegroundColor Green
$proc = Start-Process -FilePath $UsbCmd `
    -ArgumentList @("-d", "\\.\$Interface", "-o", $pcap, "-A", "-s", "65535") `
    -PassThru -WindowStyle Hidden

$remaining = $Seconds
while ($remaining -gt 0) {
    Start-Sleep -Seconds ([Math]::Min(30, $remaining))
    $remaining -= [Math]::Min(30, $remaining)
    if ($remaining -gt 0) { Write-Host ("    剩余 {0} 秒…" -f $remaining) }
}
if (-not $proc.HasExited) { $proc | Stop-Process -Force }
Start-Sleep -Seconds 2

Write-Host ""
Write-Host ">>> 抓包结束 <<<" -ForegroundColor Cyan
if (-not (Test-Path $pcap)) { Fail "没有生成抓包文件（接口 $Interface 可能不可用）" }

$lines = Get-Payload $pcap
$frames = Count-Frames $lines
Write-Host ("    数据包: {0}，含协议帧头: {1}" -f $lines.Count, $frames)

if ($lines.Count -eq 0) {
    Write-Host ""
    Write-Host "该接口没有抓到任何数据。" -ForegroundColor Yellow
    Write-Host "可能接口不对：重启或插拔后 USBPcap 编号会变。" -ForegroundColor Yellow
    Write-Host "试试显式指定：-Interface USBPcap1 / USBPcap3 …" -ForegroundColor Yellow
    exit 2
}

$lines | Set-Content -Path $txt -Encoding UTF8 -Force
Write-Host ("    已写出: " + $txt)

Write-Host ""
Write-Host "===== 非 ACK/数据 帧时间线 =====" -ForegroundColor Cyan
& $Python (Join-Path $Root "tools\scan_frames.py") $txt

Write-Host ""
Write-Host "把上面的时间线发给我，或者直接说一声，我自己读文件。" -ForegroundColor Green
