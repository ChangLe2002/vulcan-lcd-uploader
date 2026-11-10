# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
    在项目虚拟环境中打包，并对产物做冒烟自检。

.DESCRIPTION
    1. 断言 pyinstaller 来自 .venv_local（绝不用系统 Python 打包）；
    2. 清掉旧产物后执行 pyinstaller main.spec；
    3. 用 dist 里的 exe 跑 `--check`，非 0 退出码即视为失败；
    4. 打印产物大小与失败排查建议。

    闪退排查：加 -Console 重新打包，会出现控制台窗口，可直接看到 traceback。

.PARAMETER Console
    生成控制台版（排查专用）。

.PARAMETER NoClean
    保留 build 目录以加速增量打包。
#>
[CmdletBinding()]
param(
    [switch]$Console,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { $null = & chcp.com 65001 2>&1 } catch { }

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv_local\python\Scripts\python.exe"
$Spec = Join-Path $Root "main.spec"
$DistExe = Join-Path $Root "dist\VulcanLCDUploader\VulcanLCDUploader.exe"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }

Step "环境断言"
if (-not (Test-Path $Python)) {
    throw "未找到项目虚拟环境解释器: $Python。请先运行 scripts\bootstrap_venv.ps1 -Dev"
}
$exePath = & $Python -c "import sys; print(sys.executable)"
Write-Host "    解释器: $exePath"
if ($exePath -notlike "*\.venv_local\*") {
    throw "解释器不在项目虚拟环境中，拒绝打包（禁止使用系统 Python）。"
}
& $Python -c "import PyInstaller; print('    PyInstaller', PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 未安装。请运行 scripts\bootstrap_venv.ps1 -Dev" }
Ok "使用虚拟环境打包"

Step "清理旧产物"
if (-not $NoClean) {
    foreach ($dir in @((Join-Path $Root "build"), (Join-Path $Root "dist"))) {
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    }
}
Ok "已清理"

Step "执行 PyInstaller"
if ($Console) { $env:VULCAN_CONSOLE = "1" } else { Remove-Item Env:VULCAN_CONSOLE -ErrorAction SilentlyContinue }
Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean $Spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}
if (-not (Test-Path $DistExe)) { throw "未生成产物: $DistExe" }
Ok "产物: $DistExe"

Step "冒烟自检（--check）"
$proc = Start-Process -FilePath $DistExe -ArgumentList "--check" -Wait -PassThru
Write-Host ("    退出码: " + $proc.ExitCode)
$checkFile = Join-Path $Root "logs\startup_check.txt"
if (Test-Path $checkFile) {
    Write-Host "    ---- startup_check.txt ----"
    Get-Content $checkFile -Encoding UTF8 | ForEach-Object { Write-Host ("    " + $_) }
}
if ($proc.ExitCode -ne 0) {
    Write-Host ""
    Write-Host "自检失败。排查建议：" -ForegroundColor Yellow
    Write-Host "  1) 用控制台版重新打包: powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Console"
    Write-Host "  2) 直接运行 exe 看 traceback，缺什么模块就加到 main.spec 的 hiddenimports"
    throw "产物自检未通过（退出码 $($proc.ExitCode)）"
}
Ok "产物可正常启动"

Step "产物大小"
$dirSize = (Get-ChildItem (Join-Path $Root "dist\VulcanLCDUploader") -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("    {0:N1} MB  ({1} 个文件)" -f ($dirSize / 1MB), (Get-ChildItem (Join-Path $Root "dist\VulcanLCDUploader") -Recurse -File).Count)
Write-Host ""
Write-Host "打包完成：dist\VulcanLCDUploader\VulcanLCDUploader.exe" -ForegroundColor Green

exit 0
