# 第三方组件与出处声明（Third-Party Notices）

本项目以 **MIT License** 发布（见 [LICENSE](LICENSE)）。下列第三方组件由各自的许可证授权，
本项目仅以依赖形式使用，未修改其源码。分发打包产物时必须随附本文件。

---

## 1. 运行期依赖

| 组件 | 版本范围 | 许可证 | 项目地址 |
| --- | --- | --- | --- |
| pyserial | >=3.5,<4.0 | BSD-3-Clause | https://github.com/pyserial/pyserial |
| Pillow | >=10.4,<12.0 | HPND（Historical Permission Notice and Disclaimer，MIT-CMU 系） | https://python-pillow.org |
| PySide6 (Qt for Python) | >=6.7,<7.0 | LGPLv3（Qt 本体为 LGPLv3 / 商业双授权） | https://doc.qt.io/qtforpython-6/ |
| nvidia-ml-py | >=12.550 | BSD-3-Clause | https://pypi.org/project/nvidia-ml-py/ |
| psutil | >=5.9,<8.0 | BSD-3-Clause | https://github.com/giampaolo/psutil |

### 1.1 pyserial（BSD-3-Clause）

> Copyright (c) 2001-2020 Chris Liechti <cliechti@gmx.net>
> All rights reserved.
>
> Redistribution and use in source and binary forms, with or without modification,
> are permitted provided that the following conditions are met:
> 1. Redistributions of source code must retain the above copyright notice, this
>    list of conditions and the following disclaimer.
> 2. Redistributions in binary form must reproduce the above copyright notice,
>    this list of conditions and the following disclaimer in the documentation
>    and/or other materials provided with the distribution.
> 3. Neither the name of the copyright holder nor the names of its contributors
>    may be used to endorse or promote products derived from this software without
>    specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
> ANY EXPRESS OR IMPLIED WARRANTIES ... ARE DISCLAIMED.
>
> 完整条文见 https://github.com/pyserial/pyserial/blob/master/LICENSE.txt

### 1.2 PySide6 / Qt（LGPLv3）

本项目通过 **动态链接** 方式使用 PySide6 与 Qt 库，未对其做任何修改，因此符合 LGPLv3 的合规要求。
打包产物中如包含 Qt 动态库（`Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll` 等），使用者有权将其替换为
自行编译的同版本库。Qt 源码可从 https://download.qt.io/official_releases/QtForPython/ 与 https://code.qt.io/ 获取。

> 说明：本项目早期评估过 PyQt5，因其为 **GPLv3**（或商业授权），与"以 MIT 发布并分发二进制产物"存在
> 许可证冲突，故最终选用 PySide6（LGPLv3）。

### 1.3 NVIDIA Management Library 绑定

`nvidia-ml-py` 是 NVIDIA 官方维护的 NVML Python 绑定（BSD-3-Clause），运行时动态加载系统内的
`nvml.dll`。本项目不附带、不分发任何 NVIDIA 驱动或 DLL。

---

## 2. 开发期依赖（不进入运行时产物）

| 组件 | 许可证 | 说明 |
| --- | --- | --- |
| PyInstaller | GPLv2 + Bootloader Exception | 其 Bootloader 例外明确允许打包**专有/其他许可证**应用 |
| pytest | MIT | 仅测试 |

---

## 3. 协议来源与"无专有代码"声明

### 3.1 不包含 iGame Center 的代码或衍生物

本项目**不包含** iGame Center（七彩虹 / Colorful）的任何源代码、二进制、资源文件、配置文件，
也**不包含**对其程序进行反编译、反汇编、内存转储所得的衍生物。

本项目仅依据**公开可查的、由第三方独立发表的协议分析资料**，重新实现了一套串口帧构造逻辑。
协议参数（波特率、帧头字节、校验规则）属于功能性事实，不构成受版权保护的表达。

### 3.2 对 wiselike/LCD 的引用边界

[wiselike/LCD](https://github.com/wiselike/LCD)（MIT）为本项目提供了**协议事实与实现思路**的交叉验证参考，
例如"帧头 + 长度字节 + 数据区 + 16 位小端累加校验"的帧结构，以及"打开串口 → 组包 → 发送 → 关闭串口"的流程顺序。

- 该项目为 C++ 实现，本项目为**独立的 Python 实现**，**未复制、未逐行翻译**其源码。
- 该项目覆盖的是文字/数据帧（最多 25 字符的 title 区），**不覆盖 GIF / 图片上传**。
- 因其为 MIT 许可，即便发生代码复用也不构成许可证冲突；但本项目仍保持独立实现以确保代码质量与可维护性。

### 3.3 对 CC BY-SA 4.0 分析文章的处理

对基于 RTX 5080 抓包的公开协议分析文章（CC BY-SA 4.0）：

- 本项目**只提取事实性参数**（波特率、十六进制序列、校验和计算规则、屏幕分辨率）；
- **不转载、不改写、不翻译、不摘抄**原文的表述性文字；
- 出处已在 [README.md](README.md) 第 2 节显著标注。

依 CC BY-SA 4.0 第 2(a)(1) 条，单纯的事实性数据不受版权保护；因此上述引用不会导致本项目 MIT 代码
被 CC BY-SA 传染。若未来需要复制原文段落或图表，则必须将该部分单独标注为 CC BY-SA 4.0，
并保持署名 + 相同方式共享。

---

## 4. 商标声明

"iGame"、"Colorful"、"七彩虹"、"NVIDIA"、"GeForce"、"RTX" 等为其各自权利人的商标或注册商标。
本项目为**非官方、非商业**的爱好者工具，与上述公司无任何隶属、赞助或授权关系。
