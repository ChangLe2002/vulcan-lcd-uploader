# 安全审查与性能报告

> 审查日期：2026-11-06　范围：`src/vulcan_lcd/`、`main.py`、`main.spec`、依赖清单
> 结论：**未发现可利用的安全问题**；已修复 1 项"子进程弹控制台"的体验缺陷（同时也消除了
> 窗口抢焦点的骚扰）。性能方面空闲占用从 2.0% 降到 1.0%，托盘状态降到 0.00% CPU / 19 MB。

---

## 1. 安全审查

### 1.1 危险调用扫描

| 检查项 | 结果 |
| --- | --- |
| `shell=True` / `os.system` / `os.popen` | **无** |
| `eval` / `exec` / `pickle` / `yaml.load` | **无**（命中的 `box.exec()` 是 QMessageBox 的模态调用） |
| 网络访问（requests / urllib / socket） | **无**，程序不联网、不上报 |
| 动态 `__import__` | 无 |

### 1.2 子进程

用的是 **6 处 `subprocess.run`**，全部满足：

* 参数是**列表**，不经 shell，不存在命令注入；
* 可执行文件是**绝对路径**（`sc.exe` 由系统路径解析，`ffmpeg` 经 `find_ffmpeg()` 返回绝对路径），
  不依赖当前目录，避免"工作目录里放个同名 exe"的劫持；
* 全部带 `CREATE_NO_WINDOW` + `STARTF_USESHOWWINDOW/SW_HIDE`（`system/proc.py`），
  既不弹黑框，也不会抢焦点。

ffmpeg 输入通过 **stdin 管道**喂字节，不写临时文件、不拼命令行字符串。

### 1.3 注册表

只写 **`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`** 下的单个值 `VulcanLCDUploader`：

* 仅当前用户，不需要管理员；
* 写入的值是两个**带引号的绝对路径**（`"pythonw.exe" "main.py"` 或 `"exe路径"`），
  路径里的空格不会破坏命令；
* 提供 `disable()` 删除该值，删除后无残留。

### 1.4 文件系统

* 所有可写文件都在**程序自身目录**（`logs/`、`ui_prefs.json`、`recent_files.json`、
  `device_state.json`、`config/settings.user.json`），不碰系统目录、不碰用户文档；
* 唯一的临时文件是注册表原子写入用的 `tempfile.mkstemp`（系统临时目录、随机名），
  写完 `os.replace` 后 `unlink(missing_ok=True)` 清理；
* 删除操作只有两种：删自己写的临时文件、删**设备上**的文件（走协议，不碰本地磁盘）；
* 设备返回的文件名（`imgN.pak`）只用于串口协议，**从不拼成本地路径**，无路径穿越风险。

### 1.5 协议写入安全

* 生产模式下只有 `feature_registry.json` 里标记 `verified` 的功能能写串口（`gate.require_write`）；
* `--dry-run` 下所有写操作被拦截；
* 清理设备文件默认只删"本工具上传过且记录在台账里的"文件，删 `img2+` 需要二次确认框。

### 1.6 打包

`main.spec`：`upx=False`（UPX 压缩是杀软误报的主因）、`console=False`（仅排查时用环境变量开）、
**onedir** 而非 onefile（不往 `%TEMP%` 解压自身，启动快、也不给临时目录留可写载荷）。

### 1.7 依赖

| 包 | 版本 | 说明 |
| --- | --- | --- |
| pyserial | 3.5 | 仅串口读写 |
| Pillow | 11.3.0 | 图像解码（GIF/PNG/JPEG） |
| PySide6-Essentials | 6.12.0 | 只用 QtCore/QtGui/QtWidgets，不含 WebEngine |
| nvidia-ml-py | 13.x | 官方 NVML 绑定，只读传感器 |
| psutil | 7.2.2 | 只读传感器 |

全部为**只读使用**（除 pyserial 的协议写入）。无网络库、无自动更新器。

### 1.8 需要用户知晓的两点（非漏洞，属设计约束）

1. **停/启官方服务需要管理员权限。** 普通用户运行时，接管会失败并给出明确提示；
   勾选「独立模式」后完全不碰服务，普通权限即可正常使用。
2. **日志会记录串口原始帧（十六进制）与本地文件路径**，不含任何账号/密钥；
   导出调试报告时如果分享给别人，注意里面有你的目录结构。

---

## 2. 性能优化

### 2.1 优化前后

| 指标 | 优化前 | 优化后 |
| --- | --- | --- |
| 窗口可见、空闲 CPU | 2.0%（0.61 s / 30 s） | **1.0%**（0.30 s / 30 s） |
| 最小化到托盘 CPU | — | **0.00%**（30 秒 0.000 s） |
| 最小化到托盘 内存 | 158 MB | **19 MB** |
| 空闲子进程 | 每秒 1 个 `sc query`（弹黑框） | **0 个** |

### 2.2 做了什么

1. **隐藏即休眠**：`showEvent/hideEvent/changeEvent` → `_set_active()`，
   窗口不可见时停掉时钟、传感器轮询、日志跟随三个定时器（托盘状态只剩 Qt 事件循环）。
2. **降频**：
   * 传感器采集 1 s → **2 s**；
   * 服务/串口状态刷新 1 s → **5 s**（服务状态本身还有 5 s 缓存，串口枚举 10 s）；
   * 调试日志跟随 1.5 s → **3 s**，并且**先比对文件 mtime**，没变化就不重新解析；
   * 会话栏 1 s → **5 s**，且内容不变不重绘。
3. **去掉重复子进程**：服务状态加缓存后，待机时不再每秒创建 `sc.exe`。
4. **工作集回收**：隐藏到托盘时调用 `SetProcessWorkingSetSize(-1,-1)` 把物理页还给系统，
   RSS 158 MB → **19 MB**；再唤回时按需换页，不影响使用。
5. **串口枚举缓存**：`list_ports` 有几十毫秒开销，10 秒一次足够。

### 2.3 复现测量方法

```powershell
$p = Get-Process VulcanLCDUploader
$c = $p.CPU; Start-Sleep 30; $p.Refresh()
"CPU: {0:N2}%" -f (($p.CPU - $c) / 30 * 100)
"内存: {0:N1} MB" -f ($p.WorkingSet64 / 1MB)
```

---

## 3. 结论

* 安全：无 shell 注入面、无网络、无提权、无系统目录写入、无临时载荷；唯一的持久化是
  可一键删除的 HKCU 自启动项。**可以放心日常使用。**
* 性能：可见时 1% 单核（8 核 ≈ 0.12% 整机），托盘时 0% CPU / 19 MB，属于"挂着完全无感"的水平。
