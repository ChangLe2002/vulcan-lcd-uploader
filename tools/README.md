# 辅助脚本

这些是开发与排查用的一次性脚本，不属于程序运行路径。

| 脚本 | 用途 |
| --- | --- |
| `upload_pak.py` | 直接上传一个 `.pak` 到设备（支持 `--clear-cache`） |
| `query_files.py` | 查询设备文件清单与可用空间 |
| `sniff_serial.py` | 抓取串口原始收发，输出十六进制 |
| `decode_capture.py` | 解析 USBPcap 抓包，提取协议帧 |
| `analyze_transfer.py` | 分析一次上传的分包时序 |
| `analyze_clean_capture.py` | 分析官方"清理缓存"抓包，定位指令 |
| `compare_captures.py` | 对比两次抓包差异 |
| `handshake_test.py` | 单独验证握手帧 |
| `monitor_test.py` | 单独验证监控上屏帧 |
| `cycle_test.py` | 循环切换设备上已有文件 |
| `repro_upload.py` | 无界面复现一次完整上传 |
| `test_carousel_live.py` | 真机跑一轮轮播 |
| `title_demo.py` | 发送一条文字投屏 |
| `extract_pak.py` | 拆开 `.pak`，导出其中的 JPEG 帧 |
| `scan_frames.py` | 扫描素材帧数与时长 |
| `inventory.py` | 汇总目录内素材信息 |
| `export_report.py` | 生成调试报告 |
| `decompile_all.py` | 用 ILSpyCmd 批量反编译官方程序集（需自行准备工具） |
| `shot_main.py` / `shot_new_ui.py` / `shot_playlist.py` / `shot_spin_compare.py` | 离屏渲染界面截图 |
| `md_to_text.py` | 把 Markdown 文档转成纯文本（发版附件用） |

运行前请确保已安装依赖，并且**没有其他程序占用串口**。
