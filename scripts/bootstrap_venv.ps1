# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
    在项目根目录创建/接管独占虚拟环境 .venv_local\python，并安装依赖。

.DESCRIPTION
    硬性约定：
      1. .venv_local\python 已存在 -> 直接接管，不重建、不升级；
      2. 不存在 -> 用 Python 3.11（退化 3.10）创建；
      3. 找不到 3.10/3.11 -> 非零退出并打印修复指引，绝不回退到系统 Python；
      4. 安装后调用 scripts\verify_env.py 做断言。

    兼容 Windows PowerShell 5.1。

.PARAMETER Dev
    额外安装 requirements-dev.txt（pyinstaller / pytest）。

.PARAMETER PythonExe
    显式指定基础解释器路径，跳过自动探测。

.PARAMETER Recreate
    删除并重建虚拟环境（危险操作，会重新下载全部依赖）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_venv.ps1 -Dev
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Recreate,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

# 控制台切到 UTF-8：PowerShell 5.1 默认 GBK 代码页会把 Python 的 UTF-8 中文输出显示成乱码
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { $null = & chcp.com 65001 2>&1 } catch { }

$Root     = Split-Path -Parent $PSScriptRoot
$VenvDir  = Join-Path $Root ".venv_local\python"
$VenvPy   = Join-Path $VenvDir "Scripts\python.exe"
$ReqFile  = Join-Path $Root "requirements.txt"
$ReqDev   = Join-Path $Root "requirements-dev.txt"
$VerifyPy = Join-Path $PSScriptRoot "verify_env.py"

function Write-Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    [WARN] $msg" -ForegroundColor Yellow }

function Get-InterpMajorMinor([string]$Path) {
    # 返回 "3.11" / "3.12" / ""（不可用）
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    try {
        $out = & $Path -c "import sys;print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
        if ($LASTEXITCODE -ne 0) { return "" }
        return ($out | Select-Object -First 1).Trim()
    } catch {
        return ""
    }
}

function Test-Supported([string]$ver) {
    return ($ver -eq "3.11" -or $ver -eq "3.10")
}

function Find-BasePython() {
    if ($PythonExe -ne "") {
        if (-not (Test-Path -LiteralPath $PythonExe)) { throw "指定的 PythonExe 不存在: $PythonExe" }
        $v = Get-InterpMajorMinor $PythonExe
        if (-not (Test-Supported $v)) { throw "指定的解释器版本为 '$v'，本项目只支持 3.10 / 3.11" }
        return @{ Path = $PythonExe; Version = $v; How = "参数 -PythonExe" }
    }

    $candidates = New-Object System.Collections.ArrayList

    # 1) py 启动器
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($tag in @("-3.11", "-3.10")) {
            try {
                $p = & $pyLauncher.Source $tag -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $p) {
                    $p = ($p | Select-Object -First 1).Trim()
                    [void]$candidates.Add(@{ Path = $p; How = "py $tag" })
                }
            } catch { }
        }
    }

    # 2) 注册表（用户级优先于机器级）
    foreach ($hive in @("HKCU:\SOFTWARE\Python\PythonCore", "HKLM:\SOFTWARE\Python\PythonCore")) {
        foreach ($vtag in @("3.11", "3.10")) {
            $key = Join-Path $hive "$vtag\InstallPath"
            if (Test-Path $key) {
                $ip = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue)."(default)"
                if (-not $ip) { $ip = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue)."ExecutablePath" }
                if ($ip) {
                    if (Test-Path $ip) { [void]$candidates.Add(@{ Path = $ip; How = "registry $vtag" }) }
                    else {
                        $cand = Join-Path $ip "python.exe"
                        if (Test-Path $cand) { [void]$candidates.Add(@{ Path = $cand; How = "registry $vtag" }) }
                    }
                }
            }
        }
    }

    # 3) 常见安装位置
    foreach ($p in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe"
    )) {
        if (Test-Path -LiteralPath $p) { [void]$candidates.Add(@{ Path = $p; How = "well-known path" }) }
    }

    # 4) PATH 上的 python（必须是真实解释器，排除 WindowsApps 存根）
    $pathPy = Get-Command python -ErrorAction SilentlyContinue
    if ($pathPy -and ($pathPy.Source -notlike "*\WindowsApps\*")) {
        [void]$candidates.Add(@{ Path = $pathPy.Source; How = "PATH" })
    }

    foreach ($c in $candidates) {
        $v = Get-InterpMajorMinor $c.Path
        if (Test-Supported $v) {
            return @{ Path = $c.Path; Version = $v; How = $c.How }
        }
    }

    # 诊断信息
    Write-Host ""
    Write-Host "找到的候选解释器（但版本不可用）：" -ForegroundColor Yellow
    foreach ($c in $candidates) {
        $v = Get-InterpMajorMinor $c.Path
        if ($v -eq "") { $v = "<不可执行>" }
        Write-Host ("  - {0}  => {1}  [{2}]" -f $c.Path, $v, $c.How)
    }

    throw @"
未找到 Python 3.10 / 3.11，已中止（不会回退到系统 Python）。

修复方式（任选其一）：
  1) winget install --id Python.Python.3.11 --exact --scope user --accept-package-agreements --accept-source-agreements
  2) 从 https://www.python.org/downloads/ 安装 3.11.x，安装时勾选 "Add python.exe to PATH"
  3) 已装在非标准路径时，显式指定：
     powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_venv.ps1 -PythonExe "D:\Python311\python.exe"
"@
}

Write-Host "Vulcan LCD Uploader - 环境引导" -ForegroundColor White
Write-Host "项目根目录: $Root"
Write-Host "目标虚拟环境: $VenvDir"

# ---------------- 1. 接管或创建 ----------------
if ($Recreate -and (Test-Path -LiteralPath $VenvDir)) {
    Write-Step "删除旧虚拟环境（-Recreate）"
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
    Write-Ok "已删除 $VenvDir"
}

$NeedCreate = $true
if (Test-Path -LiteralPath $VenvPy) {
    $NeedCreate = $false
    Write-Step "检测到已有虚拟环境，直接接管"
    $v = Get-InterpMajorMinor $VenvPy
    if (-not (Test-Supported $v)) {
        throw "已有虚拟环境版本为 '$v'，不在 3.10/3.11 范围内。请加 -Recreate 重建（会重新下载依赖）。"
    }
    Write-Ok "解释器 $VenvPy (Python $v)"
    Write-Warn2 "不重建、不升级已有环境；如需全新环境请加 -Recreate"
}

if ($NeedCreate) {
    Write-Step "探测基础解释器"
    $base = Find-BasePython
    Write-Ok ("使用 Python {0}: {1}  (来源: {2})" -f $base.Version, $base.Path, $base.How)

    Write-Step "创建虚拟环境（venv，不继承系统 site-packages）"
    $parent = Split-Path -Parent $VenvDir
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    & $base.Path -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败（venv 退出码 $LASTEXITCODE）" }
    if (-not (Test-Path -LiteralPath $VenvPy)) { throw "创建后仍未找到 $VenvPy" }
    Write-Ok "已创建 $VenvDir"
}

# ---------------- 2. 安装依赖 ----------------
Write-Step "升级 pip"
& $VenvPy -m pip install --upgrade pip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败（退出码 $LASTEXITCODE）" }

Write-Step "安装运行期依赖 requirements.txt"
& $VenvPy -m pip install -r $ReqFile --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败（退出码 $LASTEXITCODE）" }
Write-Ok "requirements.txt 完成"

if ($Dev) {
    Write-Step "安装开发期依赖 requirements-dev.txt"
    & $VenvPy -m pip install -r $ReqDev --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "开发依赖安装失败（退出码 $LASTEXITCODE）" }
    Write-Ok "requirements-dev.txt 完成"
} else {
    Write-Warn2 "未安装 dev 依赖（pyinstaller / pytest）。需要打包时请加 -Dev"
}

# ---------------- 3. 自检 ----------------
Write-Step "运行环境自检 scripts\verify_env.py"
& $VenvPy $VerifyPy
$verifyCode = $LASTEXITCODE

Write-Host ""
if ($verifyCode -eq 0) {
    Write-Host "环境就绪。" -ForegroundColor Green
    Write-Host "激活方式：.\.venv_local\python\Scripts\Activate.ps1"
    exit 0
} else {
    Write-Host "自检未通过（退出码 $verifyCode），请按上方提示处理。" -ForegroundColor Red
    exit $verifyCode
}
