# v1.0.0

首个正式版本。**火神智屏图传工具（Vulcan LCD Uploader）** —— 面向 iGame 火神 RTX 50 系显卡副屏
（LCD5A，1024×240）的开源上传工具，用于替代 iGame Center 完成日常换图、轮播与监控上屏。

> 非官方工具，与七彩虹（Colorful）/ iGame 无隶属或授权关系，使用风险自负。

## 下载

| 文件 | 适用场景 |
| --- | --- |
| `VulcanLCDUploader-1.0.0-portable.zip` | **推荐**。解压后双击 `install.cmd`，装到 `%LOCALAPPDATA%\Programs`，不需要管理员 |
| `VulcanLCDUploader-Setup-1.0.0.exe` | 常规安装包（中文向导）。若系统拦截未签名程序写 `%TEMP%` 会报 Error 5，请改用上面的 zip |

安装包未签名，SmartScreen 提示「未知发布者」时选择「更多信息 → 仍要运行」。

## 功能

- **图像上传**：GIF / PNG / JPEG → 设备 pak，固定 30fps 播放，与官方相同的编码管线
- **播放列表轮播**：每项独立停留秒数，自动上传 → 校验 → 循环切换
- **硬件监控上屏**：GPU 负载/温度/频率、CPU 负载/频率/内存轮显，由屏幕自身渲染
- **设备设置**：读取固件/亮度/ID、调节亮度、设置开机图、切换 Vulcan 开机动画
- **缓存清理**：安全模式（只删本工具上传的）/ 彻底模式（回收无效缓存占用的空间）
- **素材库 / 托盘常驻 / 开机自启 / 独立模式**
- **首次启动**：强制阅读 20 秒免责声明与使用说明，之后可在「帮助」重看

## 技术

Python 3.11 + PySide6(Qt6)，pyserial 串口，Pillow 解码，FFmpeg 编码，NVML/psutil 监控，
PyInstaller 打包。协议事实来自公开的逆向分析文章（CC BY-SA 4.0，仅引用事实性参数）、
开源项目 wiselike/LCD（MIT，未复制源码）以及对官方程序集的反编译查证，
证据记录在 `docs/PROTOCOL.md`。

## 已知限制

- 串口独占：上传时会临时停止 iGame Center 服务，结束后自动恢复
- 设备文件表偶尔卡死（写入有应答但不建档），**断电 10 秒**即可恢复
- 带 overlay 注入的软件（如「游戏加加」）可能导致崩溃，请先退出
- 安装包未签名

## 校验

- 450+ 项自动化测试通过
- `VulcanLCDUploader.exe --check` 退出码 0

**完整变更**：见 [CHANGELOG.md](https://github.com/ChangLe2002/vulcan-lcd-uploader/blob/main/CHANGELOG.md)
