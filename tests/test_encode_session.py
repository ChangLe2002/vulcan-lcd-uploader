# SPDX-License-Identifier: MIT
"""编码链路与屏幕会话测试（不碰真机）。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from vulcan_lcd.core.transport import Transport
from vulcan_lcd.features.gif_upload import (
    ANNOUNCE_ID,
    DATA_ID,
    FileEntry,
    build_display_frame,
    next_slot_name,
    parse_file_list,
    query_file_list,
)
from vulcan_lcd.features.screen_session import run_screen_session
from vulcan_lcd.media.encode import (
    DEFAULT_QUALITY,
    EncodeError,
    encode_jpeg,
    encode_media_to_pak,
)
from vulcan_lcd.media.pak import parse_pak
from vulcan_lcd.core.protocol import build_frame

ROOT = Path(__file__).resolve().parent.parent
# 测试素材由 tests/conftest.py 按需生成，不依赖仓库外的文件
from conftest import SAMPLE_GIF, ensure_sample_gif  # noqa: E402

ensure_sample_gif()


# --------------------------------------------------------------------------- #
# 编码
# --------------------------------------------------------------------------- #
def test_encode_jpeg_roundtrip() -> None:
    from PIL import Image

    jpeg = encode_jpeg(Image.new("RGB", (64, 32), (10, 20, 30)), quality=70)
    assert jpeg.startswith(b"\xff\xd8")
    assert jpeg.endswith(b"\xff\xd9")


def test_encode_jpeg_rejects_bad_quality() -> None:
    from PIL import Image

    with pytest.raises(EncodeError, match="质量"):
        encode_jpeg(Image.new("RGB", (8, 8)), quality=99)


def test_encode_jpeg_rejects_non_image() -> None:
    with pytest.raises(EncodeError, match="PIL"):
        encode_jpeg("not an image")


@pytest.mark.skipif(not SAMPLE_GIF.is_file(), reason="缺少测试用 GIF")
def test_encode_media_produces_valid_pak() -> None:
    """3 帧 / 1.5 秒的 GIF：源帧率 2，重采样到 30fps 后约 45 帧。

    pak 头里写的是**源视频帧率**（反编译证实 iGame_JPG_to_Pak 的第二个参数）。
    """
    result = encode_media_to_pak(SAMPLE_GIF, quality=70)
    assert result.width == 1024 and result.height == 240
    assert result.fps == 2            # 3 帧 / 1.5 秒 = 2 fps（源帧率）
    assert 40 <= result.frames <= 50          # 1.5s × 30fps ≈ 45

    parsed = parse_pak(result.pak)
    assert parsed.frame_count == result.frames
    assert parsed.fps == 2
    for frame in parsed.frames:
        assert frame.startswith(b"\xff\xd8")
        assert frame.endswith(b"\xff\xd9")


@pytest.mark.skipif(not SAMPLE_GIF.is_file(), reason="缺少测试用 GIF")
def test_encode_progress_callback() -> None:
    seen: list[tuple[int, int]] = []
    encode_media_to_pak(SAMPLE_GIF, quality=50, on_progress=lambda d, t: seen.append((d, t)))
    assert seen
    assert seen[-1][0] == seen[-1][1]


# --------------------------------------------------------------------------- #
# 槽位与清单
# --------------------------------------------------------------------------- #
def test_next_slot_name_is_contiguous() -> None:
    """实测：设备要求槽位连续，只能是 max+1，跳号会被静默丢弃。"""
    assert next_slot_name([]) == "img1.pak"
    assert next_slot_name([FileEntry("img1.pak", 1)]) == "img2.pak"
    # 有空洞也必须往后接，不能去补 img2
    assert next_slot_name([FileEntry("img1.pak", 1), FileEntry("img3.pak", 2)]) == "img4.pak"
    assert next_slot_name([FileEntry("other.pak", 1)]) == "img1.pak"


def test_parse_file_list_roundtrip() -> None:
    body = bytes.fromhex("e6190000249bec696d67312e70616b0000002c0690696d67322e70616b00")
    entries = parse_file_list(body)
    assert [e.name for e in entries] == ["img1.pak", "img2.pak"]
    assert entries[0].size == 0x249BEC
    assert entries[1].size == 0x2C0690


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
class FakeController:
    def __init__(self, *, fail_on_takeover: bool = False) -> None:
        self.took = 0
        self.released = 0
        self.fail = fail_on_takeover

    def takeover(self) -> bool:
        from vulcan_lcd.system.service_control import ServiceError

        if self.fail:
            raise ServiceError("停服务失败")
        self.took += 1
        return True

    def release(self) -> bool:
        self.released += 1
        return True


class FakeDevice:
    def __init__(self, *, file_list: bytes | None = None) -> None:
        self.written: list[bytes] = []
        self._rx = bytearray()
        self.file_list = file_list
        self.closed = 0
        self.opened = 0

    # serial 接口
    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        if data[:3] != bytes.fromhex("5a9fa9"):
            return len(data)
        if data[5:7] == bytes.fromhex("ea15"):
            self._rx += bytes.fromhex("5A9FA9000CEA1503D3C0001E3DC000055E")
        elif data[5:7] == ANNOUNCE_ID:
            # 公告应答：index=0000, status=01（设备已分配文件）
            self._rx += build_frame(ANNOUNCE_ID + b"\x00\x00\x01")
        elif data[5:7] == bytes.fromhex("e619") and len(data) == 9 and self.file_list:
            self._rx += self.file_list
        elif data[5:7] == DATA_ID:
            index = int.from_bytes(data[7:9], "big")
            self._rx += build_frame(ANNOUNCE_ID + index.to_bytes(2, "big") + b"\x01")
        return len(data)

    def read(self, n: int) -> bytes:
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def flush(self) -> None: ...
    def close(self) -> None:
        self.closed += 1


def make_transport(device: FakeDevice) -> Transport:
    return Transport("COM_TEST", serial_factory=lambda p, k: device)


def test_session_uploads_and_sends_display() -> None:
    device = FakeDevice()
    controller = FakeController()
    stop = threading.Event()
    frames_sent: list[float] = []

    def fake_sleep(seconds: float) -> None:
        frames_sent.append(seconds)
        if len(frames_sent) >= 3:
            stop.set()

    report = run_screen_session(
        b"Z" * 40,
        controller=controller,      # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=stop,
        name="img7.pak",
        on_uploaded=lambda n: frames_sent.append(-1),
        sleeper=fake_sleep,
    )

    assert report.uploaded is True
    assert report.name == "img7.pak"
    assert report.error is None
    assert controller.took == 1 and controller.released == 1
    assert device.closed == 1
    display_frames = [w for w in device.written if w[5:7] == bytes.fromhex("e51a")]
    assert display_frames, "应当发送显示指令"
    assert display_frames[0] == build_display_frame("img7.pak")


def test_session_stop_before_start_still_restores() -> None:
    device = FakeDevice()
    controller = FakeController()
    stop = threading.Event()
    stop.set()

    report = run_screen_session(
        b"Y" * 40,
        controller=controller,      # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=stop,
        name="img8.pak",
        sleeper=lambda s: None,
    )

    assert report.uploaded is True
    assert report.display_seconds == 0
    assert controller.released == 1
    assert device.closed == 1


def test_session_reports_service_error() -> None:
    device = FakeDevice()
    controller = FakeController(fail_on_takeover=True)

    report = run_screen_session(
        b"X" * 40,
        controller=controller,      # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=threading.Event(),
        name="img9.pak",
        ack_timeout_ms=30,
        sleeper=lambda s: None,
    )

    assert report.uploaded is False
    assert report.error
    assert controller.released == 0      # 没接管成功就不该恢复
    assert device.closed == 0            # 串口没打开过，close 是空操作


def test_session_picks_next_slot_from_device() -> None:
    file_list = bytes.fromhex(
        "5A9FA90020E6190000249BEC696D67312E70616B0000002C0690696D67322E70616B000ADF"
    )
    device = FakeDevice(file_list=file_list)
    controller = FakeController()
    stop = threading.Event()
    stop.set()

    report = run_screen_session(
        b"W" * 40,
        controller=controller,      # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=stop,
        sleeper=lambda s: None,
    )

    assert report.name == "img3.pak"


def test_query_file_list_returns_empty_when_silent() -> None:
    device = FakeDevice()
    with make_transport(device) as transport:
        assert query_file_list(transport, timeout_ms=20) == []


def test_encode_jpeg_limited_respects_budget() -> None:
    """高噪声图像在默认质量下必然超标，应当自动降质到预算内。"""
    from PIL import Image

    from vulcan_lcd.media.encode import encode_jpeg_limited

    # 用带细节的渐变（可压缩），默认质量下会超出预算，降质后应显著变小
    img = Image.new("RGB", (1024, 240))
    img.putdata([
        ((x * 7 + y * 3) % 256, (x * 5) % 256, (y * 11) % 256)
        for y in range(240) for x in range(1024)
    ])
    baseline = encode_jpeg(img, quality=85)
    data, quality = encode_jpeg_limited(img, max_bytes=16_384)
    assert quality < 85, "应当降质"
    assert len(data) < len(baseline), "降质后应当更小"
    assert data.startswith(b"\xff\xd8")


def test_encode_resamples_to_device_fps() -> None:
    """慢素材必须补足帧数，否则设备按 30fps 会放得飞快。"""
    result = encode_media_to_pak(SAMPLE_GIF, quality=60)
    # 设备固定 30fps 播放，时长 = 帧数 / 30（pak 头存的是源帧率，不是播放帧率）
    duration_s = result.frames / 30
    assert 1.4 <= duration_s <= 1.7, f"重采样后时长应接近 1.5s，实际 {duration_s:.2f}s"


def test_jpeg_has_no_app0_and_single_dqt() -> None:
    """关键回归：必须无 APP0、只有一张量化表，否则设备会裁切画面。"""
    from PIL import Image

    from vulcan_lcd.media.encode import encode_jpeg_official

    data = encode_jpeg_official(Image.new("RGB", (64, 32), (10, 20, 30)), quality=80)
    index = 2
    markers = []
    while index < len(data) - 3:
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        markers.append(marker)
        if marker in (0xDA, 0xD9):
            break
        index += 2 + int.from_bytes(data[index + 2 : index + 4], "big")

    assert markers.count(0xE0) == 0, "不应包含 APP0(JFIF)"
    assert markers.count(0xDB) == 1, "应只有一张量化表"
    assert 0xC0 in markers or 0xC1 in markers or 0xC2 in markers


# --------------------------------------------------------------------------- #
# 审查意见回归
# --------------------------------------------------------------------------- #
def test_capacity_limit_reduces_size() -> None:
    """收紧预算后，产物应显著变小（降质重编生效）。"""
    default = encode_media_to_pak(SAMPLE_GIF, quality=85)
    tight = encode_media_to_pak(SAMPLE_GIF, quality=85, max_pak_bytes=200_000)
    assert tight.size < default.size
    assert tight.frames == default.frames, "不应通过抽帧来达标"


def test_session_rejects_fallback_when_file_existed_before(monkeypatch) -> None:
    """上传前已存在同名文件时，即使清单里能看到它，也不能判定为本次写入成功。"""
    import vulcan_lcd.features.screen_session as ss
    from vulcan_lcd.features.gif_upload import FileEntry, UploadError

    def fake_query(transport, timeout_ms=1500):
        return [FileEntry(name="img7.pak", size=40)]

    def fake_upload(transport, pak, **kwargs):
        raise UploadError("末块无 ACK", error_code="ACK_NOT_RECEIVED")

    monkeypatch.setattr(ss, "query_file_list", fake_query)
    monkeypatch.setattr(ss, "upload_pak", fake_upload)

    device = FakeDevice()
    stop = threading.Event()
    stop.set()

    report = ss.run_screen_session(
        b"V" * 40,
        controller=FakeController(),   # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=stop,
        name="img7.pak",
        ack_timeout_ms=30,
        sleeper=lambda s: None,
    )

    assert report.uploaded is False
    assert "已存在" in (report.error or "")


def test_session_accepts_fallback_for_new_file(monkeypatch) -> None:
    """上传前不存在该文件时，清单里出现同大小文件即可采信（设备写盘成功但丢了 ACK）。"""
    import vulcan_lcd.features.screen_session as ss
    from vulcan_lcd.features.gif_upload import FileEntry, UploadError

    calls = {"n": 0}

    def fake_query(transport, timeout_ms=1500):
        calls["n"] += 1
        # 第一次（上传前）为空；之后出现目标文件
        return [] if calls["n"] == 1 else [FileEntry(name="img8.pak", size=40)]

    def fake_upload(transport, pak, **kwargs):
        raise UploadError("末块无 ACK", error_code="ACK_NOT_RECEIVED")

    monkeypatch.setattr(ss, "query_file_list", fake_query)
    monkeypatch.setattr(ss, "upload_pak", fake_upload)

    device = FakeDevice()
    stop = threading.Event()
    stop.set()

    report = ss.run_screen_session(
        b"V" * 40,
        controller=FakeController(),   # type: ignore[arg-type]
        transport=make_transport(device),
        stop_event=stop,
        name="img8.pak",
        ack_timeout_ms=30,
        sleeper=lambda s: None,
    )

    assert report.uploaded is True
    assert report.name == "img8.pak"


def test_frame_stream_accepts_two_byte_length() -> None:
    """数据块风格（2 字节长度）的帧也应能被流解析器识别。"""
    from vulcan_lcd.features.gif_upload import _FrameStream
    from vulcan_lcd.media.pak import sum16

    payload = b"imgX.pak\x00"
    body = b"\xe5\x1a" + payload
    total = 3 + 2 + len(body) + 2
    head = b"\x5a\x9f\xa9" + (total - 5).to_bytes(2, "big")
    frame = head + body
    frame += sum16(frame).to_bytes(2, "big")

    stream = _FrameStream()
    parsed = stream.feed(frame)
    assert len(parsed) == 1


# --------------------------------------------------------------------------- #
# 逆向文档对齐项
# --------------------------------------------------------------------------- #
def test_ffmpeg_encoder_structure() -> None:
    """ffmpeg 产物应与官方同构：COM → DQT → DHT → SOF0 → SOS。"""
    from PIL import Image

    from vulcan_lcd.media.encode import encode_jpeg_ffmpeg, find_ffmpeg
    from vulcan_lcd.media.jpeg_layout import describe

    if find_ffmpeg() is None:
        pytest.skip("本机没有 ffmpeg")

    data = encode_jpeg_ffmpeg(Image.new("RGB", (64, 32), (200, 30, 30)), quality=85)
    names = describe(data)
    assert names[0] == "COM", names
    assert "DQT" in names and "DHT" in names and "SOF0" in names
    assert data[:2] == b"\xff\xd8"


def test_pil_backend_has_no_com() -> None:
    from PIL import Image

    from vulcan_lcd.media.encode import encode_jpeg_best
    from vulcan_lcd.media.jpeg_layout import describe

    data = encode_jpeg_best(Image.new("RGB", (64, 32), (1, 2, 3)), quality=80, backend="pil")
    assert "COM" not in describe(data)


def test_free_space_parse_from_capture() -> None:
    """实测 EA15 应答里的前 4 字节是剩余空间。"""
    from vulcan_lcd.features.gif_upload import parse_free_space

    reply = bytes.fromhex("5A9FA9000CEA1503D3C0001E3DC000055E")
    assert parse_free_space(reply) == 0x03D3C000 == 64_208_896


def test_ack_status_codes() -> None:
    from vulcan_lcd.features.gif_upload import ACK_ERROR, ACK_OK, ACK_RESEND, ACK_TIMEOUT, _FrameStream, _wait_for_ack

    class DummyTransport:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self, n: int) -> bytes:
            data, self._payload = self._payload, b""
            return data

    def frame(status: int) -> bytes:
        from vulcan_lcd.core.protocol import build_frame

        return build_frame(bytes.fromhex("e31c") + b"\x00\x07" + bytes([status]))

    assert _wait_for_ack(DummyTransport(frame(0x01)), _FrameStream(), 7, timeout_ms=50) == ACK_OK
    assert _wait_for_ack(DummyTransport(frame(0x04)), _FrameStream(), 7, timeout_ms=50) == ACK_RESEND
    assert _wait_for_ack(DummyTransport(frame(0x02)), _FrameStream(), 7, timeout_ms=50) == ACK_ERROR
    assert _wait_for_ack(DummyTransport(b""), _FrameStream(), 7, timeout_ms=30) == ACK_TIMEOUT
