# SPDX-License-Identifier: MIT
"""结构化日志测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulcan_lcd.diagnostics.logging_setup import (
    LogLevel,
    StructuredLogger,
    read_events,
)


def make_logger(tmp_path: Path, **kw: object) -> StructuredLogger:
    return StructuredLogger("test.mod", log_dir=tmp_path, console=False, **kw)  # type: ignore[arg-type]


def read_lines(tmp_path: Path) -> list[dict]:
    files = sorted(tmp_path.glob("debug_*.log"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]


# --------------------------------------------------------------------------- #
# 字段完整性
# --------------------------------------------------------------------------- #
def test_required_fields_present(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("handshake", feature_id="auto_port_scan", tx=b"\x5a\x9f\xa9", rx=b"\x00\x01")

    entry = read_lines(tmp_path)[0]
    for key in (
        "timestamp",
        "level",
        "module",
        "feature_id",
        "action",
        "result",
        "error_code",
        "duration_ms",
        "tx_hex",
        "rx_hex",
    ):
        assert key in entry, f"缺少字段 {key}"
    assert entry["level"] == LogLevel.INFO
    assert entry["module"] == "test.mod"
    assert entry["feature_id"] == "auto_port_scan"
    assert entry["result"] == "ok"
    assert entry["tx_hex"] == "5a9fa9"


def test_timestamp_is_timezone_aware(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("x")
    stamp = read_lines(tmp_path)[0]["timestamp"]
    assert "T" in stamp
    assert stamp.endswith(("+08:00", "+00:00", "Z")) or "+" in stamp[10:]


def test_duration_is_recorded(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("slow", duration_ms=12.3456)
    assert read_lines(tmp_path)[0]["duration_ms"] == pytest.approx(12.346)


# --------------------------------------------------------------------------- #
# 截断与生产模式
# --------------------------------------------------------------------------- #
def test_tx_rx_are_truncated(tmp_path: Path) -> None:
    logger = make_logger(tmp_path, raw_limit=8)
    logger.info("big", tx=bytes(range(32)))
    entry = read_lines(tmp_path)[0]
    assert entry["tx_hex"].endswith("(+24B)")
    assert entry["tx_hex"].startswith("0001020304050607")


def test_raw_serial_can_be_disabled(tmp_path: Path) -> None:
    logger = make_logger(tmp_path, log_raw_serial=False)
    logger.info("quiet", tx=b"\x01\x02", rx=b"\x03")
    entry = read_lines(tmp_path)[0]
    assert entry["tx_hex"] is None
    assert entry["rx_hex"] is None


def test_zero_raw_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="raw_limit"):
        make_logger(tmp_path, raw_limit=0)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def test_invalid_level_is_rejected(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    with pytest.raises(ValueError, match="非法级别"):
        logger.log("TRACE", "x")


def test_invalid_error_code_is_rejected(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    with pytest.raises(ValueError, match="error_code"):
        logger.log(LogLevel.ERROR, "x", error_code="bad code!")


def test_valid_error_code_is_accepted(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.error("x", error_code="CHECKSUM_MISMATCH", result="fail")
    assert read_lines(tmp_path)[0]["error_code"] == "CHECKSUM_MISMATCH"


# --------------------------------------------------------------------------- #
# 计时上下文
# --------------------------------------------------------------------------- #
def test_timed_records_success(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    with logger.timed("upload", feature_id="gif_upload"):
        pass
    entry = read_lines(tmp_path)[0]
    assert entry["result"] == "ok"
    assert entry["duration_ms"] is not None


def test_timed_records_failure_and_reraises(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    with pytest.raises(ValueError):
        with logger.timed("upload", feature_id="gif_upload") as timer:
            timer.error_code = "TIMEOUT"
            raise ValueError("boom")
    entry = read_lines(tmp_path)[0]
    assert entry["result"] == "fail"
    assert entry["error_code"] == "TIMEOUT"
    assert entry["exception"] == "ValueError"


# --------------------------------------------------------------------------- #
# 读回与过滤
# --------------------------------------------------------------------------- #
def test_read_events_filters_by_feature(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("a", feature_id="gif_upload")
    logger.info("b", feature_id="cpu_monitor")
    logger.info("c", feature_id="gif_upload")

    path = next(tmp_path.glob("debug_*.log"))
    events = read_events(path, feature_id="gif_upload")
    assert [e["action"] for e in events] == ["a", "c"]


def test_read_events_filters_by_level(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("a")
    logger.error("b")
    path = next(tmp_path.glob("debug_*.log"))
    assert [e["action"] for e in read_events(path, level=LogLevel.ERROR)] == ["b"]


def test_read_events_respects_limit(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    for i in range(10):
        logger.info(f"e{i}")
    path = next(tmp_path.glob("debug_*.log"))
    events = read_events(path, limit=3)
    assert [e["action"] for e in events] == ["e7", "e8", "e9"]


def test_read_events_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "debug_20260101.log"
    path.write_text('{"action":"ok"}\nnot json\n{"action":"ok2"}\n', encoding="utf-8")
    events = read_events(path)
    assert [e["action"] for e in events] == ["ok", "ok2"]


def test_read_events_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_events(tmp_path / "nope.log")


# --------------------------------------------------------------------------- #
# 内存缓冲
# --------------------------------------------------------------------------- #
def test_events_are_queryable_in_memory(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("a", feature_id="gif_upload")
    logger.info("b", feature_id="cpu_monitor")
    assert [e.action for e in logger.events_for("gif_upload")] == ["a"]
    assert [e.action for e in logger.recent(limit=1)] == ["b"]


def test_daily_file_name_format(tmp_path: Path) -> None:
    logger = make_logger(tmp_path)
    logger.info("x")
    files = list(tmp_path.glob("debug_*.log"))
    assert len(files) == 1
    assert files[0].name.startswith("debug_")
    assert len(files[0].stem) == len("debug_YYYYMMDD")
