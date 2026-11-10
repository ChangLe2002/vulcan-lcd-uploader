# SPDX-License-Identifier: MIT
"""构建「绿色版安装包」：ZIP + 安装/卸载脚本（只用系统签名工具，绕开未签名 exe 的写入限制）。"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(r"F:\shuchu")
APP_DIR = ROOT / "dist" / "VulcanLCDUploader"
OUT_DIR = ROOT / "dist" / "installer"
VERSION = "1.0.0"
APP_NAME = "火神智屏图传工具"

INSTALL_CMD = r"""@echo off
setlocal
chcp 936 >nul
title 安装 火神智屏图传工具

set "TARGET=%LOCALAPPDATA%\Programs\VulcanLCDUploader"
set "SRC=%~dp0app"
set "EXE=%TARGET%\VulcanLCDUploader.exe"

echo ============================================
echo   火神智屏图传工具  安装程序
echo ============================================
echo.
echo 安装位置：%TARGET%
echo.

if not exist "%SRC%\VulcanLCDUploader.exe" (
  echo [错误] 找不到 app\VulcanLCDUploader.exe，请把整个压缩包解压后再运行本脚本。
  pause
  exit /b 1
)

echo [1/4] 复制文件...
if exist "%TARGET%" (
  taskkill /f /im VulcanLCDUploader.exe >nul 2>&1
  ping -n 2 127.0.0.1 >nul
)
robocopy "%SRC%" "%TARGET%" /E /NFL /NDL /NJH /NJS /R:1 /W:1 >nul
if not exist "%EXE%" (
  echo [错误] 文件复制失败。
  pause
  exit /b 1
)
rem 卸载脚本必须一起放进安装目录，否则「设置-应用」里的卸载指向不到
copy /y "%~dp0uninstall.cmd" "%TARGET%\uninstall.cmd" >nul 2>&1

echo [2/4] 创建快捷方式...
set "PS1=%TEMP%\vulcan_shortcut.ps1"
> "%PS1%" echo $ws = New-Object -ComObject WScript.Shell
>>"%PS1%" echo $s = $ws.CreateShortcut([Environment]::GetFolderPath('Programs') + '\火神智屏图传工具.lnk')
>>"%PS1%" echo $s.TargetPath = '%EXE%'
>>"%PS1%" echo $s.WorkingDirectory = '%TARGET%'
>>"%PS1%" echo $s.IconLocation = '%EXE%'
>>"%PS1%" echo $s.Description = '火神智屏图传工具'
>>"%PS1%" echo $s.Save()
>>"%PS1%" echo $d = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\火神智屏图传工具.lnk')
>>"%PS1%" echo $d.TargetPath = '%EXE%'
>>"%PS1%" echo $d.WorkingDirectory = '%TARGET%'
>>"%PS1%" echo $d.IconLocation = '%EXE%'
>>"%PS1%" echo $d.Save()
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" >nul 2>&1
del "%PS1%" >nul 2>&1

echo [3/4] 写入卸载信息...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v DisplayName /t REG_SZ /d "火神智屏图传工具 1.0.0" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v DisplayVersion /t REG_SZ /d "1.0.0" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v Publisher /t REG_SZ /d "本地工具（非官方）" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v InstallLocation /t REG_SZ /d "%TARGET%" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v DisplayIcon /t REG_SZ /d "%EXE%" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v UninstallString /t REG_SZ /d "\"%TARGET%\uninstall.cmd\"" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v NoModify /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /v NoRepair /t REG_DWORD /d 1 /f >nul

echo [4/4] 完成。
echo.
echo 已安装到：%TARGET%
echo 开始菜单和桌面都有快捷方式；卸载可在「设置 - 应用」里找到。
echo.
choice /c YN /m "现在运行程序吗"
if errorlevel 2 goto end
start "" "%EXE%"

:end
endlocal
"""

UNINSTALL_CMD = r"""@echo off
setlocal
chcp 936 >nul
title 卸载 火神智屏图传工具

set "TARGET=%LOCALAPPDATA%\Programs\VulcanLCDUploader"

rem 把自己复制到 %TEMP% 再执行：否则删不掉自己所在的文件夹
if /i not "%~dp0"=="%TEMP%\" (
  copy /y "%~f0" "%TEMP%\vulcan_uninstall.cmd" >nul 2>&1
  start "" "%TEMP%\vulcan_uninstall.cmd"
  exit /b 0
)

echo ============================================
echo   火神智屏图传工具  卸载程序
echo ============================================
echo.
set /p SURE=确定要卸载吗？[Y/N]:
if /i not "%SURE%"=="Y" (
  echo 已取消。
  exit /b 0
)

echo [1/4] 关闭正在运行的程序...
taskkill /f /im VulcanLCDUploader.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [2/4] 删除快捷方式...
set "PS1=%TEMP%\vulcan_unshort.ps1"
> "%PS1%" echo Remove-Item ([Environment]::GetFolderPath('Programs') + '\火神智屏图传工具.lnk') -Force -ErrorAction SilentlyContinue
>>"%PS1%" echo Remove-Item ([Environment]::GetFolderPath('Desktop') + '\火神智屏图传工具.lnk') -Force -ErrorAction SilentlyContinue
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" >nul 2>&1
del "%PS1%" >nul 2>&1

echo [3/4] 清理注册表...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VulcanLCDUploader" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v VulcanLCDUploader /f >nul 2>&1

echo [4/4] 删除程序文件...
cd /d "%TEMP%"
if exist "%TARGET%" rmdir /s /q "%TARGET%"

echo.
echo 卸载完成。
ping -n 3 127.0.0.1 >nul
endlocal
"""

README_TXT = r"""火神智屏图传工具 1.0.0 —— 绿色安装包
=====================================

为什么不直接给 Setup.exe？
  本机安全策略禁止「未签名程序」在 %TEMP% 创建目录，而常规安装包
  （Inno Setup）必须先把安装引擎解压到 %TEMP%，所以会报
  "Setup was unable to create the directory ...\is-XXXX.tmp. Error 5"。
  这个包改用 Windows 自带的签名工具（robocopy / PowerShell / reg）完成安装，
  不经过未签名进程写临时目录。

安装
----
1. 把整个压缩包解压到任意位置
2. 双击「install.cmd」
   - 默认装到 %LOCALAPPDATA%\Programs\VulcanLCDUploader（不需要管理员）
   - 自动创建开始菜单 + 桌面快捷方式
   - 写入「设置 - 应用」的卸载项
3. 安装完可直接运行

卸载
----
* 「设置 - 应用」→ 火神智屏图传工具 → 卸载；或
* 运行安装目录里的「uninstall.cmd」

说明
----
* 程序会在自己目录里写 logs\ 与 ui_prefs.json 等文件，所以不要装到 Program Files
* 卸载会一并删除日志与配置
* 官方 iGame Center 可留可删；不想要它的话，在软件「文件」菜单勾选「独立模式」
"""


def main() -> int:
    if not (APP_DIR / "VulcanLCDUploader.exe").is_file():
        raise SystemExit(f"找不到应用产物：{APP_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    staging = OUT_DIR / "_portable_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # 脚本用 GBK 写，中文 Windows 的 cmd 直接可读
    (staging / "install.cmd").write_text(INSTALL_CMD, encoding="gbk")
    (staging / "uninstall.cmd").write_text(UNINSTALL_CMD, encoding="gbk")
    (staging / "使用说明.txt").write_text(README_TXT, encoding="gbk")

    zip_path = OUT_DIR / f"VulcanLCDUploader-{VERSION}-portable.zip"
    if zip_path.exists():
        zip_path.unlink()

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in ("install.cmd", "uninstall.cmd", "使用说明.txt"):
            archive.write(staging / name, name)
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, f"app/{path.relative_to(APP_DIR).as_posix()}")
                count += 1

    shutil.rmtree(staging, ignore_errors=True)
    print(f"绿色包完成：{zip_path}")
    print(f"  应用文件 {count} 个，压缩包 {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
