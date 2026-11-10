# 作者与致谢

## 项目作者

**常乐（Changle）** —— 设计、实现、逆向分析与文档

* 项目：火神智屏图传工具（Vulcan LCD Uploader）
* 许可：MIT（见 [LICENSE](LICENSE)）

## 协议事实来源

本项目的**事实性参数**（串口参数、帧结构、校验规则、分辨率等）来自公开资料，
在此致谢：

* **whgjjim** —— 公开的逆向分析文章《iGame七彩虹Vulcan火神小屏幕通信协议》
  （CSDN，2025-06，CC BY-SA 4.0）。本项目仅引用其中的事实性参数，未转载其原文表述。
* **[wiselike/LCD](https://github.com/wiselike/LCD)**（MIT）—— 协议事实与收发流程的
  交叉参考。本项目为独立的 Python 实现，未复制其源码。

## 第三方组件

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| PySide6 (Qt 6) | 图形界面 | LGPLv3 / 商业双许可 |
| pyserial | 串口通信 | BSD-3-Clause |
| Pillow | 图像解码 | HPND |
| nvidia-ml-py | NVML 显卡传感器 | BSD-3-Clause |
| psutil | CPU/内存传感器 | BSD-3-Clause |
| FFmpeg | JPEG 编码（运行时外部调用） | LGPL / GPL（视构建而定） |
| PyInstaller | 打包 | GPLv2 + 例外条款 |

详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 说明

本项目与七彩虹（Colorful）/ iGame 无任何隶属或授权关系，是个人学习与自用项目。
