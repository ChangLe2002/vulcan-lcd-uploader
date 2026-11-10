# 安装与卸载

## 系统要求

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11，64 位 |
| 硬件 | iGame 火神 RTX 50 系显卡，副屏可正常显示 |
| 运行库 | 无需预装，安装包已内置 Python 运行时与 Qt |
| FFmpeg | 可选。能找到时用于高质量 JPEG 编码；找不到自动退回 Pillow 编码 |
| 权限 | 普通用户即可；仅「停止/启动 iGame Center 服务」需要管理员 |

## 两种安装包

### A. 绿色包（推荐）

`VulcanLCDUploader-<版本>-portable.zip`

1. 解压到任意位置
2. 双击 `install.cmd`
3. 完成：程序装到 `%LOCALAPPDATA%\Programs\VulcanLCDUploader`，
   自动创建开始菜单与桌面快捷方式，并写入「设置 → 应用」的卸载项

这种方式只调用 Windows 自带工具（robocopy / PowerShell / reg），
不会解压到 `%TEMP%`，适合所有受限环境。

### B. 常规安装包

`VulcanLCDUploader-Setup-<版本>.exe`（Inno Setup，中文向导）

双击安装，可选择安装位置、是否创建桌面快捷方式、是否开机自启。
**如果系统禁止未签名程序写 `%TEMP%`，会报 `Error 5`，请改用绿色包。**

> 安装包没有代码签名。SmartScreen 提示「未知发布者」时，选「更多信息 → 仍要运行」。

## 卸载

三种方式任选：

1. **设置 → 应用 → 火神智屏图传工具 → 卸载**
2. 开始菜单 → **卸载 火神智屏图传工具**
3. 运行安装目录里的 `uninstall.cmd`

卸载会一并删除 `logs\`、`ui_prefs.json`、`recent_files.json`、`device_state.json`，
不会动屏幕里已上传的图片（那属于设备存储，用软件里的「清理设备缓存」处理）。

## 安装/运行会创建哪些文件

| 位置 | 用途 |
| --- | --- |
| `<安装目录>\` | 程序本体、`_internal\` 运行库、`app.ico` |
| `<安装目录>\logs\` | 按天生成的日志，出问题时可导出调试报告 |
| `<安装目录>\ui_prefs.json` | 关闭到托盘、独立模式、免责声明是否已读 |
| `<安装目录>\recent_files.json` | 素材库（最近 30 条路径） |
| `<安装目录>\device_state.json` | 上次读到的可用空间 / 固件 / 亮度 |
| `<安装目录>\config\settings.user.json` | 可选，覆盖默认配置时才存在 |
| 屏幕内部存储 | `img1..imgN.pak`，不占本地磁盘 |

绿色包的默认安装位置是 `%LOCALAPPDATA%\Programs\VulcanLCDUploader`。
**整个文件夹可以随意移动**，配置与日志会跟着走。

## 便携使用（不安装）

解压 `portable.zip` 后直接运行 `app\VulcanLCDUploader.exe` 也可以，
只是没有开始菜单/桌面快捷方式和卸载项。程序会在自己所在目录写配置与日志，
所以请放在**有写权限**的位置（不要放 `C:\Program Files`）。

## 升级

- 绿色包：下载新版本 → 解压 → 再次运行 `install.cmd`（会覆盖程序文件，保留配置）
- 常规安装包：直接安装新版本，会自动覆盖

## 遇到问题

见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
