# SPDX-License-Identifier: MIT
"""协议常量（唯一来源）。

标注规则 —— 每个常量都带可信度标签，禁止把 ``[E]`` 当事实使用：

``[V]`` verified
    已由实机收发验证（2026-11-04，RTX 5070 + iGameCenter 2.0.0.82），
    或由公开抓包与实机双向印证。代码可以直接依赖。
``[E]`` experimental
    未验证 / 仅有社区传闻。只能作为"可配置默认值"，必须允许调用方覆盖，
    且在 UI 与日志里标注为待验证。

变更须知：任何 ``[V]`` 常量的修改都必须同步 ``feature_registry.json``、
``CHANGELOG.md`` 与 README 的协议表。

历史教训（务必保留）
--------------------
本项目最初依据文档写成"固定 36 字节帧 + 小端校验"，**两处都错**。实机证明：

* 帧是**变长**的，``length`` 字段在偏移 **4**（偏移 3 是帧序号 #1）；
* 校验和是**大端**（MSB 在前）。``0x02A5`` 写作 ``02 A5``，不是 ``A5 02``。

36 字节只是"title 恰好 17 字节"时的特例，不是协议常量。
"""

from __future__ import annotations

from enum import Enum

# --------------------------------------------------------------------------- #
# 帧结构（变长，实机验证）
# --------------------------------------------------------------------------- #
# [V] 帧头三字节
HEADER: bytes = b"\x5a\x9f\xa9"
HEADER_SIZE: int = len(HEADER)

# [V] 偏移 3：帧序号 #1（不是长度字段！）
SEQ1_OFFSET: int = 3

# [V] 偏移 4：长度字段，值 == 总长 − 5
LENGTH_OFFSET: int = 4
LENGTH_BIAS: int = 5

# [V] 偏移 5 起是 body（数据区），body 末尾 2 字节之前含"显示版本"字节
BODY_OFFSET: int = 5

# [V] 校验和 2 字节，位于帧尾，**大端**
CHECKSUM_SIZE: int = 2

# [V] 单一帧的 length 字段只有 1 字节，故总长上限 5 + 255
MAX_FRAME_TOTAL: int = LENGTH_BIAS + 0xFF

# [V] 两个已知的 body 固定 ID
FIXED_ID_TIME: bytes = b"\xdd\x22"       # 时间/标题帧
FIXED_ID_HANDSHAKE: bytes = b"\xe0\x1f"  # 握手应答

# [V] 显示版本字节（body 最后一个字节）
VERSION_DEFAULT: int = 0x00
VERSION_KUDAN: int = 0x01
VERSION_VULCAN: int = 0x02

# [V] title 区最多 25 个字符，超长设备不显示；\0 结尾
MAX_TITLE_CHARS: int = 25

# [V] 设备实际渲染的字符集（实测：中文等字节被静默丢弃，不报错）
TITLE_ALLOWED_CHARS: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789. "

# [V] 时间/标题帧的 body 内部偏移（相对 body 起点，不是相对整帧）
BODY_FIXED_ID: int = 0      # 2 字节 DD 22
BODY_YEAR: int = 2          # 2 字节，大端，如 0x07E9 = 2025
BODY_MONTH: int = 4
BODY_DAY: int = 5
BODY_WEEKDAY: int = 6       # 0=周日 … 6=周六
BODY_HOUR: int = 7
BODY_MINUTE: int = 8
BODY_SECOND: int = 9
BODY_SEQ2: int = 10         # 帧序号 #2 = 序号#1 + 1
BODY_TITLE: int = 11        # title 起始，\0 结尾，后面紧跟版本字节

# --------------------------------------------------------------------------- #
# 硬件与串口参数
# --------------------------------------------------------------------------- #
# 物理分辨率。文档曾写 800×216，但抓包还原的官方 pak 中每帧 JPEG 实测为
# **1024×240**（270/270 帧一致），以实测为准。
SCREEN_WIDTH: int = 1024
SCREEN_HEIGHT: int = 240

# [V] 串口参数：115200 8N1，超时 50ms（文档 + 实机均一致）
SERIAL_BAUDRATE: int = 115200
SERIAL_BYTESIZE: int = 8
SERIAL_PARITY: str = "N"
SERIAL_STOPBITS: float = 1
SERIAL_TIMEOUT_MS: int = 50

# [V] 客户端侧硬性限制
MAX_UPLOAD_BYTES: int = 40 * 1024 * 1024  # 40 MB
MAX_FPS: float = 30.0

# --------------------------------------------------------------------------- #
# 未验证 / 待抓包确认的参数（仅作默认值，必须可配置）
# --------------------------------------------------------------------------- #
# [E] 分包大小：GIF 协议未知，暂定 4096
DEFAULT_CHUNK_SIZE: int = 4096

# [E] 帧间延时：10–20ms 区间内取中值
DEFAULT_INTER_PACKET_DELAY_MS: int = 15

# [E] 可选 ACK 等待（握手只有单次应答，不是逐包 ACK）
DEFAULT_ACK_TIMEOUT_MS: int = 500
DEFAULT_ACK_MAX_RETRIES: int = 3


class ChecksumAlgorithm(str, Enum):
    """校验算法标识。只允许 16 位累加 + **大端**，禁止 8 位累加。"""

    SUM16_BE = "sum16_be"

    def __str__(self) -> str:  # pragma: no cover - 仅用于日志可读性
        return self.value


__all__ = [
    "HEADER",
    "HEADER_SIZE",
    "SEQ1_OFFSET",
    "LENGTH_OFFSET",
    "LENGTH_BIAS",
    "BODY_OFFSET",
    "CHECKSUM_SIZE",
    "MAX_FRAME_TOTAL",
    "FIXED_ID_TIME",
    "FIXED_ID_HANDSHAKE",
    "VERSION_DEFAULT",
    "VERSION_KUDAN",
    "VERSION_VULCAN",
    "MAX_TITLE_CHARS",
    "TITLE_ALLOWED_CHARS",
    "BODY_FIXED_ID",
    "BODY_YEAR",
    "BODY_MONTH",
    "BODY_DAY",
    "BODY_WEEKDAY",
    "BODY_HOUR",
    "BODY_MINUTE",
    "BODY_SECOND",
    "BODY_SEQ2",
    "BODY_TITLE",
    "SCREEN_WIDTH",
    "SCREEN_HEIGHT",
    "SERIAL_BAUDRATE",
    "SERIAL_BYTESIZE",
    "SERIAL_PARITY",
    "SERIAL_STOPBITS",
    "SERIAL_TIMEOUT_MS",
    "MAX_UPLOAD_BYTES",
    "MAX_FPS",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_INTER_PACKET_DELAY_MS",
    "DEFAULT_ACK_TIMEOUT_MS",
    "DEFAULT_ACK_MAX_RETRIES",
    "ChecksumAlgorithm",
]
