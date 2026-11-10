# SPDX-License-Identifier: MIT
"""功能注册表测试：状态机、校验、原子落盘。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulcan_lcd.features.registry import (
    SCHEMA_VERSION,
    FeatureRecord,
    FeatureRegistry,
    FeatureStatus,
    RegistryError,
)

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "feature_registry.json"


def make_record(feature_id: str = "demo", **kwargs: object) -> FeatureRecord:
    base = {
        "feature_id": feature_id,
        "name": "演示功能",
        "module": "src/demo.py",
        "status": FeatureStatus.EXPERIMENTAL,
    }
    base.update(kwargs)
    return FeatureRecord(**base)  # type: ignore[arg-type]


def make_registry(*records: FeatureRecord) -> FeatureRegistry:
    return FeatureRegistry({r.feature_id: r for r in records})


# --------------------------------------------------------------------------- #
# 载入真实注册表
# --------------------------------------------------------------------------- #
def test_shipped_registry_loads_and_is_self_consistent() -> None:
    registry = FeatureRegistry.load(SHIPPED)
    assert len(registry) >= 12
    assert registry.problems == []


def test_shipped_registry_has_required_feature_ids() -> None:
    required = {
        "gif_upload",
        "dual_screen_layout",
        "playlist_rotation",
        "gpu_monitor",
        "dual_screen_layout",
        "dual_screen_layout",
        "auto_port_scan",
        "service_control",
        "checksum_16le",
        "ack_wait_optional",
        "venv_bootstrap",
        "pyinstaller_packaging",
    }
    registry = FeatureRegistry.load(SHIPPED)
    assert required.issubset(set(registry.ids()))


def test_shipped_registry_verified_features() -> None:
    registry = FeatureRegistry.load(SHIPPED)
    verified = set(registry.verified_ids())
    assert {"checksum_16le", "venv_bootstrap", "title_display"} <= verified


def test_shipped_registry_blocks_upload_features() -> None:
    """尚未真机验证的功能必须保持未验证状态（上传类功能尤其如此）。"""
    registry = FeatureRegistry.load(SHIPPED)
    for fid in ("dual_screen_layout",):
        assert registry.require(fid).status is not FeatureStatus.VERIFIED


def test_playlist_rotation_is_verified() -> None:
    """轮播已于 2026-11-06 真机验证（两段 GIF 循环切换 7 次）。"""
    registry = FeatureRegistry.load(SHIPPED)
    assert registry.require("playlist_rotation").status is FeatureStatus.VERIFIED


# --------------------------------------------------------------------------- #
# 载入期校验
# --------------------------------------------------------------------------- #
def write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "schema_version": SCHEMA_VERSION,
            "features": [{"feature_id": "x", "name": "x", "module": "x", "status": "maybe"}],
        },
    )
    with pytest.raises(RegistryError, match="非法状态"):
        FeatureRegistry.load(path)


def test_wrong_schema_version_is_rejected(tmp_path: Path) -> None:
    path = write_registry(tmp_path, {"schema_version": 99, "features": []})
    with pytest.raises(RegistryError, match="schema_version"):
        FeatureRegistry.load(path)


def test_empty_features_is_rejected(tmp_path: Path) -> None:
    path = write_registry(tmp_path, {"schema_version": SCHEMA_VERSION, "features": []})
    with pytest.raises(RegistryError, match="非空数组"):
        FeatureRegistry.load(path)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {"schema_version": SCHEMA_VERSION, "features": [{"feature_id": "x", "status": "verified"}]},
    )
    with pytest.raises(RegistryError, match="缺少必填字段"):
        FeatureRegistry.load(path)


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    item = {"feature_id": "dup", "name": "x", "module": "x", "status": "verified"}
    path = write_registry(tmp_path, {"schema_version": SCHEMA_VERSION, "features": [item, item]})
    with pytest.raises(RegistryError, match="重复"):
        FeatureRegistry.load(path)


def test_dependency_on_missing_feature_is_rejected(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "schema_version": SCHEMA_VERSION,
            "features": [
                {
                    "feature_id": "a",
                    "name": "A",
                    "module": "a",
                    "status": "experimental",
                    "depends_on": ["ghost"],
                }
            ],
        },
    )
    with pytest.raises(RegistryError, match="依赖不存在"):
        FeatureRegistry.load(path)


def test_self_dependency_is_rejected(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "schema_version": SCHEMA_VERSION,
            "features": [
                {
                    "feature_id": "a",
                    "name": "A",
                    "module": "a",
                    "status": "experimental",
                    "depends_on": ["a"],
                }
            ],
        },
    )
    with pytest.raises(RegistryError, match="依赖自己"):
        FeatureRegistry.load(path)


# --------------------------------------------------------------------------- #
# 状态机
# --------------------------------------------------------------------------- #
def test_verified_requires_protocol_verified() -> None:
    registry = make_registry(make_record(protocol_verified=False))
    with pytest.raises(RegistryError, match="协议尚未验证"):
        registry.set_status("demo", FeatureStatus.VERIFIED)


def test_verified_allowed_when_protocol_verified() -> None:
    registry = make_registry(make_record(protocol_verified=True))
    record = registry.set_status("demo", FeatureStatus.VERIFIED)
    assert record.status is FeatureStatus.VERIFIED


def test_verified_without_protocol_requirement_is_allowed() -> None:
    registry = make_registry(make_record(protocol_verified=False, requires_protocol=False))
    record = registry.set_status("demo", FeatureStatus.VERIFIED)
    assert record.status is FeatureStatus.VERIFIED


def test_failed_verification_auto_disables() -> None:
    registry = make_registry(make_record(protocol_verified=True, status=FeatureStatus.VERIFIED, last_result="pass"))
    record = registry.record_result("demo", passed=False, error_summary="校验失败")
    assert record.status is FeatureStatus.DISABLED
    assert record.last_result == "fail"
    assert record.suggested_action == "disable"
    assert record.error_summary == "校验失败"


def test_successful_verification_clears_error() -> None:
    registry = make_registry(make_record(protocol_verified=True, status=FeatureStatus.DISABLED, last_result="fail"))
    record = registry.record_result("demo", passed=True)
    assert record.last_result == "pass"
    assert record.error_summary is None
    assert record.suggested_action == "none"


def test_unknown_feature_raises() -> None:
    registry = make_registry(make_record())
    with pytest.raises(RegistryError, match="未知的 feature_id"):
        registry.set_status("ghost", FeatureStatus.DISABLED)


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def test_validate_flags_verified_without_passing_test() -> None:
    record = make_record(protocol_verified=True, status=FeatureStatus.VERIFIED, last_result="not_run")
    registry = make_registry(record)
    assert any("last_result" in p for p in registry.problems)


def test_validate_flags_experimental_with_passing_test() -> None:
    record = make_record(protocol_verified=True, status=FeatureStatus.EXPERIMENTAL, last_result="pass")
    registry = make_registry(record)
    assert any("状态说谎" in p for p in registry.problems)


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def test_save_and_reload_roundtrip(tmp_path: Path) -> None:
    registry = make_registry(make_record(protocol_verified=True))
    path = tmp_path / "out.json"
    registry.save(path)

    reloaded = FeatureRegistry.load(path)
    assert reloaded.ids() == ["demo"]
    assert reloaded.require("demo").status is FeatureStatus.EXPERIMENTAL


def test_save_is_valid_json_and_touches_timestamp(tmp_path: Path) -> None:
    registry = make_registry(make_record(protocol_verified=True))
    path = tmp_path / "out.json"
    registry.save(path)
    first = json.loads(path.read_text(encoding="utf-8"))["updated_at"]
    registry.save(path)
    second = json.loads(path.read_text(encoding="utf-8"))["updated_at"]
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION
    assert first and second


def test_save_leaves_no_temp_files(tmp_path: Path) -> None:
    registry = make_registry(make_record(protocol_verified=True))
    registry.save(tmp_path / "out.json")
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_snapshot_has_counts(tmp_path: Path) -> None:
    registry = make_registry(
        make_record("a", protocol_verified=True, status=FeatureStatus.VERIFIED, last_result="pass"),
        make_record("b"),
    )
    snap = registry.snapshot()
    assert snap["counts"]["verified"] == 1
    assert snap["counts"]["experimental"] == 1
    assert len(snap["features"]) == 2


def test_removed_features_are_not_loaded() -> None:
    registry = make_registry(make_record(status=FeatureStatus.REMOVED))
    assert registry.require("demo").status.is_loaded is False
    assert registry.blocked_ids() == ["demo"]
