# SPDX-License-Identifier: MIT
"""串口链路：UI 层与硬件之间的**唯一**通道。

设计意图：面板不许自己 ``Transport(...)``。所有"能不能发"的判断都在这里做，
于是只有一处需要审计，也只有一处可能出错。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..app import AppContext
from ..core.handshake import HandshakeResult, perform_handshake, send_init_sequence
from ..core.protocol import TitleEncoding, build_time_frame
from ..core.transport import SerialSettings, Transport, TransportError

__all__ = ["SerialLink"]


class SerialLink(QObject):
    """串口连接状态与发送动作。"""

    opened = Signal(str)          # 端口名
    closed = Signal()
    failed = Signal(str)          # 人类可读的失败原因
    sent = Signal(str, bytes)     # (动作名, 原始字节)
    received = Signal(bytes)

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._transport: Transport | None = None

    # -- 状态 ------------------------------------------------------------- #
    @property
    def is_open(self) -> bool:
        return self._transport is not None and self._transport.is_open

    @property
    def port(self) -> str:
        return self._transport.port if self._transport else ""

    # -- 连接 ------------------------------------------------------------- #
    def open(self, port: str) -> bool:
        self.close()
        transport = Transport(
            port,
            SerialSettings(),
            dry_run=self._ctx.session.dry_run,
            on_rx=self.received.emit,
        )
        try:
            transport.open()
        except TransportError as exc:
            self._ctx.logger.error(
                "port_open",
                feature_id="auto_port_scan",
                result="fail",
                error_code=exc.error_code,
                detail=exc.message,
                port=port,
            )
            self.failed.emit(f"{port} 打开失败：{exc.message}")
            return False

        self._transport = transport
        self._ctx.logger.info("port_open", feature_id="auto_port_scan", port=port, dry_run=transport.dry_run)
        self.opened.emit(port)
        return True

    def close(self) -> None:
        if self._transport is not None:
            port = self._transport.port
            self._transport.close()
            self._transport = None
            self._ctx.logger.info("port_close", feature_id="auto_port_scan", port=port)
        self.closed.emit()


    def ensure_open(self) -> bool:
        """按需自动连接：已打开直接返回 True，否则自动找口并打开。

        界面不再提供手动连接按钮，所有发送动作都通过这里拿到可用连接。
        """
        if self.is_open:
            return True
        from ..core.port_scanner import find_lcd_port  # noqa: PLC0415

        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or ""
        )
        if not port:
            self.failed.emit("未检测到智屏串口（检查 USB 连接）")
            return False
        return self.open(port)

    # -- 握手 ------------------------------------------------------------- #
    def handshake(self, timeout_ms: int = 800) -> HandshakeResult | None:
        if self._transport is None:
            self.failed.emit("串口未打开")
            return None
        result = perform_handshake(self._transport, timeout_ms=timeout_ms)
        self._ctx.logger.log(
            "INFO" if result.matched else "WARNING",
            "handshake",
            feature_id="auto_port_scan",
            result="ok" if result.matched else "fail",
            error_code=None if result.matched else "HANDSHAKE_FAILED",
            tx=result.sent,
            rx=result.reply or None,
            detail=result.reason or "",
        )
        if result.reply:
            self.received.emit(result.reply)
        return result

    # -- 发送 ------------------------------------------------------------- #
    def send_title(self, encoding: TitleEncoding) -> bool:
        """发送标题帧。需要 ``title_display`` 为 verified。"""
        if not self._ctx.feature_allowed("title_display"):
            self.failed.emit(self._ctx.blocked_reason("title_display") or "title_display 不可用")
            return False
        if self._transport is None:
            self.failed.emit("串口未打开")
            return False

        frame = build_time_frame(encoding)
        try:
            self._ctx.gate.require_write("title_display")
            self._transport.write(frame)
        except Exception as exc:  # noqa: BLE001 - 统一转成 UI 可读信息
            self._ctx.logger.error(
                "send_title", feature_id="title_display", result="fail",
                error_code=getattr(exc, "error_code", "UNKNOWN"), detail=str(exc), tx=frame,
            )
            self.failed.emit(str(exc))
            return False

        self._ctx.logger.info("send_title", feature_id="title_display", tx=frame, chars=len(encoding.text))
        self.sent.emit("title", frame)
        return True

    def send_init_sequence(self) -> None:
        if self._transport is None:
            return
        if self._ctx.session.dry_run:
            self._ctx.logger.info("init_sequence_skipped", feature_id="title_display", result="skipped")
            return
        send_init_sequence(self._transport)
        self._ctx.logger.info("init_sequence", feature_id="title_display")

    def send_manual_hex(self, payload: bytes, *, confirmed: bool) -> bool:
        """人工原始发送（受控例外，需调试模式 + 二次确认）。"""
        try:
            self._ctx.gate.require_manual_raw(confirmed=confirmed, config=self._ctx.config)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return False
        if self._transport is None:
            self.failed.emit("串口未打开")
            return False

        self._transport.write(payload)
        self._ctx.logger.warning(
            "manual_send", feature_id="manual_raw_hex", tx=payload, bytes=len(payload)
        )
        self.sent.emit("manual", payload)
        return True
