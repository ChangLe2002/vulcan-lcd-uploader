# SPDX-License-Identifier: MIT
"""协议核心：帧构造、校验、传输与设备发现。

本包不依赖 GUI；导入时刻意不加载串口驱动，便于单元测试。
"""
