# SPDX-License-Identifier: MIT
"""调试会话与调试报告测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulcan_lcd.diagnostics.debug_session import DebugSession, parse_session
from vulcan_lcd.diagnostics.logging_setup import StructuredLogger
from vulcan_lcd.diagnostics.report import (
    ReportContext,
    build_report,
    collect_environment,
    harness_instruction,
    render_markdown,
    write_reports,
)
from vulcan_lcd.features.registry import FeatureRegistry

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "feature_registry.json"
CONFIG = REPO / "config" / "settings.default.json"


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def make_context(tmp_path: Path, **kwargs: object) -> ReportContext:
    logger = StructuredLogger("report.test", log_dir=tmp_path / "logs", console=False)
    logger.error("upload", feature_id="dual_screen_layout", result="fail", error_code="TIMEOUT")
    base = {
        "registry": FeatureRegistry.load(SHIPPED),
        "config": load_config(),
        "session": DebugSession(debug=True, dry_run=True),
        "logger": logger,
        "ports": ("COM1", "COM4"),
        "handshake": {"matched": True, "port": "COM4"},
        "service_name": "iGameCenterService",
        "service_status": "Running",
    }
    base.update(kwargs)
    return ReportContext(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
def test_parse_defaults_are_production() -> None:
    session = parse_session([])
    assert session.debug is False
    assert session.dry_run is False
    assert session.feature_filter is None
    assert session.is_production is True
    assert session.allows_manual_hex is False


def test_parse_debug_and_dry_run() -> None:
    session = parse_session(["--debug", "--dry-run", "--feature=dual_screen_layout"])
    assert session.debug is True
    assert session.dry_run is True
    assert session.feature_filter == "dual_screen_layout"
    assert session.is_production is False
    assert session.allows_manual_hex is True


def test_feature_filter_matching() -> None:
    session = parse_session(["--feature=dual_screen_layout"])
    assert session.matches("dual_screen_layout") is True
    assert session.matches("gif_upload") is False


def test_no_filter_matches_everything() -> None:
    assert parse_session([]).matches("anything") is True


def test_with_dry_run_is_immutable() -> None:
    original = parse_session([])
    updated = original.with_dry_run()
    assert original.dry_run is False
    assert updated.dry_run is True


# --------------------------------------------------------------------------- #
# 报告内容
# --------------------------------------------------------------------------- #
def test_environment_has_required_keys() -> None:
    env = collect_environment()
    for key in (
        "python_version",
        "executable",
        "venv_prefix",
        "venv_active",
        "is_admin",
        "platform",
    ):
        assert key in env


def test_report_structure(tmp_path: Path) -> None:
    report = build_report(make_context(tmp_path))
    for key in ("generated_at", "environment", "session", "device", "registry", "unmet_gates", "attention"):
        assert key in report
    assert report["device"]["service_name"] == "iGameCenterService"
    assert report["device"]["ports"] == ["COM1", "COM4"]


def test_report_lists_experimental_features_as_attention(tmp_path: Path) -> None:
    report = build_report(make_context(tmp_path))
    ids = {item["feature_id"] for item in report["attention"]}
    assert "dual_screen_layout" in ids
    assert "checksum_16le" not in ids


def test_attention_entry_has_repro_steps_and_logs(tmp_path: Path) -> None:
    report = build_report(make_context(tmp_path))
    gif = next(i for i in report["attention"] if i["feature_id"] == "dual_screen_layout")
    assert gif["repro_steps"]
    assert any("dual_screen_layout" in step for step in gif["repro_steps"])
    assert gif["recent_logs"]
    assert gif["recent_logs"][-1]["error_code"] == "TIMEOUT"


def test_unmet_gates_listed(tmp_path: Path) -> None:
    report = build_report(make_context(tmp_path))
    labels = {g["label"] for g in report["unmet_gates"]}
    # 监控帧格式已真机验证，现在唯一未满足的是双屏分区
    assert "双屏分区指令" in labels
    assert "握手请求/应答字节" not in labels


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def test_markdown_has_all_sections(tmp_path: Path) -> None:
    md = render_markdown(build_report(make_context(tmp_path)))
    for heading in (
        "# 火神智屏工具 · 调试报告",
        "## 1. 运行环境",
        "## 2. 设备与服务",
        "## 3. 功能注册表快照",
        "## 4. 未就绪功能与失败详情",
        "## 5. 待验证协议项",
        "## 6. 给 Harness 的修改指令模板",
    ):
        assert heading in md


def test_markdown_marks_missing_venv(tmp_path: Path) -> None:
    md = render_markdown(build_report(make_context(tmp_path)))
    assert "虚拟环境" in md


def test_markdown_includes_harness_template_per_feature(tmp_path: Path) -> None:
    md = render_markdown(build_report(make_context(tmp_path)))
    assert "请仅修改 feature_id=dual_screen_layout" in md
    assert "不要改动其他 verified 功能" in md
    assert "更新 feature_registry.json 和 CHANGELOG.md" in md


def test_harness_instruction_contains_required_clauses() -> None:
    text = harness_instruction("dual_screen_layout", "分包未知", "upload result=fail")
    assert "feature_id=dual_screen_layout" in text
    assert "失败原因=分包未知" in text
    assert "相关日志=upload result=fail" in text
    assert "第 3 节安全约束" in text
    assert "第 9 节日志/注册表机制" in text


def test_harness_instruction_handles_missing_values() -> None:
    text = harness_instruction("x", "", "")
    assert "未提供" in text
    assert "（无相关日志）" in text


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def test_write_reports_creates_both_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    md_path, json_path = write_reports(build_report(make_context(tmp_path)), out)

    assert md_path.is_file() and md_path.name == "debug_report.md"
    assert json_path.is_file() and json_path.name == "debug_report.json"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["device"]["service_name"] == "iGameCenterService"
    assert "给 Harness" in md_path.read_text(encoding="utf-8")


def test_write_reports_creates_directory(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deep"
    md_path, _ = write_reports(build_report(make_context(tmp_path)), out)
    assert md_path.is_file()


def test_report_without_logger_still_works(tmp_path: Path) -> None:
    report = build_report(make_context(tmp_path, logger=None))
    gif = next(i for i in report["attention"] if i["feature_id"] == "dual_screen_layout")
    assert gif["recent_logs"] == []
    assert render_markdown(report)
