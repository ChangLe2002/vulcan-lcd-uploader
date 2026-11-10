# SPDX-License-Identifier: MIT
"""功能注册表：``feature_registry.json`` 的读写、校验与状态机。

设计原则
--------
* **文件是唯一事实来源**，代码里的硬编码状态一律不认；
* 状态只有四种：``verified`` / ``experimental`` / ``disabled`` / ``removed``；
* 任何状态变更都必须能被审计（谁、何时、因为什么失败）；
* 写入用"临时文件 + 原子替换"，避免半截 JSON 把注册表写坏；
* 记录对象是 frozen dataclass，改动走 :meth:`FeatureRegistry.set_status`，
  这样"偷偷改一个字段"在类型层面就写不出来。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterator

__all__ = [
    "FeatureStatus",
    "RegistryError",
    "FeatureRecord",
    "FeatureRegistry",
    "SCHEMA_VERSION",
]

SCHEMA_VERSION = 1


class FeatureStatus(str, Enum):
    """功能状态。四种，别再加第五种。"""

    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"
    REMOVED = "removed"

    @property
    def may_write(self) -> bool:
        """只有 verified 允许向串口写数据。"""
        return self is FeatureStatus.VERIFIED

    @property
    def is_loaded(self) -> bool:
        """removed 的功能不加载代码。"""
        return self is not FeatureStatus.REMOVED


class RegistryError(Exception):
    """注册表不合法。"""

    error_code = "REGISTRY_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# 单条记录
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FeatureRecord:
    """一个功能的状态快照。"""

    feature_id: str
    name: str
    module: str
    status: FeatureStatus
    protocol_verified: bool = False
    requires_protocol: bool = True
    depends_on: tuple[str, ...] = ()
    last_test_at: str | None = None
    last_result: str = "not_run"          # pass / fail / partial / not_run / skipped
    error_summary: str | None = None
    suggested_action: str = "none"        # none / disable / needs_capture / implement_module / fix
    test_env: dict[str, object] = field(default_factory=dict)
    notes: str = ""

    # -- 序列化 ---------------------------------------------------------- #
    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "module": self.module,
            "status": self.status.value,
            "protocol_verified": self.protocol_verified,
            "requires_protocol": self.requires_protocol,
            "depends_on": list(self.depends_on),
            "last_test_at": self.last_test_at,
            "last_result": self.last_result,
            "error_summary": self.error_summary,
            "suggested_action": self.suggested_action,
            "test_env": self.test_env,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object], *, where: str = "") -> "FeatureRecord":
        if not isinstance(data, dict):
            raise RegistryError(f"{where}: 条目必须是对象")
        for key in ("feature_id", "name", "module", "status"):
            if key not in data:
                raise RegistryError(f"{where}: 缺少必填字段 {key!r}")

        raw_status = data["status"]
        try:
            status = FeatureStatus(str(raw_status))
        except ValueError as exc:
            raise RegistryError(
                f"{where}: 非法状态 {raw_status!r}，只允许 "
                f"{[s.value for s in FeatureStatus]}"
            ) from exc

        feature_id = str(data["feature_id"])
        depends = data.get("depends_on") or []
        if not isinstance(depends, (list, tuple)):
            raise RegistryError(f"{where}: depends_on 必须是数组")
        if feature_id in depends:
            raise RegistryError(f"{where}: 功能不能依赖自己")

        test_env = data.get("test_env") or {}
        if not isinstance(test_env, dict):
            raise RegistryError(f"{where}: test_env 必须是对象")

        return cls(
            feature_id=feature_id,
            name=str(data["name"]),
            module=str(data["module"]),
            status=status,
            protocol_verified=bool(data.get("protocol_verified", False)),
            requires_protocol=bool(data.get("requires_protocol", True)),
            depends_on=tuple(str(x) for x in depends),
            last_test_at=(str(data["last_test_at"]) if data.get("last_test_at") else None),
            last_result=str(data.get("last_result", "not_run")),
            error_summary=(str(data["error_summary"]) if data.get("error_summary") else None),
            suggested_action=str(data.get("suggested_action", "none")),
            test_env=dict(test_env),
            notes=str(data.get("notes", "")),
        )


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
class FeatureRegistry:
    """``feature_registry.json`` 的内存模型。"""

    def __init__(self, records: dict[str, FeatureRecord], *, updated_at: str = "") -> None:
        self._records = dict(records)
        self.updated_at = updated_at or _now_iso()
        self.problems = self.validate()

    # -- 载入 / 保存 ------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | Path) -> "FeatureRegistry":
        file_path = Path(path)
        if not file_path.is_file():
            raise RegistryError(f"注册表不存在: {file_path}")
        try:
            data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"注册表 JSON 解析失败: {exc}") from exc

        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise RegistryError(
                f"schema_version 不支持: {version!r}（期望 {SCHEMA_VERSION}）"
            )

        items = data.get("features")
        if not isinstance(items, list) or not items:
            raise RegistryError("features 必须是非空数组")

        records: dict[str, FeatureRecord] = {}
        for index, item in enumerate(items):
            record = FeatureRecord.from_dict(item, where=f"features[{index}]")
            if record.feature_id in records:
                raise RegistryError(f"feature_id 重复: {record.feature_id}")
            records[record.feature_id] = record

        # 依赖必须指向存在的 id
        for record in records.values():
            for dep in record.depends_on:
                if dep not in records:
                    raise RegistryError(
                        f"{record.feature_id} 依赖不存在的功能: {dep}"
                    )

        return cls(records, updated_at=str(data.get("updated_at") or ""))

    def save(self, path: str | Path, *, touch: bool = True) -> None:
        """原子写入。``touch=True`` 时刷新 updated_at。"""
        file_path = Path(path)
        if touch:
            self.updated_at = _now_iso()

        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": self.updated_at,
            "_comment": (
                "功能状态的唯一事实来源。生产模式只允许 status=verified 的功能向串口写数据。"
                "任何状态变更必须同步 CHANGELOG.md。status 只能是 verified / experimental / "
                "disabled / removed。"
            ),
            "features": [r.to_dict() for r in self._records.values()],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        # 先写临时文件再替换，避免中途崩溃留下半截 JSON
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".registry-", suffix=".tmp", dir=str(file_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp_name, file_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # -- 查询 -------------------------------------------------------------- #
    def __iter__(self) -> Iterator[FeatureRecord]:
        return iter(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    def get(self, feature_id: str) -> FeatureRecord | None:
        return self._records.get(feature_id)

    def require(self, feature_id: str) -> FeatureRecord:
        record = self._records.get(feature_id)
        if record is None:
            raise RegistryError(f"未知的 feature_id: {feature_id}")
        return record

    def ids(self) -> list[str]:
        return list(self._records)

    def by_status(self, status: FeatureStatus) -> list[FeatureRecord]:
        return [r for r in self._records.values() if r.status is status]

    def verified_ids(self) -> list[str]:
        return [r.feature_id for r in self.by_status(FeatureStatus.VERIFIED)]

    def blocked_ids(self) -> list[str]:
        return [
            r.feature_id
            for r in self._records.values()
            if not r.status.may_write
        ]

    # -- 变更 -------------------------------------------------------------- #
    def set_status(
        self,
        feature_id: str,
        status: FeatureStatus,
        *,
        error_summary: str | None = None,
        suggested_action: str | None = None,
        note: str | None = None,
    ) -> FeatureRecord:
        """更新状态（返回新记录，调用方需调用 :meth:`save` 落盘）。"""
        record = self.require(feature_id)
        if status is FeatureStatus.VERIFIED and record.requires_protocol and not record.protocol_verified:
            raise RegistryError(
                f"{feature_id} 的协议尚未验证（protocol_verified=false），"
                "不允许置为 verified。请先完成抓包/实机验证。"
            )
        updated = replace(
            record,
            status=status,
            error_summary=error_summary,
            suggested_action=suggested_action if suggested_action is not None else record.suggested_action,
            notes=note if note is not None else record.notes,
            last_test_at=_now_iso(),
        )
        self._records[feature_id] = updated
        self.problems = self.validate()
        return updated

    def record_result(
        self,
        feature_id: str,
        *,
        passed: bool,
        error_summary: str | None = None,
        test_env: dict[str, object] | None = None,
        auto_disable_on_failure: bool = True,
    ) -> FeatureRecord:
        """记录一次验证结果。失败时默认降级为 ``disabled``（不删除代码）。"""
        record = self.require(feature_id)
        result = "pass" if passed else "fail"
        new_status = record.status
        action = record.suggested_action

        if passed:
            action = "none"
            error_summary = None
        else:
            action = "disable"
            if auto_disable_on_failure and record.status is FeatureStatus.VERIFIED:
                new_status = FeatureStatus.DISABLED

        updated = replace(
            record,
            status=new_status,
            last_result=result,
            last_test_at=_now_iso(),
            error_summary=error_summary,
            suggested_action=action,
            test_env=dict(test_env) if test_env is not None else record.test_env,
        )
        self._records[feature_id] = updated
        self.problems = self.validate()
        return updated

    # -- 自检 -------------------------------------------------------------- #
    def validate(self) -> list[str]:
        """返回自相矛盾之处。空列表表示健康。"""
        problems: list[str] = []
        for record in self._records.values():
            if record.status is FeatureStatus.VERIFIED:
                if record.requires_protocol and not record.protocol_verified:
                    problems.append(
                        f"{record.feature_id}: verified 但 protocol_verified=false"
                    )
                if record.last_result not in {"pass"}:
                    problems.append(
                        f"{record.feature_id}: verified 但 last_result={record.last_result!r}"
                    )
            if record.status is FeatureStatus.EXPERIMENTAL and record.last_result == "pass":
                problems.append(
                    f"{record.feature_id}: experimental 但 last_result='pass'"
                    "（已验证就该置 verified，否则状态说谎）"
                )
        return problems

    def snapshot(self) -> dict[str, object]:
        """给 debug_report.json 用的只读快照。"""
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": self.updated_at,
            "counts": {
                s.value: len(self.by_status(s)) for s in FeatureStatus
            },
            "features": [r.to_dict() for r in self._records.values()],
        }
