# SPDX-License-Identifier: MIT
"""设备设置读写：亮度 / 设备信息 / 开机图 / 开机动画。

协议依据（反编译 `iGameAPI.LCD.CSharp.dll` + 真机）：
* ``0xE01F`` GetSetting   → ``亮度(1) ?(1) 主版本(1) 次版本(1) ?(1) OPType(1) ID(1) …``
* ``0xE11E`` SetSetting   → ``亮度(1) 0(1)``
* ``0xE916`` SetStartImg  → ``"imgN.pak" 00``
* ``0xE21D`` PlayOP       → ``1=Vulcan 2=Kudan``
* ``0xEB14`` SetOP        → ``1=Vulcan 2=Kudan``

这些指令只改设备设置，不碰上传链路；失败一律降级为"读取/设置失败"，
不会影响已上传的素材。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.protocol import build_frame

__all__ = [
    "DeviceSettings",
    "OP_THEMES",
    "read_settings",
    "set_brightness",
    "set_start_image",
    "play_op",
    "set_op_type",
]

GET_SETTING = bytes.fromhex("e01f")
SET_SETTING = bytes.fromhex("e11e")
SET_START_IMAGE = bytes.fromhex("e916")
PLAY_OP = bytes.fromhex("e21d")
SET_OP = bytes.fromhex("eb14")

#: 开机动画主题
OP_THEMES = {0: "未设置", 1: "Vulcan", 2: "Kudan"}

_HEADER = bytes.fromhex("5a9fa9")


@dataclass(frozen=True)
class DeviceSettings:
    """`E01F` 应答解析结果。"""

    brightness: int
    firmware: str
    op_type: int
    device_id: int
    raw: bytes

    def describe(self) -> str:
        theme = OP_THEMES.get(self.op_type, str(self.op_type))
        return (
            f"固件 {self.firmware} · 亮度 {self.brightness}/10 · "
            f"ID {self.device_id} · 开机动画 {theme}"
        )


def _extract_reply(reply: bytes, cmd: bytes) -> bytes | None:
    """从原始字节里找出指定指令的应答 body。"""
    start = reply.find(_HEADER)
    while start >= 0:
        if start + 5 > len(reply):
            return None
        total = reply[start + 4] + 5
        frame = reply[start : start + total]
        if len(frame) >= total and frame[5:7] == cmd:
            return frame[7 : total - 2]
        start = reply.find(_HEADER, start + 1)
    return None


def _request(transport: object, cmd: bytes, body: bytes, *, timeout_s: float = 1.0) -> bytes | None:
    """发一条指令并等待同指令的应答 body。"""
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined]
        transport.write(build_frame(cmd + body))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None

    deadline = time.monotonic() + timeout_s
    buffer = bytearray()
    while time.monotonic() < deadline:
        try:
            chunk = transport.read(4096)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        if chunk:
            buffer.extend(chunk)
            payload = _extract_reply(bytes(buffer), cmd)
            if payload is not None:
                return payload
    return None


def read_settings(transport: object) -> DeviceSettings | None:
    """读取设备设置；失败返回 None（不抛异常）。"""
    body = _request(transport, GET_SETTING, b"")
    if body is None or len(body) < 7:
        return None
    return DeviceSettings(
        brightness=body[0],
        firmware=f"{body[2]}.{body[3]}",
        op_type=body[5],
        device_id=body[6],
        raw=body,
    )


def set_brightness(transport: object, value: int) -> bool:
    """设置亮度 0–10。

    实测设备**不回** SetSetting 的应答，因此写完后回读一次确认是否生效。
    """
    level = max(0, min(10, int(value)))
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined]
        transport.write(build_frame(SET_SETTING + bytes([level, 0])))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False

    for _ in range(5):
        time.sleep(0.25)
        current = read_settings(transport)
        if current is not None and current.brightness == level:
            return True
    return False


def set_start_image(transport: object, name: str) -> bool:
    """把某个素材设为开机图。

    **实测/反编译要点**：官方传的是 ``img1``（`imgName.Substring(0, 4)`，
    不带 ``.pak``）。早期我们发 ``img1.pak``，设备接受但不生效。

    设备不回显确认，发送成功即视为已下发；开机后才会看到效果。
    """
    short = _short_name(name)
    if not short:
        return False
    payload = short.encode("ascii") + b"\x00"
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined]
        transport.write(build_frame(SET_START_IMAGE + payload))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
        return True
    except Exception:  # noqa: BLE001
        return False


def _short_name(name: str) -> str:
    """``img3.pak`` → ``img3``；已是不带扩展名的就原样返回。"""
    text = (name or "").strip()
    if text.lower().endswith(".pak"):
        text = text[:-4]
    return text


def play_op(transport: object, theme: int = 1) -> bool:
    """播放一次开机动画（1=Vulcan 2=Kudan）。

    设备不回显，发送成功即视为已下发。
    """
    try:
        transport.write(build_frame(PLAY_OP + bytes([max(1, min(2, theme))])))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
        return True
    except Exception:  # noqa: BLE001
        return False


def set_op_type(transport: object, theme: int) -> bool:
    """切换开机动画主题（1=Vulcan 2=Kudan），写后回读确认。"""
    target = max(1, min(2, theme))
    try:
        transport.reset_input_buffer()  # type: ignore[attr-defined]
        transport.write(build_frame(SET_OP + bytes([target])))  # type: ignore[attr-defined]
        transport.flush()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False
    for _ in range(5):
        time.sleep(0.25)
        current = read_settings(transport)
        if current is not None and current.op_type == target:
            return True
    return False
