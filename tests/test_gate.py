# SPDX-License-Identifier: MIT
"""生产闸门测试。

核心断言只有一句：**未 verified 的功能，任何模式下都不允许写串口。**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulcan_lcd.features.gate import (
    CONFIG_GATES,
    FeatureBlockedError,
    FeatureGate,
    Permission,
    audit,
    evaluate_config,
)
from vulcan_lcd.features.registry import FeatureRecord, FeatureRegistry, FeatureStatus

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "settings.default.json"


def record(feature_id: str, status: FeatureStatus, **kwargs: object) -> FeatureRecord:
    base = {
        "feature_id": feature_id,
        "name": feature_id,
        "module": "src/x.py",
        "status": status,
    }
    base.update(kwargs)
    return FeatureRecord(**base)  # type: ignore[arg-type]


def registry_of(*records: FeatureRecord) -> FeatureRegistry:
    return FeatureRegistry({r.feature_id: r for r in records})


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 权限矩阵
# --------------------------------------------------------------------------- #
def test_verified_can_write() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)))
    assert gate.permission("a") is Permission.WRITE
    assert gate.can_write("a") is True


def test_experimental_is_read_only_even_in_debug() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.EXPERIMENTAL)), debug_mode=True)
    assert gate.permission("a") is Permission.READ_ONLY
    assert gate.can_write("a") is False


def test_disabled_is_blocked() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.DISABLED)))
    assert gate.permission("a") is Permission.BLOCKED


def test_removed_is_blocked() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.REMOVED)))
    assert gate.permission("a") is Permission.BLOCKED


def test_unknown_feature_fails_closed() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)))
    assert gate.permission("does-not-exist") is Permission.BLOCKED


def test_dependency_not_verified_degrades_to_read_only() -> None:
    gate = FeatureGate(
        registry_of(
            record("parent", FeatureStatus.VERIFIED, depends_on=("child",)),
            record("child", FeatureStatus.EXPERIMENTAL),
        )
    )
    assert gate.permission("parent") is Permission.READ_ONLY


def test_dependency_verified_keeps_write() -> None:
    gate = FeatureGate(
        registry_of(
            record("parent", FeatureStatus.VERIFIED, depends_on=("child",)),
            record("child", FeatureStatus.VERIFIED),
        )
    )
    assert gate.permission("parent") is Permission.WRITE


def test_dependency_cycle_does_not_hang() -> None:
    gate = FeatureGate(
        registry_of(
            record("a", FeatureStatus.VERIFIED, depends_on=("b",)),
            record("b", FeatureStatus.VERIFIED, depends_on=("a",)),
        )
    )
    assert gate.permission("a") is Permission.BLOCKED


# --------------------------------------------------------------------------- #
# 写入口
# --------------------------------------------------------------------------- #
def test_require_write_passes_for_verified() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)))
    gate.require_write("a")  # 不抛异常即可


def test_require_write_raises_for_experimental() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.EXPERIMENTAL)))
    with pytest.raises(FeatureBlockedError) as excinfo:
        gate.require_write("a")
    assert excinfo.value.error_code == "FEATURE_BLOCKED"
    assert excinfo.value.permission is Permission.READ_ONLY
    assert "拒绝向串口写入" in str(excinfo.value)


def test_require_write_includes_error_summary() -> None:
    gate = FeatureGate(
        registry_of(record("a", FeatureStatus.DISABLED, error_summary="校验失败 3 次"))
    )
    with pytest.raises(FeatureBlockedError, match="校验失败 3 次"):
        gate.require_write("a")


def test_writable_lists_only_verified() -> None:
    gate = FeatureGate(
        registry_of(
            record("a", FeatureStatus.VERIFIED),
            record("b", FeatureStatus.EXPERIMENTAL),
            record("c", FeatureStatus.DISABLED),
        )
    )
    assert gate.writable() == ["a"]


# --------------------------------------------------------------------------- #
# 配置闸门
# --------------------------------------------------------------------------- #
def test_gate_labels_are_unique() -> None:
    labels = [g.label for g in CONFIG_GATES]
    assert len(labels) == len(set(labels))


def test_evaluate_shipped_config() -> None:
    results = evaluate_config(load_config())
    by_label = {r.label: r for r in results}
    assert by_label["握手请求/应答字节"].ready is True
    assert by_label["官方服务名"].ready is True
    assert by_label["分包大小"].ready is True
    assert by_label["帧间延时"].ready is True
    assert by_label["图片帧校验范围"].ready is True
    assert by_label["像素格式"].ready is True  # 静态图/监控帧已真机验证


def test_evaluate_marks_everything_unverified_on_empty_config() -> None:
    results = evaluate_config({})
    assert all(r.ready is False for r in results)


def test_broken_config_does_not_raise() -> None:
    results = evaluate_config({"protocol": {"checksum": "not-a-dict"}})
    assert all(r.ready is False for r in results)


# --------------------------------------------------------------------------- #
# 一致性审计
# --------------------------------------------------------------------------- #
def test_audit_detects_registry_claiming_verified_but_config_says_no() -> None:
    cfg = load_config()
    cfg["protocol"]["handshake_verified"] = False
    registry = registry_of(
        record("auto_port_scan", FeatureStatus.EXPERIMENTAL, protocol_verified=True)
    )
    findings = audit(registry, cfg)
    assert any("protocol_verified=true" in f for f in findings)


def test_audit_detects_config_ready_but_registry_stale() -> None:
    registry = registry_of(
        record("auto_port_scan", FeatureStatus.EXPERIMENTAL, protocol_verified=False)
    )
    findings = audit(registry, load_config())
    assert any("忘了更新注册表" in f for f in findings)


def test_audit_is_clean_for_shipped_registry() -> None:
    registry = FeatureRegistry.load(REPO / "feature_registry.json")
    findings = audit(registry, load_config())
    assert findings == []


# --------------------------------------------------------------------------- #
# 人工原始发送（受控例外）
# --------------------------------------------------------------------------- #
def test_manual_raw_requires_debug_mode() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)))
    with pytest.raises(FeatureBlockedError, match="调试模式"):
        gate.require_manual_raw(confirmed=True, config=load_config())


def test_manual_raw_requires_confirmation() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)), debug_mode=True)
    with pytest.raises(FeatureBlockedError, match="二次确认"):
        gate.require_manual_raw(confirmed=False, config=load_config())


def test_manual_raw_allowed_with_debug_and_confirmation() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)), debug_mode=True)
    gate.require_manual_raw(confirmed=True, config=load_config())


def test_manual_raw_can_disable_confirmation_via_config() -> None:
    cfg = load_config()
    cfg["debug"]["require_confirm_for_manual_hex"] = False
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)), debug_mode=True)
    gate.require_manual_raw(confirmed=False, config=cfg)


def test_manual_raw_allowed_helper_is_non_raising() -> None:
    gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)))
    assert gate.manual_raw_allowed(confirmed=True, config=load_config()) is False
    debug_gate = FeatureGate(registry_of(record("a", FeatureStatus.VERIFIED)), debug_mode=True)
    assert debug_gate.manual_raw_allowed(confirmed=True, config=load_config()) is True


def test_manual_raw_does_not_unlock_experimental_features() -> None:
    """人工通道是独立口子，绝不能顺带把 experimental 功能变成可写。"""
    gate = FeatureGate(registry_of(record("a", FeatureStatus.EXPERIMENTAL)), debug_mode=True)
    gate.require_manual_raw(confirmed=True, config=load_config())
    assert gate.permission("a") is Permission.READ_ONLY


def test_audit_includes_registry_problems() -> None:
    registry = registry_of(
        record(
            "a",
            FeatureStatus.VERIFIED,
            protocol_verified=True,
            last_result="not_run",
        )
    )
    findings = audit(registry, load_config())
    assert any("last_result" in f for f in findings)
