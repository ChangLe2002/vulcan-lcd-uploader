# 贡献指南

欢迎提交 Issue / PR。为了保持"不猜协议"的底线，请先看下面的约定。

## 开发环境

```powershell
# 1. 准备解释器（项目自带便携环境，或用你自己的 Python 3.11）
.\.venv_local\python\python.exe -m venv .venv

# 2. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest

# 3. 跑测试（当前 448 项）
.\.venv\Scripts\python.exe -m pytest tests -q

# 4. 直接运行（不打包）
.\.venv\Scripts\python.exe main.py --debug --dry-run

# 5. 打包
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

## 详细文档

* 安装与卸载：[docs/INSTALL.md](docs/INSTALL.md)
* 开发、打包、发版：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
* 协议细节：[docs/PROTOCOL.md](docs/PROTOCOL.md)
* 排错：[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
* 路线图：[docs/ROADMAP.md](docs/ROADMAP.md)

## 目录结构

| 目录 | 内容 |
| --- | --- |
| `src/vulcan_lcd/core/` | 帧协议、校验、串口传输、握手 |
| `src/vulcan_lcd/media/` | 图像解码、ffmpeg 编码、pak 容器、预处理 |
| `src/vulcan_lcd/features/` | 业务能力：上传、轮播、监控、设置、清理、历史、自启 |
| `src/vulcan_lcd/ui/` | 旧界面（浅色，`--ui=old`） |
| `src/vulcan_lcd/ui2/` | 新界面（深色，默认） |
| `src/vulcan_lcd/diagnostics/` | 日志、调试报告 |
| `tests/` | pytest 测试 |
| `tools/` | 抓包分析、上传/查询等一次性脚本 |
| `docs/` | 协议文档、路线图、安全与性能报告 |
| `installer/` | Inno Setup 脚本与中文语言覆盖 |
| `decomp_all/` | **不提交**：官方程序集反编译结果（仅本地查证用） |

## 硬性约定（PR 会被拒的情况）

1. **不猜协议**：没有抓包/反编译证据的字节，不允许进生产路径；
   未验证的功能必须标 `experimental` 且被功能闸门挡住。
2. **不碰底层**：不写 VBIOS / SPI Flash / 固件，不加刷机、恢复出厂类功能。
3. **默认只读**：新增写操作必须走 `gate.require_write()`，并支持 `--dry-run`。
4. **不删已验证功能**：改动不能悄悄删掉已验证的能力；确需移除请先讨论。
5. **不留死代码**：一次性的探测脚本放 `tools/`，不要进主程序。

## 提交前自查

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # 全绿
.\.venv\Scripts\python.exe -m compileall -q src        # 无语法错误
.\.venv\Scripts\python.exe main.py --smoke=2000        # 能起能退
```

UI 改动请附一张截图（`tools/shot_main.py` 或 `tools/shot_new_ui.py` 可生成）。

## 提交信息

建议使用 Conventional Commits：

```
feat(ui2): 支持把竖屏预览放大显示
fix(serial): 修正分包边界少写 1 字节的问题
docs(protocol): 补充清理缓存抓包证据
```

## 版权

贡献的代码默认以 MIT 许可并入本项目。提交 PR 即表示你同意这一点。
