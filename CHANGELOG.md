## v1.0.0 — 首个正式版本（2026-11-10）

* 版本号从 0.4.2 提升为 **1.0.0**：功能集稳定，文档、安装包、CI 齐备，对外发布
* 界面底栏版本改为从 meta.APP_VERSION 读取，不再写死
* 发布说明改为 docs/RELEASE_NOTES_v1.0.0.md

## 2026-11-10（续二）— 仓库瘦身与工程化收尾

* 修复：安装包曾误提交进 git（74 MB），已从全部历史中清除并加入 .gitignore，
  仓库从 76 MB 降到约 3 MB（附件改由 GitHub Release 分发）
* 清理 tools/ 下的一次性脚本，新增 tools/README.md 说明各脚本用途
* 新增 .editorconfig、Issue 模板（Bug 报告 / 功能建议）
* 文档正式化：README 重构 + INSTALL / DEVELOPMENT / TROUBLESHOOTING / ROADMAP / SECURITY

## 2026-11-10（续）— 文档重构为正式开源项目结构

* README 重写：徽章、截图、功能表、系统要求、安装、快速上手、界面、FAQ、原理、安全、开发、贡献、许可
  删除开发日志式内容（本机环境说明、手动步骤、上传 GitHub 教程等）
* 新增 docs/INSTALL.md（安装/卸载/目录结构/便携用法/升级）
* 新增 docs/DEVELOPMENT.md（环境、目录、测试、打包、发版流程、调试技巧）
* 新增 docs/TROUBLESHOOTING.md（串口占用、Error 5、设备卡死、GamePP 冲突、监控读不到等）
* 新增 docs/ROADMAP.md（替代原 NEXT_STEPS.md）
* 新增 SECURITY.md（漏洞报告渠道、威胁模型、设计约束）
* 新增 docs/screenshots/（主界面、关于、免责声明，附演示素材生成脚本输出）

## 2026-11-10（续）— 关于窗口适配任意安装位置

* 关于窗口里的路径改为**跟随程序实际所在目录**（此前「程序缓存」一行写死了 LOCALAPPDATA）
* 表格改为「顶部显示当前安装目录 + 行内用 <安装目录> 占位」，长路径不再换行错乱
* 关于窗口新增「打开安装目录」按钮
* 测试补充：路径随安装位置变化、不再写死、占位符渲染（450+ 项）
* 新增 docs/RELEASE_NOTES_v0.4.2.md（GitHub Release 用）

## 2026-11-10 — 关于窗口、作者署名、开源仓库

* 新增 meta.py：统一维护应用名/作者/版本/许可/项目地址/运行期目录说明
* 「关于」改为富文本窗口（ui2/about.py）：作者 **常乐（Changle）**、MIT 许可、
  GitHub 地址、协议来源，以及**安装/运行会创建哪些文件**的表格
* 帮助菜单新增「项目主页（GitHub）」
* LICENSE 版权人改为「常乐 (Changle)」
* 开源化：新增 AUTHORS.md / CONTRIBUTING.md / .github/workflows/tests.yml，
  重写 .gitignore（排除反编译产物、抓包、打包产物、本地状态文件）
* 已 git init 并完成首个提交（147 个文件，2.4 MB）
* 测试 454 项（新增 6 项关于窗口的回归）

## 2026-11-08 — 首次启动免责声明（强制 20 秒）

* 新增 ui2/disclaimer.py：一页式文档覆盖免责声明 / 功能用法 / 协议合规 / 制作方式与技术栈
* 强制停留 20 秒：按钮显示倒计时并禁用，点 X、按 Esc 都被忽略（只提示剩余秒数）
* 接受后写 ui_prefs.json: disclaimer_accepted，之后不再打扰；帮助菜单可重看（不倒计时）
* 修复 JSON 读取不兼容 BOM 的问题（记事本/PowerShell 写出的带 BOM 文件此前会让偏好静默失效），
  涉及 ui_prefs / history / device_state / upload_ledger / 
egistry / config，改为 utf-8-sig
* 测试：新增 8 项（倒计时锁定、接受写入、BOM 容错、文案覆盖检查），总计 448 项

## 2026-11-06 夜（续）— 绿色安装包（绕开未签名程序的 Temp 限制）

**问题**：Inno Setup 的 Setup.exe 在本机报
Setup was unable to create the directory ...\is-XXXX.tmp. Error 5。
排查结论：本机策略禁止**未签名 exe** 往 %TEMP% 创建目录
（cmd/PowerShell/reg 等签名程序不受影响），与安装包内容无关。
普通安装包必须先把引擎解压到 %TEMP%，因此必然失败。

**方案**：scripts\\package_portable.py 生成
dist\\installer\\VulcanLCDUploader-0.4.2-portable.zip（43.8 MB）：
* install.cmd：robocopy 复制 + PowerShell 建快捷方式 + reg 写卸载项
* uninstall.cmd：自复制到 %TEMP% 再执行，能删掉自己所在目录
* 脚本文件名用 ASCII（中文名在 cmd/计划任务里会被编码破坏），内容仍为中文

**验证**（用计划任务模拟双击的中等完整性上下文）：
安装 → 176 文件 / 快捷方式 / 卸载项；卸载 → 目录、快捷方式、注册表全部清除。

## 2026-11-06 夜（续）— EXE 安装包

* 新增 installer\\VulcanLCDUploader.iss（Inno Setup 6 脚本）+ installer\\ChineseOverrides.isl
  （英文基底 + 中文覆盖，向导界面中文）
* 新增 scripts\\build_installer.ps1 一键构建（PyInstaller + Inno），产物 30.5 MB
* 应用图标：uild_assets\\app.ico（黄底黑 V），已注入 exe 与安装包
* 安装行为：装到 %LOCALAPPDATA%\\Programs、免管理员、可选开机自启、
  卸载清理日志与状态文件
* 验证：用「免注册表」变体在可写临时目录完成部署测试（175 文件 / 105.2 MB /
  安装目录内 --check 退出码 0）。当前沙箱 shell 会给子进程加受限令牌
  （%TEMP%、HKCU 卸载项、.lnk 写入被拒），正常桌面双击不受影响

## 2026-11-06 夜 — 安全审查与性能优化

**安全审查**（详见 docs/SECURITY_AND_PERFORMANCE.md）
* 无 shell=True / eval / exec / pickle / 网络访问
* 6 处子进程全部列表传参、绝对路径、CREATE_NO_WINDOW
* 注册表仅写 HKCU Run 单值，可一键删除
* 临时文件用 mkstemp，写完即删；设备文件名不参与本地路径拼接
* 打包 onedir + 无 UPX + 无控制台，减少杀软误报与临时载荷

**性能优化**
* 隐藏到托盘即休眠：停掉时钟/传感器/日志三个定时器 → 托盘 0.00% CPU
* 托盘时回收工作集：RSS 158 MB → 19 MB
* 传感器 2 s、服务状态 5 s（含缓存）、日志 3 s（mtime 未变则跳过）、会话栏 5 s
* 串口枚举 10 s 缓存；待机不再每秒创建 sc.exe 子进程

## 2026-11-06 晚（续）— 新界面、独立模式、闪烁修复

**新界面（ui2，默认启用）**
* 按设计图重排：顶栏（品牌/导航/串口/时钟）+ 左栏 01-03 + 中间机箱 + 右栏 04-06 + 底栏
* 横屏预览放在「04 投屏内容」；竖屏预览叠加在机箱图的显卡小屏上（圆角+微光，点击放大）
* 「旋转 180°」同时作用于预览与打包；文字投屏自动停服务→发帧→恢复服务
* 按钮自绘 + 120ms 缓动（悬停变黄、按下压暗、导航选中下划线）
* 旧界面完整保留：`--ui=old`

**独立模式**
* 文件菜单可勾选「独立模式（不管理官方服务）」，进程级开关，所有调用点自动生效
* 实测：服务名指向不存在的服务时，上传/清理/查询全部正常

**修复**
* 桌面每秒闪黑框：`01` 卡片每秒调用 `sc query`，无控制台的 GUI 进程会为子进程新建控制台窗口。
  新增 `system/proc.py`（CREATE_NO_WINDOW），并给服务状态加 5 秒、串口枚举加 3 秒缓存
* 播放列表表头右侧黑块（最后一列改为拉伸）
* 顶栏/菜单栏与深色背景不协调（统一为 BG 色，只留分隔线）
* 机箱底图换成用户提供的渲染图，小屏放大到 150×400 并做融合处理

## 2026-11-06 晚 — 彻底清理、素材库、开机自启、开机图修复

**彻底清理（新）**
* 抓包确认官方垃圾桶 = 删除 img2..img6（保留 img1），空间随即回收；
* 「清理设备缓存」按钮现在给两个选项：只删本工具上传的（安全）/ 彻底清理（删 img2 及以后）；
* 真机验证：传 2.11 MB → 空间 49.05→46.92 MB；彻底清理 → 回到 49.05 MB。

**素材库（新）**
* 预览面板顶部「最近使用」下拉，记录最近上传的素材（最多 30 条，自动清理失效路径）；
* 数据存 
ecent_files.json。

**开机自启（新）**
* 文件菜单 →「开机自启动」，写 HKCU Run 键，无需管理员；
* 写失败会自动还原勾选并提示。

**开机图修复**
* 反编译证实官方传的是 img1（Substring(0,4)，不带 .pak）；我们之前发 img1.pak，
  设备接受但不生效。已改为短名。

## 2026-11-06 下午 — 托盘、可用内存、轮播修复、设备端监控

**关闭到托盘（新）**
* 文件菜单新增可勾选项「关闭窗口时最小化到托盘」，**默认勾选**；
* 托盘图标（运行时绘制）+ 单击恢复 + 右键菜单（显示主窗口 / 退出）；
* 偏好保存在程序目录 `ui_prefs.json`，下次启动沿用。

**可用内存显示（新）**
* 顶部状态条显示「可用内存 xx MB（hh:mm 读取）」；
* 串口独占，只能在我们接管时读取，所以显示上次读到的值；
* 上传 / 清理 / 读设置 / 轮播结束时自动刷新并落盘 `device_state.json`。

**轮播修复**
* 槽位分配把「本次已分配」一并计入——设备清单有延迟，否则会重名覆盖；
* 每个素材上传后轮询等待真正登记（最多 3 秒），漏登记自动补传一次；
* 开播前做**空间预检**：不足时直接提示"请在 iGame Center 点垃圾桶清理无效缓存"。

**设备端监控上屏（反编译实现）**
* `monitor_data.py`：按 `LCD5ACore` 的 `CPU1/CPU5/GPU1/GPU3` 组帧（设备自己渲染）；
* 只保留本机读得到的指标：显卡负载/温度/频率、CPU 负载/频率/内存；
  CPU 温度、CPU/GPU 电压在 Windows + 消费卡上读不到，**不再发送**（避免显示 0°C / 0.00V）；
* 「硬件监控」页两个布局：显卡核心页、处理器单指标轮显。

**官方管线对齐（依据 decomp_all）**
* ffmpeg：`rotate=180*PI/180, pad=1024:240:x=1:y=5, fps=30` + `-vsync 0 -pix_fmt yuvj420p`；
* pak 头偏移 4 = **源视频帧率**（静态图为 0），不再是"帧间隔"。

**界面精简**
* 移除「设备连接」面板 → 顶部一行状态条；
* 移除「屏幕适配」下拉（固定原始尺寸）、「缩放」控件、「按 30fps 补帧」开关；
* 设备设置移除 Kudan 入口（本机回读始终是 Vulcan）。

## 2026-11-06 — 按完整反编译对齐官方管线

依据 `decomp_all/`（36 个程序集，`LCDImgPakHelper.ClipImage:194`）：

1. **ffmpeg 参数逐项对齐**：`rotate=180*PI/180, pad=1024:240:x=1:y=5, fps=30`，
   `-pix_fmt yuvj420p -vsync 0 -qscale:v <ImgQuality>`。此前 pad 偏移写的是 0:0，
   少了官方的 1px 右移与 5px 下移。
2. **恢复 30fps 补帧**：反编译证明官方固定 `fps=30`，此前"官方不补帧"的判断是错的。
3. **pak 头字段语义修正**：偏移 4 是**源视频帧率**（`iGame_JPG_to_Pak <pak> <sourceFPS>`），
   不是帧间隔毫秒。`build_pak(interval_ms=)` → `build_pak(fps=)`，静态图为 0。
   实测：初音 GIF → 270 帧 + 头部 fps=20。
4. 记录官方 GUI 的 6 槽位限制（设备不限，我们已用到 img18）。

验证：`ruler800.png` 用新管线编码后与官方 `official_ruler.pak` 的帧构图一致
（内容区 0..799 / 5..220，右侧 223px、底部 19px 黑边）。

## 2026-11-06 — 设备设置 / 独立监控 / 逐项停留 / 上传预估

**新增「设备设置」标签页**
* 读取设备信息：`E01F` → 固件 5.13 · 亮度 · ID · 开机动画（实测通过）
* 亮度调节：`E11E`（设备不回应答，写入后回读确认；实测 10→7→10 生效）
* 开机图：`E916`（设备不回显，按已下发处理）
* 开机动画：`EB14` 切换、`E21D` 播放（Vulcan 生效；Kudan 本机不接受，界面如实提示）

**硬件监控改为独立本地采集**
* 不依赖 iGame Center：GPU 走 NVML、CPU/内存走 psutil
* 新增显存、风扇、CPU 型号、内存占用；刷新间隔可选 0.5–5 秒，可暂停
* 仍然只显示、不发送（监控上屏指令未验证）

**播放列表：每项独立停留时间**
* 改为表格（文件 / 停留秒数），双击单元格即可单独修改
* `carousel.build_entries` 改为接收 `[(路径, 秒数), …]`

**上传进度与剩余时间**
* 按已完成块数的平均耗时估算 ETA，状态栏显示
  「上传中 45/126 块（35%）· 剩余约 32 秒」

## 2026-11-06 — 移除「设备连接」面板，改为串口状态条

串口已能按 VID/PID 自动识别，手动连接面板不再需要：

* 删除 ui/panels/connection_panel.py（端口下拉、刷新、扫描、连接/断开、
  服务启停按钮全部移除）
* 新增 ui/port_status.py：单行状态「智屏串口：已连接 · COM5 /
  未连接（检测到 COMx）/ 未检测到设备」，每 2 秒自动刷新
* SerialLink.ensure_open()：标题投屏等发送动作改为**按需自动连接**
* 小节编号顺延：① 文字投屏、② 图像预览与上传

## 2026-11-06 — 播放列表轮播上线 + 三个关键修复

**轮播（新）**：`features/carousel.py` + 播放列表面板。
一次接管串口 → 逐个上传 → 校验清单 → 静置 2.5s → 按停留秒数循环发 `E51A`。
真机验证：两段 GIF 每 4 秒切换，连续 7 次无异常。

**修复一：槽位必须连续**（根因级）
设备只接受 `max(编号)+1`，跳号写入会被静默丢弃（公告和数据块都回 01，
但清单里没有）。此前所有"上传成功但看不到"都是这个原因。

**修复二：公告应答校验**
发公告后未读应答，会被当成第 0 块 ACK；现已显式校验 `status == 01`。

**修复三：zh_HK 区域导致数字显示异常**
Qt 对 `zh_HK` 使用杭州数字（`120 → 〡〢〇`），QSpinBox 显示成 `〩〩`
且无法输入两位以上数字。启动时固定 locale 为 en_US 解决。

编码：改用单次 ffmpeg 直转（官方做法），270 帧 0.26 秒。

## 2026-11-06 — 「画面旋转 180°」与预览修正

**新功能**：界面新增「画面旋转」下拉（不旋转 / 旋转 180°），把上传的动画内容
整体翻转，而屏幕安装方向补偿保持不变。实现上：设备补偿固定 180°，
用户选 180° 时打包改传 0°，两者相消 → 内容倒置。

**预览修正**：此前预览如实画出打包帧（内容在左 + 右侧黑边 + 倒置存储），
与屏幕实际效果完全不符，造成上传坏了的误判。实测设备会翻转 180°、
裁掉黑边并铺满面板（官方帧同样带黑边，屏幕上却看不到），
故预览改为直接显示设备的最终观感。

**验证**：两种旋转设置生成的帧哈希不同；真机确认选 180° 后内容确实倒置。

## 2026-11-06 — 找到"画面偏移"的根因：官方不缩放

**根因**：官方把源素材**按原始像素**贴到 1024×240 黑色画布左上角（右侧留黑），
从不缩放。我们一直用 fill/stretch 把 800×216 放大到 1024，导致画面放大、位置偏移。

**证据**：解剖官方 pak（`deliverable/samples/img2.pak`）的帧：
列 1..799 是内容、列 800..1023 全黑、最左一列是画布边界黑线。

**修复**：新增 `fit_mode="native"` 并设为默认；GUI 默认选中「原始尺寸（官方效果）」。
真机验证：改为 native 后显示与官方一致。

## 2026-11-05 — 清理设备无效缓存（e718）

**背景**：本工具上传的文件官方软件不认，会在设备里堆积成"无效缓存"，
越积越多会拖慢写入（实测从 0.5 秒/块退化到 120 秒/块），画面也会渲染异常。

**抓到的协议**（清理时官方逐条发送）::

    5A 9F A9 00 0E | E7 18 | 00 | "img3.pak" 00 | 05 89

**实现**：
- `gif_upload.build_delete_frame()` / `delete_file()`
- `upload_ledger.UploadLedger`：记录本工具上传过的文件名（JSON 台账）
- `cache_clean.clear_uploaded_files()`：只删台账里的文件
- GUI 新增「清理设备缓存」按钮（后台线程）；CLI `--clear-cache`

**真机验证**：上传 img3 → 清理 → 设备清单只剩 img1；写入速度恢复正常（1.7 秒/块）。
测试：407 项通过。

## 2026-11-05 — GUI 全流程验收通过

- 用 `初音未来.gif`（3.37 MB）在 GUI 里完成 选择 → 上传 → 播放，自动识别到 COM5
- 设备掉线真因确认：**主板 USB 针脚接触不良**，换针脚后恢复
- 至此：编码、打包、传输、显示、恢复五段链路全部真机验证通过

## 2026-11-05 — 设备掉线根因（USB 针脚）+ 串口自动识别

- 反复出现的「描述符请求失败 / 写入 100 秒每块」**真因是主板 USB 针脚接触不良**；
  换针脚后设备恢复，端口由 COM4 变 COM5。
- 3.37 MB / 270 帧上传成功：216 块、145 秒、0 重试。
- 新增 `port_scanner.find_lcd_port()`：按 USB VID:PID 匹配串口，
  会话层、GUI、CLI 均已接入；`auto_port_scan` 置 verified。
- 审查（千问）提出的 6 项已修复；测试 400 项通过；新增 `--gap-ms` 分块间隔参数。

## 2026-11-04 — 最终验收（GUI 全流程）

- 画面裁切/偏移：**已修复**（JPEG 改为单量化表 + 无 APP0），真机确认四角齐全、红框贴边
- 播放速度：30fps 重采样后时长与官方一致（17.8s 素材实测一致）
- 剧情完整性：取消自动抽帧后 214 帧素材完整播放
- 上传速度：GUI 实测 2.5 MB / ≤1 分钟（命令行偶发 100 秒/块属设备降级，断电可恢复）
- 测试：396 项通过

## 2026-11-04 — 修正"画面被裁切/偏移"（JPEG 段结构）

**现象**：上传后屏幕只显示画面左侧一部分，右边缘内容缺失（标尺图缺 TR/BR）。

**根因**：设备解码器无法正确处理 **APP0(JFIF) + 双量化表** 的 JPEG，会算错宏块。
官方 pak 用的是 **单张量化表 + 无 APP0**（另有 COM 段）。

**修复**：`encode_jpeg_official()` 按官方结构编码（单表、去 APP0），
`encode_jpeg_limited` 默认使用它。真机验证：同一张标尺图四角齐全、红框贴边。

## 2026-11-04 — 播放节奏定案（30 fps）与"抽帧 bug"修复

**最关键的发现**：早期为压体积加的"自动抽帧"，把 214 帧砍成 54 帧、130 帧砍成 65 帧，
用户看到的"只播了一部分剧情"正是它造成的，与设备无关。

**播放规律（实测）**：
- 设备固定 **30 fps** 播放，`interval` 字段被忽略（120ms / 300ms 速度一致）；
- 动画时长 = 帧数 ÷ 30，所以编码必须重采样到 30fps；
- 单包 8.5 MB 仍可正常播放，因此上限设为 10 MB，体积超限时**优先降质、绝不丢帧**。

**参数**：`target_fps=30`、`max_frame_bytes=32000`、`max_pak_bytes=10MB`、`allow_decimation=False`。

## 2026-11-04 — GUI 上传可用（两个 GUI bug 修复）

**现象**：点「上传到屏幕」毫无反应，屏幕也不会有上传动画。

1. **`AttributeError` 被 Qt 吞掉**：注入的"上传前释放串口"用了 `self._link`，
   而主窗口属性叫 `self.link`。槽函数抛异常后线程根本没启动，界面上完全无提示。
2. **端口被自己占用**：程序自身的连接面板开着 COM4 时，上传线程再开同一端口
   会 `PermissionError(13, 拒绝访问)`。现在点上传会自动断开连接面板的占用。

**验证**：红绿蓝 3 帧测试 GIF 上传后屏幕正常循环变色，点停止恢复官方素材。

**同时修复**：
- 自适应 JPEG 编码（每帧 ≤16 KB，质量阶梯 85→30），解决"只循环播放几帧"
- `build.ps1` 末尾补 `exit 0`

## 2026-11-04 — 自适应 JPEG 编码

官方 1024×240 帧约 8.7–16 KB。早期固定 q85 会产出 34 KB/帧、pak 4.2 MB，
设备解码缓冲装不下，表现为"只循环播放几帧"。现按帧独立降质到 16 KB 以内，
11.8 MB 的 GIF 编码后约 2.0 MB（平均质量 49），可完整播放。

## 2026-11-04 — GIF 上传真机打通（gif_upload → verified）

**结果**：自建 1 帧 pak 上传后，屏幕正常显示自建测试图（蓝底 `VULCAN`）。

**三个关键 bug / 误判**：

1. **数据块长度字段**：第 3–4 字节是 `uint16 BE = 总长 − 5`，不是常量 `0x4006`。
   满块恰好相等所以长期没被发现；尾块写错会导致"设备回 ACK 但不登记文件"。
2. **`e51a` 方向搞反**：它是主机 → 设备的「显示该文件」指令（每秒一次），
   不是设备心跳。不发它，屏幕永远停在默认动画。
3. **`e619` 是查询**：9 字节空帧请求 → 设备回清单。用它做只读验证，
   才定位到"文件根本没写进去"。

**顺带修好的**：
- 写超时 1s → 5s，16 KB 块改 1 KB 分片 + 3 ms 间隔（避免设备 RX 缓冲溢出卡死）
- COM4 写超时会把设备卡到 `VID_0000`（描述符请求失败），只能冷断电恢复；
  已避免用 `Disable-PnpDevice` 复位

**新增**：
- `media/pak.py`：pak 构造/解析，可与官方产物**逐字节一致**
- `features/gif_upload.py`：握手 → 公告 → 分块 → ACK → 收尾握手 → 显示指令
- `tools/query_files.py`：只读查询设备文件清单
- `tools/scan_frames.py`：扫描每个 USB 传输内部的所有帧
- `scripts/capture_ready.ps1`：按回车才开始抓包 + 自动探测接口
- 测试：381 项通过

# Changelog

本项目所有值得记录的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

功能状态变更（`verified` / `experimental` / `disabled` / `removed`）必须在此登记，
并与 `feature_registry.json` 保持一致。

## [Unreleased]

### 2026-11-04 · 抓包工具链（为补齐 GIF 协议准备）

- 新增 `docs/CAPTURE_GUIDE.md`：USBPcap + Wireshark 抓包步骤（COM4 被服务独占，
  只能在 USB 层观察）
- 新增 `tools/decode_capture.py`：把抓包十六进制切成协议帧，并做三件判断
  - 帧头 + 长度字段双重校验切帧（避免 payload 里偶然出现的 `5A 9F A9` 造成错位）
  - **同时用大端与小端验算校验和**，直接回答"图片帧是否沿用大端"
  - 按固定 ID 分组统计，标出未知 ID（很可能就是图像通道）
- 新增 `tests/test_decode_capture.py`（15 个用例）；测试 328 → 343

### 2026-11-04 · 双视图预览（横屏 + 立装竖屏）

- 预览面板改为双视图：左侧 **800×216 横屏**（实际发送内容），右侧 **216×800 竖屏**
  （模拟显卡立装后的观感）
- 竖装方向可切换：顺时针 90° / 逆时针 90° / 关闭竖屏预览
- `media/preprocess.rotate_image()` 用 `Image.transpose`（无损），不用 `rotate`（会插值发虚）
- **上传内容不受影响**：旋转只发生在本机预览，`gif_upload` 的参数与发送链路完全没变
- 测试 323 → 328（新增 5 个旋转用例，含角落像素级断言）

### 2026-11-04 · 模块 9b：打包与产物验证

- 新增 `main.spec`（onedir，`VULCAN_CONSOLE=1` 出控制台版）：
  `pathex` 含 `src`；`hiddenimports` 含 `serial` / `serial.tools.list_ports` /
  `PySide6.Qt*` / `pynvml` / `psutil`；排除 numpy/pandas/matplotlib/WebEngine
- 新增 `scripts/build.ps1`：断言虚拟环境 → 清理 → 打包 → 产物 `--check` 自检 → 体积报告
- `app.py` 新增冻结环境路径解析：`resource_root()`（`_MEIPASS`）与 `writable_root()`（exe 同级），
  解决"打包后找不到配置/注册表、日志写不进去"的典型问题
- `main.py` 新增 `--check`（装配自检，结果落 `logs/startup_check.txt`）
  与 `--smoke[=ms]`（起窗后自动退出，供无人值守验证）
- `pyinstaller_packaging` 状态置 **verified**

**实测**：产物 103.5 MB / 173 文件；`--check` 退出码 0；`--smoke=2500` 日志完整
（`context_ready → app_start → window_closed → app_exit(0)`）；窗口版与控制台版均通过。

**踩坑记录**：从脚本里 `Start-Process -Wait` 启动 GUI 产物会让父命令永远等不到结束——
子进程继承了父进程的管道句柄，`-Wait` 又阻塞在退出上。自动化验证必须改成
`cmd /c start` 分离启动，或直接用 `--smoke` + 轮询日志文件。

### 2026-11-04 · 服务接管（system/service_control.py + recovery.py）

- `ServiceController`：查询 / 停止 / 启动 / 接管 / 恢复，用 `sc.exe`，无额外依赖
- `RestoreGuard`：`atexit` + `sys.excepthook` 双钩子恢复服务；强调"强杀进程/断电无法恢复"
- UI：连接面板新增服务状态与「停止/启动服务」按钮，连接前自动停、断开后自动恢复；
  服务操作放工作线程，避免 `sc stop` 的 2–10 秒把界面冻住
- `service_control` 状态置 **verified**

**实机验证**：takeover 2.0s（COM4 从 `PORT_BUSY` → 可独占），release 10.8s（恢复 RUNNING）。

**实机踩出的三个坑（均已加处理与回归测试）：**

1. `sc query` 状态行用 `isalpha()` 过滤会把 `START_PENDING` 判为非字母，
   退化成返回 `"STATE"`，导致启动等待永远超时；
2. 在 `START_PENDING` / `STOP_PENDING` 期间发 stop/start，Windows 会**忽略**请求，
   必须先 settle 再操作；
3. 服务异常时返回 **1061**（cannot accept control messages），此时重试无效，
   需重启 iGame Center 或结束服务进程。本次实测中该状态由前两个坑的连续重试诱发，
   通过结束 `iGameCenter.Service` 进程让 SCM 自动重启恢复。

### 2026-11-04 · 模块 9a：GUI 主窗与接线

- 新增 `main.py`：参数解析 → 装配上下文 → 权限询问（非管理员时弹窗询问是否提权，
  不静默提权/降级）→ 起窗口
- 新增 `app.py`：`build_context()` 装配配置 + 注册表 + 闸门 + 日志；**不导入 Qt**，
  因此可被纯 pytest 覆盖
- 新增 `ui/link.py`：`SerialLink` 是 UI 与硬件之间的**唯一**通道，
  所有"能不能发"的判断集中在此
- 新增面板：连接（枚举/扫描/连接）、文字投屏（已验功能）、图像预览（后台线程解码）、
  播放列表（受闸门禁用）、硬件监控（只读 + 黄色警告）、调试（功能表/日志过滤/导出报告/人工发送）
- 新增 `tests/test_app.py`；测试 273 → 284
- 冒烟验证：offscreen 与原生 `windows` 平台均可构造并正常退出，
  窗口 1180×760，状态栏显示 `调试 · 管理员 · venv · 可写功能 3/13`

**闸门在 UI 上的实际表现**（无头冒烟断言）：`title_display` 可点、
`gif_upload` 与 `playlist_rotation` 置灰并带 tooltip 说明原因、人工发送仅在 `--debug` 可用。

### 2026-11-04 · 模块 8：结构化日志 + 调试会话 + 调试报告

- 新增 `diagnostics/logging_setup.py`：JSONL 日志，字段固定为
  `timestamp / level / module / feature_id / action / result / error_code /
  duration_ms / tx_hex / rx_hex`，按天写 `logs/debug_YYYYMMDD.log`
  - `tx`/`rx` **强制截断**（默认 64B，超出标 `(+N B)`）；生产模式直接不记录
  - `timed()` 上下文自动记录耗时，异常路径也写一条 `result=fail`
  - `read_events()` 支持按 `feature_id` / `level` / 条数过滤，单行损坏只跳过该行
- 新增 `diagnostics/debug_session.py`：`--debug` / `--dry-run` / `--feature=` 收敛为不可变对象
- 新增 `diagnostics/report.py`：`debug_report.md` + `debug_report.json`
  - 六节结构：环境 / 设备服务 / 注册表快照 / 未就绪功能（含复现步骤与最近日志）/
    待验证协议项 / **给 Harness 的修改指令模板**（每个失败功能一段，可直接复制）
- 新增 `system/privileges.py`：`is_admin()`（只检测不提权，便于测试）
- 新增 `tools/export_report.py`：无需 GUI 即可导出报告
- 测试 237 → 273

**实测产物**：`debug_report.md` 列出了 10 个关注项、7 条未验证闸门；
日志 `logs/debug_20261104.log` 两行 JSONL，字段齐全。

### 2026-11-04 · 模块 4：图像预处理 + 像素格式接口

- 新增 `media/preprocess.py`：
  - 输出**严格 800×216 RGB**，cover 策略（等比铺满 + 居中裁剪），不做拉伸、不留黑边
  - 固定 LANCZOS 重采样
  - **EXIF 方向校正**（手机竖拍不再躺倒）
  - 透明通道合成到底色（默认黑，可配置），不让 alpha 漏到下游
  - 按 stride 抽帧，并把被抽掉帧的**时长累加到保留帧**（总时长不变，动画不会变快）
  - 流式生成器（不把整段 GIF 解成几十张位图常驻内存）+ `max_frames` 硬上限 + 进度回调
- 新增 `media/pixel_format.py`：RGB565 / RGB888 转换，通道顺序（RGB/BGR）与字节序（LE/BE）
  都是**显式参数**——真实排列未验证，默认值只是占位，由 `media.pixel_format_verified` 闸门拦住发送
- 新增测试 `test_preprocess.py` / `test_pixel_format.py`；测试总数 187 → 237

**修复的两处自身错误：** 灰色 `128,128,128` 的 RGB565 期望值算错（漏算绿色分量的 `0x0400`，
正确是 `0x8410`）；静态图误套"帧延时缺失 → 100ms"兜底（该兜底只对多帧动画成立）。

### 2026-11-04 · 人工原始发送通道（受控例外）

按需求 §9.2「手动发送原始十六进制必须二次确认，且默认禁用」落地：

- `FeatureGate.require_manual_raw(confirmed, config)`：必须 `debug_mode` + 二次确认
  （`debug.require_confirm_for_manual_hex=true`），否则抛 `FeatureBlockedError`
- 该通道**不进入** `feature_registry.json`——它不是功能，是逃生舱
- 不改变功能闸门：`experimental` 仍然是 `READ_ONLY`，人工通道不会顺带解锁任何功能
- 日志固定使用 `feature_id=manual_raw_hex`、`action=manual_send`

### 2026-11-04 · 模块 6：功能注册表 + 生产闸门

- 新增 `feature_registry.json`：13 个 feature（需求要求的 12 个 + `title_display`），
  每个含 `status` / `protocol_verified` / `last_test_at` / `last_result` /
  `error_summary` / `suggested_action` / `depends_on` / `test_env`
- 新增 `features/registry.py`：四态状态机、载入期校验（非法状态/重复 id/缺失依赖/环）、
  **原子写入**（临时文件 + `os.replace`）、`snapshot()` 供调试报告使用
- 新增 `features/gate.py`：
  - `Permission`（write / read_only / blocked），**fail closed**：未知 id 一律拦截
  - `experimental` 即使 `debug_mode=True` 也只读——调试模式不放宽写权限
  - 依赖链：依赖被禁用或成环 → 父功能 `BLOCKED`（不允许"半个功能"跑起来）
  - `audit()`：检测"注册表说已验证、配置却说未验证"这类自相矛盾
- **消除重复策略**：配置闸门表从 `scripts/verify_env.py` 迁到 `features/gate.py`，
  自检脚本改为导入同一份规则，避免两处规则漂移
- 测试 143 → 187

**状态**：`verified` = checksum_16le / venv_bootstrap / title_display；
`experimental` = 其余 10 个（上传、监控、双屏、ACK、打包等，均因协议未验证）。

### 2026-11-04 · 模块 2R：协议层按实机事实重写

旧实现基于"固定 36 字节 + 小端校验"的错误前提，全部推翻重写：

- `constants.py`：帧改为变长；`SEQ1_OFFSET=3`、`LENGTH_OFFSET=4`、`LENGTH_BIAS=5`；
  校验改 `SUM16_BE`；新增 body 内部偏移常量与 `FIXED_ID_TIME` / `FIXED_ID_HANDSHAKE`
- `core/protocol.py`：
  - `build_frame` / `parse_frame`：变长帧、长度自洽校验
  - `accumulate16` 与 `compute_checksum` 分离（见下方缺陷记录）
  - `encode_title` 返回 `TitleEncoding`，**带回被丢弃的字符**（实机证明设备会静默丢弃，
    本地若也静默，用户会以为程序坏了）
  - `build_time_frame` 对文档 step7 / step8 实现**逐字节复现**
- `core/handshake.py`：**结构匹配**（帧头 + 长度 + 校验 + 固定 ID），不做整包等值比较；
  `perform_handshake` / `send_init_sequence`
- 测试从 123 增至 143，基准向量全部换成实机/文档真实字节

**修复的缺陷：** `build_frame` 曾把"不含校验位的帧头"传给 `compute_checksum`，
而后者内部又会砍掉末 2 字节，导致漏算 `title\0` 与版本字节（差恰好为 2）。
现拆为 `accumulate16`（全量求和）与 `compute_checksum`（排除末 2 字节），
并在两处注释中写明分工，防止复发。

**实机复验（新协议层）：** 握手 `成功`，`VULCAN 5070 OK` 标题帧 34 字节发送成功，
`length=0x1D=29` 自洽。`handshake_verified` 置 `true`。

### 2026-11-04 · 实机验证里程碑：文字投屏成功

在 RTX 5070 + iGameCenter 2.0.0.82 上完成首次端到端控制：

- 握手 `5A9FA90004E01F02A5` → 设备应答 `5A9FA9000CE01F0A…02C9`（17 字节）
- 发送初始化序列 step3–6 后，自定义 title 帧成功渲染到屏幕（实测显示 `I LOVE YOU`）
- 组帧器对文档 step7 / step8 样本实现**逐字节复现**（含校验和）

**由此更正两条此前的错误认知：**

1. **校验和是大端（MSB 在前），不是小端。** 证据：step1 累加 677=`0x02A5` 写作 `02 A5`；
   设备应答累加 714=`0x02CA` 写作 `02 CA`；文档 step8 累加 2109=`0x083D` 写作 `08 3D`。
   原文与项目需求中的"Little-Endian"说法均被实机证伪。
2. **帧是变长的，不是固定 36 字节。** 真实结构为
   `header(3) + seq1(1) + length(1) + body + checksum(2)`，`length = 总长 − 5`；
   36 字节只是"title 恰好 17 字节"时的特例。

**由此确认的事实：**

- 智屏串口 = `COM4`（USB `VID:PID=1B3F:0123`），COM1 为主板 16550 端口，与显卡无关
- 官方服务名 = **`iGameCenterService`**（此前猜测的 `iGameCenter.Service` 是错的）
- 停止该服务后可独占 COM4；服务运行时会 `PermissionError 13`
- 设备为"主机先开口"型：不发握手则永不应答（被动监听 2.5s 零数据）
- 5070 与 5080 协议一致，仅应答包偏移 13 状态位不同（`00` vs `01`）

**仍未知（阻塞 GIF 上传）：** GIF 分包结构、分包大小、图片帧校验范围、是否存在逐包 ACK、
监控数据帧格式、分区/局部刷新指令。

### 2026-11-04 · 项目脚手架

- 建立项目虚拟环境 `.venv_local\python`（Python 3.11.9），锁定依赖范围
- 环境自检 `scripts/verify_env.py`：解释器归属、venv 隔离、依赖版本、NVML 实读、
  配置合法性、**协议就绪度表**（按 `*_verified` 标记推导哪些 feature 被阻挡）
- 协议常量与帧构造 `core/protocol.py`（**注意：此版本基于"固定 36 字节 / 小端"的错误前提，
  待按实机结果重写**）
- 串口传输层 `core/transport.py`：全项目唯一允许触碰 `serial.Serial` 的入口，dry-run 不碰硬件
- 端口嗅探 `core/port_scanner.py` + `tools/sniff_serial.py`：只读监听，发送需双开关
- 文件校验 `media/probe.py`：40MB 上限、魔数识别（不看扩展名）、APNG 显式拒绝、
  GIF 帧延时 10ms 量化处理、零延时按 100ms/帧估算并标记
- 测试 123 项（`pytest`），其中协议层部分需随重写更新

### 已知问题

- `core/protocol.py` 的帧模型与校验字节序**与实机不符**，必须重写后才能用于任何真实发送
- `tools/handshake_test.py`、`tools/title_demo.py` 是验证用临时脚本，正式协议层落地后应移除或改造

## 2026-11-04 — 上传功能接入 GUI（模块 A）

- 预览面板新增「上传到屏幕」：编码 → 接管服务 → 上传 → 每秒发显示指令 → 停止时恢复
- 新增 `media/encode.py`（GIF/图片 → JPEG → pak）与 `features/screen_session.py`（完整会话）
- 分辨率常量改为实测 **1024×240**（原 800×216 废弃），相关测试同步更新
- 上传线程化，UI 不卡；进度条分编码/上传两阶段
- 测试 393 项通过；exe 重新打包（`--check` 退出码 0）
