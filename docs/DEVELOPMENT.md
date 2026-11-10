# 开发与构建

## 环境

- Python 3.11（3.10 亦可）
- Windows 10 / 11

```powershell
# 虚拟环境（仓库自带的便携环境在 .venv_local，可另建）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest      # 测试用
```

运行：

```powershell
.\.venv\Scripts\python.exe main.py                 # 正常启动
.\.venv\Scripts\python.exe main.py --debug         # 调试模式（解锁实验功能）
.\.venv\Scripts\python.exe main.py --dry-run       # 只读模式，不写设备
.\.venv\Scripts\python.exe main.py --ui=old        # 旧界面（浅色）
```

## 目录结构

```
src/vulcan_lcd/
├── core/           帧协议、校验、串口传输、握手
├── media/          图像解码、ffmpeg 编码、pak 容器、预处理
├── features/       业务能力：上传、轮播、监控、设置、清理、素材库、自启
├── system/         官方服务控制、子进程调用
├── diagnostics/    结构化日志、调试报告
├── ui/             旧界面（浅色，--ui=old）
└── ui2/            新界面（深色，默认）
tests/              450+ 项 pytest 测试
tools/              抓包分析、批量上传、截图等一次性脚本
docs/               协议文档、安装、开发、排错、路线图
installer/          Inno Setup 脚本
scripts/            构建与打包脚本
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # 全量
.\.venv\Scripts\python.exe -m pytest tests -k protocol # 单个模块
```

CI：`.github/workflows/tests.yml`，在 `windows-latest` 上跑全量测试。

## 打包

```powershell
# 1) PyInstaller onedir -> dist\VulcanLCDUploader\
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1

# 2) 绿色安装包（zip + install.cmd）
.\.venv\Scripts\python.exe .\scripts\package_portable.py

# 3) 常规安装包（需要 Inno Setup 6）
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -SkipApp
```

产物自检：

```powershell
.\dist\VulcanLCDUploader\VulcanLCDUploader.exe --check   # 退出码 0 表示完整
```

## 发版流程

1. 更新 `src/vulcan_lcd/meta.py` 的 `APP_VERSION`
2. 更新 `CHANGELOG.md`，写 `docs/RELEASE_NOTES_v<版本>.md`
3. 重新打包（上面三步）
4. 提交并推送，打标签：`git tag v1.0.0 && git push --tags`
5. 在 GitHub 创建 Release，附加 `dist/installer/` 下的两个文件

## 代码约定

- 类型注解齐全，`from __future__ import annotations`
- 串口写操作必须经过 `FeatureGate.require_write()`
- 新增协议字段必须有证据（抓包 / 反编译），写入 `docs/PROTOCOL.md`
- 不引入网络依赖

## 调试技巧

| 需求 | 做法 |
| --- | --- |
| 看串口收发 | `--debug` 启动，日志里会记录 `tx_hex` / `rx_hex` |
| 只读排查 | `--dry-run`，所有写操作被拦截 |
| 只做编码 | `VulcanLCDUploader.exe --encode 图片.gif` |
| 导出报告 | 菜单「文件 → 导出调试报告」，生成 `debug_report.md/json` |
| 界面截图 | `tools/shot_new_ui.py`（离屏渲染，不需要真实窗口） |
