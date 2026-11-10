# SPDX-License-Identifier: MIT
"""结构化日志：控制台 + 按天文件，字段固定，可按 feature_id 过滤。

为什么不用标准库 logging 的 Formatter
------------------------------------
需求要求每条日志**必须**带 ``feature_id`` / ``action`` / ``result`` /
``error_code`` / ``duration_ms`` 这五个字段，且串口场景要附截断后的
``tx_hex`` / ``rx_hex``。用 ``record.__dict__`` 塞 payload 再在 Formatter 里
拼 JSON 也能做，但字段缺失、类型漂移都只能靠约定；这里直接用 dataclass 建模，
缺字段在构造期就报错。

生产模式的红线
--------------
不记录大块图像数据。一帧 800×216 RGB565 是 345,600 字节，日志里放三帧就能
把磁盘写满。因此 ``tx``/``rx`` 只记录**截断后的前 N 字节**，且生产模式下
（``log_raw_serial=False``）连截断版都不记。
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

__all__ = [
    "LogLevel",
    "LogEvent",
    "StructuredLogger",
    "read_events",
    "DEFAULT_RAW_LIMIT",
]

DEFAULT_RAW_LIMIT = 64

#: 错误分类（需求 §9.3 要求至少覆盖这些）
ERROR_CODES = (
    "PROTOCOL_UNVERIFIED",
    "CHECKSUM_MISMATCH",
    "HANDSHAKE_FAILED",
    "TIMEOUT",
    "ACK_NOT_RECEIVED",
    "SERVICE_BUSY",
    "PERMISSION_DENIED",
    "PREPROCESS_FAILED",
    "DEVICE_NOT_FOUND",
    "ENV_ERROR",
    "UNKNOWN",
)


class LogLevel:
    """级别常量（用字符串，便于过滤与人工阅读）。"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    ALL = (DEBUG, INFO, WARNING, ERROR)


@dataclass(frozen=True)
class LogEvent:
    """一条结构化日志。字段顺序即输出顺序。"""

    timestamp: str
    level: str
    module: str
    feature_id: str | None
    action: str
    result: str = "ok"                  # ok / fail / skipped / partial
    error_code: str | None = None
    duration_ms: int | float | None = None
    tx_hex: str | None = None
    rx_hex: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra") or {}
        data.update(extra)          # 额外字段平铺，方便 grep
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _hex_preview(data: bytes | bytearray | memoryview | None, limit: int) -> str | None:
    if data is None:
        return None
    raw = bytes(data)
    if len(raw) <= limit:
        return raw.hex()
    return raw[:limit].hex() + f"...(+{len(raw) - limit}B)"


class StructuredLogger:
    """写 JSONL 日志，同时回显到控制台。

    Args:
        name: 模块名，写进每条日志的 ``module`` 字段。
        log_dir: 日志目录，默认 ``logs/``。
        console: 是否回显控制台。
        log_raw_serial: 是否记录 tx/rx 十六进制（生产模式应关闭）。
        raw_limit: 单条 tx/rx 保留的最大字节数。
        min_level: 低于该级别不落盘。
    """

    def __init__(
        self,
        name: str,
        *,
        log_dir: str | Path = "logs",
        console: bool = True,
        log_raw_serial: bool = True,
        raw_limit: int = DEFAULT_RAW_LIMIT,
        min_level: str = LogLevel.DEBUG,
    ) -> None:
        if raw_limit <= 0:
            raise ValueError(f"raw_limit 必须为正数: {raw_limit}")
        self.name = name
        self.log_dir = Path(log_dir)
        self.console = console
        self.log_raw_serial = log_raw_serial
        self.raw_limit = raw_limit
        self.min_level = min_level
        self._current_date: date | None = None
        self._current_path: Path | None = None
        self.events: list[LogEvent] = []   # 内存里保留一份，便于导出报告时按 feature 过滤

    # -- 文件 ------------------------------------------------------------- #
    def _file_for_today(self) -> Path:
        today = date.today()
        if self._current_path is None or self._current_date != today:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._current_date = today
            self._current_path = self.log_dir / f"debug_{today:%Y%m%d}.log"
        return self._current_path

    # -- 写入 ------------------------------------------------------------- #
    def log(
        self,
        level: str,
        action: str,
        *,
        feature_id: str | None = None,
        result: str = "ok",
        error_code: str | None = None,
        duration_ms: int | float | None = None,
        tx: bytes | bytearray | memoryview | None = None,
        rx: bytes | bytearray | memoryview | None = None,
        **extra: Any,
    ) -> LogEvent:
        """写一条日志。``tx``/``rx`` 是否落盘取决于 ``log_raw_serial``。"""
        if level not in LogLevel.ALL:
            raise ValueError(f"非法级别 {level!r}，允许: {LogLevel.ALL}")
        if error_code is not None and error_code not in ERROR_CODES:
            # 允许自定义码，但要求大写短横线风格，避免日志里出现随意字符串
            if not error_code.replace("_", "").isalnum() or error_code != error_code.upper():
                raise ValueError(f"error_code 需为大写下划线风格: {error_code!r}")

        record_raw = self.log_raw_serial
        event = LogEvent(
            timestamp=_now_iso(),
            level=level,
            module=self.name,
            feature_id=feature_id,
            action=action,
            result=result,
            error_code=error_code,
            duration_ms=(round(float(duration_ms), 3) if duration_ms is not None else None),
            tx_hex=_hex_preview(tx, self.raw_limit) if record_raw else None,
            rx_hex=_hex_preview(rx, self.raw_limit) if record_raw else None,
            extra=dict(extra),
        )

        self.events.append(event)
        if LogLevel.ALL.index(level) < LogLevel.ALL.index(self.min_level):
            return event

        line = event.to_json()
        path = self._file_for_today()
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")

        if self.console:
            print(self._console_line(event), file=sys.stderr if level == LogLevel.ERROR else sys.stdout)
        return event

    @staticmethod
    def _console_line(event: LogEvent) -> str:
        stamp = event.timestamp[11:23]
        parts = [f"{stamp} {event.level:<7} [{event.module}] {event.action}"]
        if event.feature_id:
            parts.append(f"feature={event.feature_id}")
        parts.append(f"result={event.result}")
        if event.error_code:
            parts.append(f"err={event.error_code}")
        if event.duration_ms is not None:
            parts.append(f"{event.duration_ms}ms")
        return " ".join(parts)

    # -- 便捷方法 --------------------------------------------------------- #
    def debug(self, action: str, **kw: Any) -> LogEvent:
        return self.log(LogLevel.DEBUG, action, **kw)

    def info(self, action: str, **kw: Any) -> LogEvent:
        return self.log(LogLevel.INFO, action, **kw)

    def warning(self, action: str, **kw: Any) -> LogEvent:
        return self.log(LogLevel.WARNING, action, **kw)

    def error(self, action: str, **kw: Any) -> LogEvent:
        return self.log(LogLevel.ERROR, action, **kw)

    # -- 计时 ------------------------------------------------------------- #
    @contextmanager
    def timed(self, action: str, **kw: Any) -> Iterator["_Timer"]:
        """用法::

            with logger.timed("upload", feature_id="gif_upload") as t:
                ...
                t.result = "fail"; t.error_code = "TIMEOUT"

        退出时自动写一条带 ``duration_ms`` 的日志（含异常路径）。
        """
        timer = _Timer()
        started = datetime.now()
        try:
            yield timer
        except Exception as exc:  # noqa: BLE001 - 记录后原样抛出
            timer.result = "fail"
            timer.error_code = timer.error_code or "UNKNOWN"
            timer.extra.setdefault("exception", type(exc).__name__)
            raise
        finally:
            elapsed = (datetime.now() - started).total_seconds() * 1000
            kw.setdefault("result", timer.result)
            if timer.error_code:
                kw.setdefault("error_code", timer.error_code)
            kw.update(timer.extra)
            self.log(timer.level, action, duration_ms=elapsed, **kw)

    # -- 过滤 ------------------------------------------------------------- #
    def events_for(self, feature_id: str) -> list[LogEvent]:
        return [e for e in self.events if e.feature_id == feature_id]

    def recent(self, *, feature_id: str | None = None, limit: int = 20) -> list[LogEvent]:
        pool = self.events if feature_id is None else self.events_for(feature_id)
        return pool[-limit:]


class _Timer:
    """``StructuredLogger.timed`` 的返回值。"""

    def __init__(self) -> None:
        self.result = "ok"
        self.error_code: str | None = None
        self.level = LogLevel.INFO
        self.extra: dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# 读回日志（调试面板的"按 feature_id 过滤"）
# --------------------------------------------------------------------------- #
def read_events(
    path: str | Path,
    *,
    feature_id: str | None = None,
    level: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """读取 JSONL 日志并按条件过滤。

    容错：单行损坏只跳过该行，不让整个日志读取失败——排查问题时最不需要的
    就是"日志读不出来"。
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"日志文件不存在: {file_path}")

    events: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if feature_id is not None and item.get("feature_id") != feature_id:
                continue
            if level is not None and item.get("level") != level:
                continue
            events.append(item)

    if limit is not None and limit >= 0:
        events = events[-limit:] if limit else []
    return events


def iter_log_files(log_dir: str | Path) -> list[Path]:
    """按日期升序列出所有日志文件。"""
    directory = Path(log_dir)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("debug_*.log"))


def utc_stamp() -> str:
    """UTC 时间戳，用于报告文件名。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
