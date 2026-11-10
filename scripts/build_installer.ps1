# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
    一键构建安装包（先打包 onedir，再用 Inno Setup 生成 Setup.exe）。

.DESCRIPTION
    依赖：
      * Python 虚拟环境 .venv_local\python
      * Inno Setup 6（默认装在 %LOCALAPPDATA%\Programs\Inno Setup 6，
        可用 -IsccPath 指定；没有的话先 `winget install JRSoftware.InnoSetup`）

.PARAMETER SkipApp
    跳过 PyInstaller，直接用 dist\VulcanLCDUploader 里现有产物打安装包。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
#>
param(
    [switch]$SkipApp,
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Fail([string]$Message) {
    Write-Host "`n[失败] $Message" -ForegroundColor Red
    exit 1
}

# ---- 1. 应用本体 ----
if (-not $SkipApp) {
    Write-Host "=== 1/3 打包应用（PyInstaller onedir）===" -ForegroundColor Cyan
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\build.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "应用打包失败" }
} else {
    Write-Host "=== 1/3 跳过应用打包（-SkipApp）===" -ForegroundColor Yellow
}

$appExe = Join-Path $root "dist\VulcanLCDUploader\VulcanLCDUploader.exe"
if (-not (Test-Path $appExe)) { Fail "找不到 $appExe，请先打包应用" }

# ---- 2. 找 ISCC ----
Write-Host "=== 2/3 定位 Inno Setup ===" -ForegroundColor Cyan
$candidates = @(
    $IsccPath,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $candidates) {
    Fail "未找到 ISCC.exe。请先安装：winget install JRSoftware.InnoSetup"
}
# 只有命中一个候选时，PowerShell 会把数组折叠成字符串，必须显式取首元素
$iscc = [string](@($candidates) | Select-Object -First 1)
Write-Host ("  使用: " + $iscc)

# ---- 3. 编译安装包 ----
Write-Host "=== 3/3 编译安装包 ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Join-Path $root "dist\installer") | Out-Null
& $iscc (Join-Path $root "installer\VulcanLCDUploader.iss")
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup 编译失败" }

$setup = Get-ChildItem (Join-Path $root "dist\installer") -Filter "VulcanLCDUploader-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host ""
Write-Host "安装包完成：" -ForegroundColor Green
Write-Host ("  " + $setup.FullName)
Write-Host ("  {0:N1} MB" -f ($setup.Length / 1MB))
Write-Host ""
Write-Host "说明：" -ForegroundColor Cyan
Write-Host "  * 双击即可安装，默认装到 %LOCALAPPDATA%\Programs\VulcanLCDUploader（无需管理员）"
Write-Host "  * 卸载：开始菜单 → 卸载 火神智屏图传工具，或 设置 → 应用"
Write-Host "  * 安装时可勾选「开机自动启动」，之后可在软件「文件」菜单关闭"
