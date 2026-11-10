# SPDX-License-Identifier: MIT
"""应用装配测试（不加载 Qt）。

窗口本身用无头冒烟脚本验证；这里覆盖那些"打开就崩"的高风险逻辑：
配置合并、注册表缺失、闸门与 UI 提示文案。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulcan_lcd.app import AppError, AppContext, build_context, load_config
from vulcan_lcd.diagnostics.debug_session import DebugSession

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def test_load_default_config() -> None:
    config, problems = load_config(REPO)
    assert problems == []
    assert config["protocol"]["serial"]["baudrate"] == 115200


def test_user_config_overrides_only_given_keys(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.default.json").write_text(
        json.dumps({"a": {"x": 1, "y": 2}, "b": 3}), encoding="utf-8"
    )
    (tmp_path / "config" / "settings.user.json").write_text(
        json.dumps({"a": {"y": 99}}), encoding="utf-8"
    )
    config, problems = load_config(tmp_path)
    assert problems == []
    assert config["a"] == {"x": 1, "y": 99}
    assert config["b"] == 3


def test_broken_user_config_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.default.json").write_text(
        json.dumps({"a": 1}), encoding="utf-8"
    )
    (tmp_path / "config" / "settings.user.json").write_text("{ not json", encoding="utf-8")

    config, problems = load_config(tmp_path)
    assert config == {"a": 1}
    assert len(problems) == 1
    assert "settings.user.json" in problems[0]


def test_missing_default_config_raises(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="默认配置缺失"):
        load_config(tmp_path)


# --------------------------------------------------------------------------- #
# 上下文
# --------------------------------------------------------------------------- #
def test_build_context_in_production_mode() -> None:
    ctx = build_context(DebugSession(), console_log=False)
    assert isinstance(ctx, AppContext)
    assert ctx.gate.debug_mode is False
    assert ctx.feature_allowed("title_display") is True
    assert ctx.feature_allowed("dual_screen_layout") is False


def test_build_context_in_debug_mode_does_not_unlock_features() -> None:
    ctx = build_context(DebugSession(debug=True), console_log=False)
    assert ctx.gate.debug_mode is True
    assert ctx.feature_allowed("dual_screen_layout") is False
    assert ctx.session.allows_manual_hex is True


def test_blocked_reason_explains_why() -> None:
    ctx = build_context(DebugSession(), console_log=False)
    reason = ctx.blocked_reason("dual_screen_layout")
    assert "尚未验证" in reason or "未验证" in reason


def test_blocked_reason_empty_for_allowed_feature() -> None:
    ctx = build_context(DebugSession(), console_log=False)
    assert ctx.blocked_reason("title_display") == ""


def test_blocked_reason_for_unknown_feature() -> None:
    ctx = build_context(DebugSession(), console_log=False)
    assert ctx.blocked_reason("no_such_feature") == "未知功能"


def test_service_name_from_config() -> None:
    ctx = build_context(DebugSession(), console_log=False)
    assert ctx.service_name == "iGameCenterService"


def test_missing_registry_raises(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.default.json").write_text(
        json.dumps({"debug": {"export_dir": "logs"}}), encoding="utf-8"
    )
    with pytest.raises(AppError, match="注册表载入失败"):
        build_context(DebugSession(), root=tmp_path, console_log=False)
