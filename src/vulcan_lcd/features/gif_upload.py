# SPDX-License-Identifier: MIT
"""GIF/图片上传（实测协议实现）。

会话顺序（与抓包逐帧对应）::

    ① ea15 握手      主机 → 设备，设备回 ea15 应答
    ② e31c 公告      文件大小(3B) + 16 位累加和(2B) + 版本 + "imgN.pak"
    ③ e41b 数据块    ×ceil(size/16384)，每块 9 字节头 + 16384 净荷 + 2 字节校验
    ④ e31c 应答      设备逐块回 <块号> 01
    ⑤ 结束           无额外指令

安全边界：本模块只被 ``features.gate`` 允许写时才会被调用（``gif_upload`` 未验证前
闸门返回 READ_ONLY），且不触碰驱动/固件。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

from ..constants import HEADER
from ..core.protocol import FrameInfo, build_frame, parse_frame
from ..media.pak import sum16

__all__ = [
    "CHUNK_SIZE",
    "ANNOUNCE_ID",
    "DATA_ID",
    "UPLOAD_HANDSHAKE_TX",
    "UploadError",
    "UploadResult",
    "FileEntry",
    "build_announce_frame",
    "build_data_block",
    "build_file_list",
    "build_display_frame",
    "build_delete_frame",
    "delete_file",
    "FILE_DELETE_ID",
    "FILE_LIST_QUERY",
    "parse_file_list",
    "query_file_list",
    "query_free_space",
    "parse_free_space",
    "next_slot_name",
    "upload_pak",
]

#: 每个数据块的净荷大小（实测固定 16384）
CHUNK_SIZE = 16384

#: 单次 write 的切片大小。16 KB 一次性写容易触发写超时，分批更稳。
#: 每块之间额外等待的毫秒数。设备写 flash 慢时，加大这个值能显著减少尾部掉 ACK。
DEFAULT_BLOCK_GAP_MS = 0

#: 单块从开始写到最后一次 ACK 的最长允许时间（秒）。
#: 正常一块（16 KB）约 1.5 s，实测最慢正常值约 3 s；
#: 取 60 s 既能容忍设备偶发变慢，又能在真正停摆时及时止损（曾观察到 45 s/块的异常）。
BLOCK_STALL_LIMIT_S = 60.0

WRITE_SLICE = 4096

#: 分片之间的延时（毫秒）。设备 RX 缓冲小，连续猛写会溢出并停摆。
SLICE_DELAY_MS = 2

#: 数据块的 seq1（实测 0x40）
DATA_SEQ1 = 0x40

ANNOUNCE_ID = b"\xe3\x1c"
DATA_ID = b"\xe4\x1b"
HANDSHAKE_ID = b"\xea\x15"

#: 文件清单帧（实测：一次短帧 + 一次列表帧，成对出现）
FILE_LIST_ID = b"\xe6\x19"

#: 删除单个文件（实测：清理无效缓存时，官方逐个删除）
FILE_DELETE_ID = b"\xe7\x18"

#: "显示某个文件"指令（实测官方软件每秒发一次，方向为主机→设备）
DISPLAY_ID = b"\xe5\x1a"

#: 文件清单查询请求（9 字节空帧）：设备会回一条带列表的 e619
FILE_LIST_QUERY = bytes.fromhex("5A9FA90004E61902A5")

#: 上传会话的握手指令（与标题模式的 e0 1f 握手不是同一套）
UPLOAD_HANDSHAKE_TX = bytes.fromhex("5A9FA90004EA1502A5")

#: 公告帧里的两个"未完全解明"字段，实测取值：flag 有两种（00 00 / 00 01），version 恒为 1
DEFAULT_FLAG = b"\x00\x00"
DEFAULT_VERSION = 0x01


class UploadError(Exception):
    """上传失败。``error_code`` 直接进结构化日志。"""

    def __init__(self, message: str, *, error_code: str = "UPLOAD_FAILED") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


@dataclass(frozen=True)
class UploadResult:
    chunks: int
    retries: int
    duration_ms: float
    name: str
    size: int

    def describe(self) -> str:
        return (
            f"{self.name}: {self.size} 字节 / {self.chunks} 块，"
            f"重试 {self.retries} 次，耗时 {self.duration_ms / 1000:.1f}s"
        )


# --------------------------------------------------------------------------- #
# 组包
# --------------------------------------------------------------------------- #
def build_announce_frame(
    name: str,
    size: int,
    checksum: int,
    *,
    flag: bytes = DEFAULT_FLAG,
    version: int = DEFAULT_VERSION,
) -> bytes:
    """构造 e31c 公告帧。"""
    if len(flag) != 2:
        raise ValueError(f"flag 必须是 2 字节: {flag!r}")
    if not 0 <= size <= 0xFFFFFF:
        raise ValueError(f"文件大小必须是 24 位: {size}")
    if not 0 <= checksum <= 0xFFFF:
        raise ValueError(f"校验必须是 16 位: {checksum}")
    if not 0 <= version <= 0xFF:
        raise ValueError(f"版本必须是单字节: {version}")

    body = bytearray()
    body += ANNOUNCE_ID
    body += flag
    body += size.to_bytes(3, "big")
    body += checksum.to_bytes(2, "big")
    body += bytes([version])
    body += name.encode("ascii") + b"\x00"
    return build_frame(bytes(body), seq1=0)


@dataclass(frozen=True)
class FileEntry:
    """文件清单里的一项（实测格式：flag u16 + 大小 u24 + 名字 ASCII）。"""

    name: str
    size: int
    flag: int = 0

    def to_bytes(self) -> bytes:
        if not 0 <= self.flag <= 0xFFFF:
            raise ValueError(f"flag 必须是 16 位: {self.flag}")
        if not 0 <= self.size <= 0xFFFFFF:
            raise ValueError(f"大小必须是 24 位: {self.size}")
        return (
            self.flag.to_bytes(2, "big")
            + self.size.to_bytes(3, "big")
            + self.name.encode("ascii")
            + b"\x00"
        )


def build_delete_frame(name: str) -> bytes:
    """构造 e718 删除指令。

    实测样本（清理缓存时删除 img3.pak）::

        5A9FA9 00 0E | E7 18 | 00 | "img3.pak" 00 | 05 89
    """
    body = FILE_DELETE_ID + b"\x00" + name.encode("ascii") + b"\x00"
    return build_frame(body, seq1=0)


def delete_file(transport: object, name: str) -> None:
    """请求设备删除指定文件（不校验结果，调用方自行查清单确认）。"""
    transport.write(build_delete_frame(name))  # type: ignore[attr-defined]
    transport.flush()  # type: ignore[attr-defined]


def parse_file_list(body: bytes) -> list[FileEntry]:
    """解析 e619 应答体（含固定 ID）为文件条目列表。"""
    entries: list[FileEntry] = []
    index = 2  # 跳过固定 ID
    while index + 5 <= len(body):
        flag = int.from_bytes(body[index : index + 2], "big")
        size = int.from_bytes(body[index + 2 : index + 5], "big")
        end = body.find(b"\x00", index + 5)
        if end < 0:
            break
        name = body[index + 5 : end].decode("ascii", errors="replace")
        entries.append(FileEntry(name=name, size=size, flag=flag))
        index = end + 1
    return entries


def query_file_list(transport: object, *, timeout_ms: int = 1500) -> list[FileEntry]:
    """只读查询设备上的文件清单。失败返回空列表（不抛异常）。"""
    stream = _FrameStream()
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined] - 清掉残留 ACK
        transport.write(FILE_LIST_QUERY)  # type: ignore[attr-defined]
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            for frame in stream.feed(transport.read(4096)):  # type: ignore[attr-defined]
                if frame.fixed_id == FILE_LIST_ID and len(frame.body) > 2:
                    return parse_file_list(frame.body)
    except Exception:  # noqa: BLE001 - 查询失败视为"未知"，不阻断上传
        return []
    return []


#: 当设备清单查询失败（返回空）时使用的安全起始槽位号。
#: 从 20 起，避免覆盖用户已有的 img1..imgN。
SAFE_SLOT_BASE = 20


def next_slot_name(entries: Sequence[FileEntry], *, base: int = 1) -> str:
    """按现有清单推算下一个合法槽位名（imgN.pak）。

    实测（2026-11-06 真机）：设备要求**槽位连续**——只能是
    ``max(已有编号) + 1``，跳号（如已有 img1 却写 img11/img20）会被静默丢弃，
    表现为"上传成功但清单里没有"。清单为空时从 ``base`` 开始。
    """
    used: set[int] = set()
    for entry in entries:
        stem = entry.name.split(".")[0]
        if stem.startswith("img") and stem[3:].isdigit():
            used.add(int(stem[3:]))
    index = (max(used) + 1) if used else max(1, base)
    return f"img{index}.pak"


def parse_free_space(reply: bytes) -> int | None:
    """从 EA15 应答里解出剩余字节数。

    实测应答：``5A9FA9000C EA15 03D3C000 1E3DC000 05 64``
    → 剩余 0x03D3C000 = 64,208,896 字节（≈61 MB，与官方界面显示一致）。
    """
    start = reply.find(bytes.fromhex("5a9fa9"))
    if start < 0 or start + 13 > len(reply):
        return None
    total = reply[start + 4] + 5
    frame = reply[start : start + total]
    if len(frame) < total:
        return None
    body = frame[5 : total - 2]
    if body[0:2] != HANDSHAKE_ID or len(body) < 6:
        return None
    return int.from_bytes(body[2:6], "big")


def query_free_space(transport: object, *, timeout_ms: int = 1200) -> int | None:
    """向设备查询剩余空间（字节）。失败返回 None，不抛异常。"""
    stream = _FrameStream()
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined]
        transport.write(UPLOAD_HANDSHAKE_TX)  # type: ignore[attr-defined]
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            for frame in stream.feed(transport.read(4096)):  # type: ignore[attr-defined]
                if frame.fixed_id == HANDSHAKE_ID and len(frame.body) >= 6:
                    return int.from_bytes(frame.body[2:6], "big")
    except Exception:  # noqa: BLE001 - 查询失败视为未知
        return None
    return None


def build_display_frame(name: str) -> bytes:
    """构造 e51a "显示这个文件" 指令。

    实测官方软件**每秒发送一次**，方向是主机 → 设备（端点 0x09, OUT）。
    本项目早期把它误当成"设备上报的、当前显示文件名"的心跳，导致上传后从不发送，
    设备便一直停留在默认动画上。

    样本::

        5A9FA9000D E51A "img1.pak" 00 0586
    """
    body = DISPLAY_ID + name.encode("ascii") + b"\x00"
    return build_frame(body, seq1=0)


def build_file_list(entries: Sequence[FileEntry]) -> bytes:
    """构造 e619 文件清单帧。

    实测样本（captureA，两个文件）::

        5A9FA90020 E619 0000 249BEC "img1.pak" 00 0000 2C0690 "img2.pak" 00 0ADF

    官方软件在上传完成后会推一次清单，让设备知道多了一个文件——
    这很可能就是"上传后自动上屏"的关键（我们之前没发）。
    """
    if not entries:
        raise ValueError("文件清单不能为空")
    body = bytearray(FILE_LIST_ID)
    for entry in entries:
        body += entry.to_bytes()
    return build_frame(bytes(body), seq1=0)


def build_data_block(index: int, payload: bytes) -> bytes:
    """构造一个 e41b 数据块。

    注意：长度字段只描述包头（``0x06``），但**校验覆盖 头 + 全部数据**。
    """
    if not 0 <= index <= 0xFFFF:
        raise ValueError(f"块序号必须是 16 位: {index}")
    if len(payload) > CHUNK_SIZE:
        raise ValueError(f"单块净荷最多 {CHUNK_SIZE} 字节，收到 {len(payload)}")

    # 头两个字节是 **16 位大端长度 = 整块长度 − 5**（不是"序号 + 0x06"）。
    # 满块时 0x4006 = 16390 = 16395−5 恰好成立，所以早期误以为它是常量；
    # 只有不满 16KB 的尾块才会暴露（实机样本：1279 字节的块字段是 0x04FA）。
    total = 3 + 2 + 2 + 2 + len(payload) + 2
    length_field = total - 5
    head = HEADER + length_field.to_bytes(2, "big") + DATA_ID + index.to_bytes(2, "big")
    body = head + payload
    return body + sum16(body).to_bytes(2, "big")


# --------------------------------------------------------------------------- #
# 收包（读 ACK）
# --------------------------------------------------------------------------- #
class _FrameStream:
    """把连续字节流切成帧，用于从应答里找 ACK。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[FrameInfo]:
        self._buf += data
        frames: list[FrameInfo] = []
        while True:
            start = self._buf.find(HEADER)
            if start < 0:
                # 保留末尾 2 字节，可能是被截断的帧头
                del self._buf[: max(0, len(self._buf) - 2)]
                break
            if start:
                del self._buf[:start]
            if len(self._buf) < 5:
                break
            # 控制帧长度字段是 1 字节（offset 4）；数据块风格是 2 字节（offset 3-4）。
            # 先用 1 字节解析并校验，失败再尝试 2 字节，避免将来遇到长帧时错位。
            total = self._buf[4] + 5
            raw: bytes | None = None
            if total >= 7 and len(self._buf) >= total:
                candidate = bytes(self._buf[:total])
                if (sum(candidate[:-2]) & 0xFFFF) == int.from_bytes(candidate[-2:], "big"):
                    raw = candidate
            if raw is None and len(self._buf) >= 6:
                alt_total = int.from_bytes(self._buf[3:5], "big") + 5
                if alt_total >= 7 and len(self._buf) >= alt_total:
                    candidate = bytes(self._buf[:alt_total])
                    if (sum(candidate[:-2]) & 0xFFFF) == int.from_bytes(candidate[-2:], "big"):
                        raw = candidate
                        total = alt_total
            if raw is None:
                break
            del self._buf[:total]
            try:
                frames.append(parse_frame(raw, strict=False))
            except Exception:  # noqa: BLE001 - 坏帧直接丢弃，不打断流程
                continue
        return frames


#: ACK 状态码（逆向文档 §5.3）
ACK_OK = "ok"          # 01 收下
ACK_RESEND = "resend"  # 04 要求从该块重发
ACK_ERROR = "error"    # 02/03/05 设备报错
ACK_TIMEOUT = "timeout"


def _wait_for_ack(
    transport: object,
    stream: _FrameStream,
    index: int,
    *,
    timeout_ms: int,
) -> str:
    """等待该块的应答，返回状态码（见 ACK_* 常量）。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        chunk = transport.read(4096)  # type: ignore[attr-defined]
        for frame in stream.feed(chunk):
            if frame.fixed_id != ANNOUNCE_ID:
                continue
            payload = frame.body[2:]
            if len(payload) < 3 or payload[0:2] != index.to_bytes(2, "big"):
                continue
            status = payload[2]
            if status == 0x01:
                return ACK_OK
            if status == 0x04:
                return ACK_RESEND
            if status in (0x02, 0x03, 0x05):
                return ACK_ERROR
    return ACK_TIMEOUT


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def upload_pak(
    transport: object,
    pak_bytes: bytes,
    *,
    name: str = "img9.pak",
    flag: bytes = DEFAULT_FLAG,
    version: int = DEFAULT_VERSION,
    ack_timeout_ms: int = 8000,
    max_retries: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
    block_gap_ms: int = DEFAULT_BLOCK_GAP_MS,
    sleeper: Callable[[float], None] = time.sleep,
    files_after: Sequence[FileEntry] | None = None,
    final_handshake: bool = True,
    display_name: str | None = None,
    display_seconds: float = 0.0,
    display_interval_ms: int = 1000,
    file_list_delay_ms: int = 50,
    announce_wait_ms: int = 1000,
) -> UploadResult:
    """把 pak 上传到屏幕。

    Args:
        transport: 已打开的 :class:`~vulcan_lcd.core.transport.Transport`。
        pak_bytes: :func:`~vulcan_lcd.media.pak.build_pak` 生成的字节串。
        name: 目标文件名，实测形如 ``img2.pak``。
        flag/version: 公告帧里的两个未完全解明字段，默认沿用实测值。
        ack_timeout_ms: 单块等待 ACK 的上限。
        max_retries: 单块 ACK 超时后的重发次数。
        on_progress: ``(已发送块数, 总块数)`` 回调。
        files_after: 上传完成后要推送的**文件清单**（e619）。实测官方软件在
            上传后会推一次，让设备知道多了文件；不发的话设备可能不会切换显示。
        file_list_delay_ms: 推清单前的等待，给设备一点处理时间。

    Raises:
        UploadError: 握手失败 / ACK 一直收不到。
    """
    if not pak_bytes:
        raise UploadError("pak 为空", error_code="PAK_EMPTY")

    started = time.monotonic()
    stream = _FrameStream()

    # 容量预检：设备剩余空间不足时直接失败，避免写坏文件
    free = query_free_space(transport)
    if free is not None and len(pak_bytes) > max(0, free - 1024):
        raise UploadError(
            f"设备剩余空间不足：需要 {len(pak_bytes)} 字节，可用 {free} 字节",
            error_code="NO_SPACE",
        )

    # ① 握手
    transport.reset_input_buffer()  # type: ignore[attr-defined]
    transport.write(UPLOAD_HANDSHAKE_TX)  # type: ignore[attr-defined]
    handshake_ok = False
    deadline = time.monotonic() + ack_timeout_ms / 1000.0
    while time.monotonic() < deadline:
        for frame in stream.feed(transport.read(4096)):  # type: ignore[attr-defined]
            if frame.fixed_id == HANDSHAKE_ID:
                handshake_ok = True
        if handshake_ok:
            break
    if not handshake_ok:
        raise UploadError("上传握手无应答", error_code="HANDSHAKE_FAILED")

    # ② 公告
    announce = build_announce_frame(name, len(pak_bytes), sum16(pak_bytes), flag=flag, version=version)
    transport.write(announce)  # type: ignore[attr-defined]
    # 设备收到公告后要完成文件分配；不等会直接丢第一块 ACK（逆向文档 §5.3）
    if announce_wait_ms > 0:
        sleeper(announce_wait_ms / 1000.0)

    # 公告应答必须显式读掉并确认状态为 1。
    # 若不然，这条应答会被后续块 ACK 的循环当成"第 0 块已确认"，
    # 于是设备没分配文件、宿主却以为上传成功（实测踩坑）。
    announce_status: int | None = None
    reply_deadline = time.monotonic() + ack_timeout_ms / 1000.0
    while time.monotonic() < reply_deadline and announce_status is None:
        for frame in stream.feed(transport.read(4096)):  # type: ignore[attr-defined]
            if frame.fixed_id != ANNOUNCE_ID:
                continue
            body = frame.body[2:]
            if len(body) >= 3 and body[0:2] == b"\x00\x00":
                announce_status = body[2]
                break
    if announce_status is None:
        raise UploadError(
            "公告无应答（设备没有确认文件分配）",
            error_code="ANNOUNCE_NO_REPLY",
        )
    if announce_status != 0x01:
        raise UploadError(
            f"公告被设备拒绝（状态 {announce_status:02X}）：可能是空间不足或文件名非法",
            error_code="ANNOUNCE_REJECTED",
        )

    # ③④ 分块 + 逐块 ACK
    total_chunks = (len(pak_bytes) + CHUNK_SIZE - 1) // CHUNK_SIZE
    retries = 0
    for index in range(total_chunks):
        payload = pak_bytes[index * CHUNK_SIZE : (index + 1) * CHUNK_SIZE]
        block = build_data_block(index, payload)

        block_started = time.monotonic()
        attempt = 0
        while True:
            if time.monotonic() - block_started > BLOCK_STALL_LIMIT_S:
                raise UploadError(
                    f"第 {index} 块写入超时（>{BLOCK_STALL_LIMIT_S:.0f}s），设备可能已停摆；"
                    f"（已发送 {index}/{total_chunks} 块）",
                    error_code="DEVICE_STALLED",
                )
            # 分片写 + 片间延时：设备 RX 缓冲小，连续猛写会溢出停摆（实测会永久卡死）。
            for offset in range(0, len(block), WRITE_SLICE):
                transport.write(block[offset : offset + WRITE_SLICE], flush=False)  # type: ignore[attr-defined]
                if SLICE_DELAY_MS:
                    sleeper(SLICE_DELAY_MS / 1000.0)
            transport.flush()  # type: ignore[attr-defined]
            status = _wait_for_ack(transport, stream, index, timeout_ms=ack_timeout_ms)
            if status == ACK_OK:
                break
            if status == ACK_RESEND:
                # 设备要求从该块重发：直接重试且不计入失败
                retries += 1
                if retries > max_retries * 2:
                    raise UploadError(
                        f"第 {index} 块被反复要求重发",
                        error_code="ACK_RESEND_LOOP",
                    )
                continue
            if status == ACK_ERROR:
                raise UploadError(
                    f"第 {index} 块被设备拒绝（状态 02/03/05）",
                    error_code="ACK_REJECTED",
                )
            attempt += 1
            retries += 1
            if attempt > max_retries:
                raise UploadError(
                    f"第 {index} 块未收到 ACK（已重试 {attempt - 1} 次）",
                    error_code="ACK_NOT_RECEIVED",
                )
        if block_gap_ms > 0:
            sleeper(block_gap_ms / 1000.0)
        if on_progress is not None:
            on_progress(index + 1, total_chunks)

    # ⑤ 收尾握手：实测官方在最后一块 ACK 后会再发一次 ea15 握手，
    #    推测这是"提交/生效"信号。不发的话文件虽写入但不会切换显示。
    if final_handshake:
        if file_list_delay_ms:
            sleeper(file_list_delay_ms / 1000.0)
        transport.write(UPLOAD_HANDSHAKE_TX)  # type: ignore[attr-defined]
        deadline = time.monotonic() + ack_timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if any(f.fixed_id == HANDSHAKE_ID for f in stream.feed(transport.read(4096))):  # type: ignore[attr-defined]
                break

    # ⑥ 可选：推送文件清单，让设备知道多了一个文件
    if files_after:
        if file_list_delay_ms:
            sleeper(file_list_delay_ms / 1000.0)
        transport.write(build_file_list(files_after))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]

    # ⑦ 发送"显示该文件"指令：官方软件每秒一次，是屏幕真正切换的关键。
    if display_name:
        frame = build_display_frame(display_name)
        transport.write(frame)  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
        if display_seconds > 0:
            deadline = time.monotonic() + display_seconds
            while time.monotonic() < deadline:
                sleeper(display_interval_ms / 1000.0)
                if time.monotonic() >= deadline:
                    break
                transport.write(frame)  # type: ignore[attr-defined]
                transport.flush()  # type: ignore[attr-defined]

    duration = (time.monotonic() - started) * 1000
    return UploadResult(
        chunks=total_chunks,
        retries=retries,
        duration_ms=duration,
        name=name,
        size=len(pak_bytes),
    )
