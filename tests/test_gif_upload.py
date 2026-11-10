# SPDX-License-Identifier: MIT
"""上传协议测试：组包与逐块 ACK 流程。

用假设备模拟屏幕：收到握手回 ea15 应答，收到数据块回 ``<块号> 01``。
这样可以在没有硬件的情况下验证：
* 公告帧 / 数据块与抓包字节完全一致；
* ACK 超时会重发，连续失败才报错；
* 进度回调按块推进。
"""

from __future__ import annotations

import pytest

from vulcan_lcd.constants import HEADER
from vulcan_lcd.core.transport import Transport
from vulcan_lcd.features.gif_upload import (
    ANNOUNCE_ID,
    CHUNK_SIZE,
    DATA_ID,
    DATA_SEQ1,
    UPLOAD_HANDSHAKE_TX,
    UploadError,
    build_announce_frame,
    build_data_block,
    build_file_list,
    FileEntry,
    upload_pak,
)
from vulcan_lcd.core.protocol import build_frame

# 抓包里真实出现的应答
HANDSHAKE_REPLY = bytes.fromhex("5A9FA9000CEA1503D9C0001E3DC0000564")

# 抓包里 img2.pak 的公告帧（size=2397564, sum=0x7F76）
CAPTURED_ANNOUNCE = bytes.fromhex(
    "5A9FA90015E31C000024957C7F7601696D67322E70616B0007BA"
)


class FakeDevice:
    """模拟设备侧应答。"""

    def __init__(self, *, ack: bool = True, fail_first: int = 0) -> None:
        self.written: list[bytes] = []
        self._rx = bytearray()
        self.ack = ack
        self.fail_first = fail_first
        self.data_blocks = 0

    # Transport 用到的接口
    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        if data[:3] != HEADER:
            return len(data)

        if data[5:7] == bytes.fromhex("ea15"):
            self._rx += HANDSHAKE_REPLY
        elif data[5:7] == ANNOUNCE_ID:
            # 公告应答：index=0000, status=01
            self._rx += build_frame(ANNOUNCE_ID + b"\x00\x00\x01")
        elif data[5:7] == DATA_ID:
            self.data_blocks += 1
            index = int.from_bytes(data[7:9], "big")
            if self.ack and self.data_blocks > self.fail_first:
                self._rx += build_frame(ANNOUNCE_ID + index.to_bytes(2, "big") + b"\x01")
        return len(data)

    def read(self, n: int) -> bytes:
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def close(self) -> None: ...

    def flush(self) -> None: ...


def make_transport(device: FakeDevice) -> Transport:
    return Transport("COM_TEST", serial_factory=lambda p, k: device)


# --------------------------------------------------------------------------- #
# 组包：与抓包逐字节比对
# --------------------------------------------------------------------------- #
def test_announce_matches_captured_bytes() -> None:
    frame = build_announce_frame("img2.pak", 2_397_564, 0x7F76)
    assert frame == CAPTURED_ANNOUNCE


def test_announce_length_field() -> None:
    frame = build_announce_frame("img2.pak", 100, 0x1234)
    assert frame[4] == len(frame) - 5


def test_data_block_layout() -> None:
    payload = bytes(range(32))
    block = build_data_block(0, payload)
    assert block[:3] == HEADER
    # 第 3-4 字节是 16 位大端长度 = 整块长度 − 5
    assert int.from_bytes(block[3:5], "big") == len(block) - 5 == len(payload) + 6
    assert block[5:7] == DATA_ID
    assert block[7:9] == b"\x00\x00"
    assert block[9 : 9 + len(payload)] == payload
    assert int.from_bytes(block[-2:], "big") == (sum(block[:-2]) & 0xFFFF)


def test_data_block_index_is_big_endian() -> None:
    block = build_data_block(0x0102, b"x")
    assert block[7:9] == b"\x01\x02"


def test_data_block_rejects_oversize_payload() -> None:
    with pytest.raises(ValueError, match="最多"):
        build_data_block(0, bytes(CHUNK_SIZE + 1))


def test_data_block_rejects_bad_index() -> None:
    with pytest.raises(ValueError, match="16 位"):
        build_data_block(70000, b"x")



def test_full_block_header_matches_capture() -> None:
    """满块（净荷 16384）的头部应与官方一致：5A9FA9 4006 E41B <idx>。"""
    block = build_data_block(0, bytes(16384))
    assert block[:9].hex(" ") == "5a 9f a9 40 06 e4 1b 00 00"


def test_tail_block_header_matches_capture() -> None:
    """尾块（净荷 1268）的头部应与官方一致：5A9FA9 04FA E41B 0015。

    这正是早期误判的根源：满块看起来像"常量 0x4006"，尾块才暴露它是长度。
    """
    block = build_data_block(21, bytes(1268))
    assert block[:9].hex(" ") == "5a 9f a9 04 fa e4 1b 00 15"
    assert len(block) == 1279
    assert int.from_bytes(block[-2:], "big") == (sum(block[:-2]) & 0xFFFF)

# --------------------------------------------------------------------------- #
# 文件清单 e619
# --------------------------------------------------------------------------- #
CAPTURED_FILE_LIST = bytes.fromhex(
    "5A9FA90020E6190000249BEC696D67312E70616B0000002C0690696D67322E70616B000ADF"
)


def test_file_list_matches_captured_bytes() -> None:
    frame = build_file_list([FileEntry("img1.pak", 0x249BEC), FileEntry("img2.pak", 0x2C0690)])
    assert frame == CAPTURED_FILE_LIST


def test_file_entry_rejects_bad_flag() -> None:
    with pytest.raises(ValueError, match="16 位"):
        FileEntry("a.pak", 10, flag=70000).to_bytes()


def test_file_entry_rejects_bad_size() -> None:
    with pytest.raises(ValueError, match="24 位"):
        FileEntry("a.pak", 1 << 24).to_bytes()


def test_file_list_rejects_empty() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        build_file_list([])


def test_file_list_sent_after_upload_when_requested() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        upload_pak(
            transport, b"Q" * 40, name="img7.pak",
            ack_timeout_ms=50,
            files_after=[FileEntry("img7.pak", 52)],
        )
    last = device.written[-1]
    assert last[5:7] == bytes.fromhex("e619")
    assert b"img7.pak" in last


def test_file_list_not_sent_by_default() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        upload_pak(transport, b"R" * 40, ack_timeout_ms=50)
    assert all(w[5:7] != bytes.fromhex("e619") for w in device.written)

# --------------------------------------------------------------------------- #
# 上传流程
# --------------------------------------------------------------------------- #
def test_upload_single_chunk() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        result = upload_pak(transport, b"X" * 100, name="img9.pak", ack_timeout_ms=50)
    assert result.chunks == 1
    assert result.retries == 0
    assert result.size == 100
    # 前两条都是握手（容量预检 + 会话握手），之后是公告和数据块
    assert device.written[0] == UPLOAD_HANDSHAKE_TX
    assert device.written[1] == UPLOAD_HANDSHAKE_TX
    announces = [w for w in device.written if w[5:7] == ANNOUNCE_ID]
    blocks = [w for w in device.written if w[5:7] == DATA_ID]
    assert len(announces) == 1 and len(blocks) == 1


def test_upload_multiple_chunks_progress() -> None:
    device = FakeDevice()
    pak = b"Y" * (CHUNK_SIZE * 2 + 10)
    seen: list[tuple[int, int]] = []
    with make_transport(device) as transport:
        result = upload_pak(
            transport, pak, ack_timeout_ms=50,
            on_progress=lambda done, total: seen.append((done, total)),
        )
    assert result.chunks == 3
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert device.data_blocks == 3


def test_upload_fails_without_handshake_reply() -> None:
    device = FakeDevice()
    device.write = lambda data: (device.written.append(bytes(data)), len(data))[1]  # 从不回包
    with make_transport(device) as transport:
        with pytest.raises(UploadError) as excinfo:
            upload_pak(transport, b"Z" * 10, ack_timeout_ms=30)
    assert excinfo.value.error_code == "HANDSHAKE_FAILED"


def test_upload_retries_when_ack_missing_once() -> None:
    device = FakeDevice(fail_first=1)      # 第一块故意不回 ACK
    with make_transport(device) as transport:
        result = upload_pak(transport, b"A" * 50, ack_timeout_ms=30, max_retries=2)
    assert result.retries == 1
    assert result.chunks == 1


def test_upload_gives_up_after_retries() -> None:
    device = FakeDevice(ack=False)
    with make_transport(device) as transport:
        with pytest.raises(UploadError) as excinfo:
            upload_pak(transport, b"B" * 50, ack_timeout_ms=20, max_retries=1)
    assert excinfo.value.error_code == "ACK_NOT_RECEIVED"


def test_upload_rejects_empty_pak() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        with pytest.raises(UploadError, match="pak 为空"):
            upload_pak(transport, b"", ack_timeout_ms=10)


def test_upload_result_description() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        result = upload_pak(transport, b"C" * 100, name="img9.pak", ack_timeout_ms=50)
    assert "img9.pak" in result.describe()
    assert "1 块" in result.describe()
