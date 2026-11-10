# SPDX-License-Identifier: MIT
"""应用装配：把配置、注册表、闸门、日志、会话拼成一个可注入的上下文。

刻意**不导入 PySide6** —— 这样 GUI 之外（测试、CLI、dry-run）也能复用装配逻辑，
而且本模块可以被纯 pytest 覆盖，不需要 QApplication。
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics.debug_session import DebugSession
from .diagnostics.logging_setup import StructuredLogger
from .features.gate import FeatureGate, audit
from .features.registry import FeatureRegistry

__all__ = [
    "AppContext",
    "build_context",
    "load_config",
    "AppError",
    "is_frozen",
    "resource_root",
    "writable_root",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包产物里。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """**只读**资源目录：配置、注册表、许可证等随包分发的文件。

    * 源码运行：项目根目录；
    * 打包运行：``sys._MEIPASS``（onedir 模式下即 exe 旁的 ``_internal``）。
    """
    if is_frozen():
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled)
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def writable_root() -> Path:
    """**可写**目录：日志、调试报告。

    打包后不能往 ``_MEIPASS`` 写（可能是只读的临时目录），所以落在 exe 同级目录。
    源码运行时就是项目根目录。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


class AppError(Exception):
    """装配失败（配置/注册表缺失或损坏）。"""

    error_code = "APP_INIT_FAILED"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class AppContext:
    """一次运行所需的全部只读依赖。"""

    root: Path
    session: DebugSession
    config: dict[str, Any]
    registry: FeatureRegistry
    gate: FeatureGate
    logger: StructuredLogger
    config_problems: tuple[str, ...] = ()

    # -- 便捷访问 --------------------------------------------------------- #
    @property
    def service_name(self) -> str:
        return str(self.config.get("service", {}).get("name", ""))

    @property
    def log_dir(self) -> Path:
        return Path(self.config.get("debug", {}).get("export_dir", "logs"))

    def feature_allowed(self, feature_id: str) -> bool:
        """该功能此刻是否允许写串口。"""
        return self.gate.can_write(feature_id)

    def blocked_reason(self, feature_id: str) -> str:
        """给 UI 的 tooltip 用：为什么这个按钮是灰的。"""
        record = self.registry.get(feature_id)
        if record is None:
            return "未知功能"
        if record.status.value == "experimental":
            detail = record.error_summary or "协议未验证"
            return f"{record.name} 尚未验证（experimental）：{detail}"
        if record.status.value in {"disabled", "removed"}:
            return f"{record.name} 已{('禁用' if record.status.value == 'disabled' else '移除')}"
        for dep in record.depends_on:
            if not self.gate.can_write(dep):
                return f"依赖的功能 {dep} 尚不可用"
        return ""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并：``settings.user.json`` 只覆盖它显式写出的键。"""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(root: str | Path | None = None) -> tuple[dict[str, Any], list[str]]:
    """载入默认配置并叠加用户配置。

    Args:
        root: 资源目录（含 ``config/``）。默认自动判断源码/打包环境。

    Returns:
        ``(config, problems)``。``problems`` 非空表示用户配置文件有问题，
        但**仍然返回可用的默认配置**——配置文件写坏不该让程序打不开。
    """
    base_root = Path(root) if root is not None else resource_root()
    default_path = base_root / "config" / "settings.default.json"
    user_path = base_root / "config" / "settings.user.json"

    if not default_path.is_file():
        raise AppError(f"默认配置缺失: {default_path}")
    try:
        config = json.loads(default_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AppError(f"默认配置 JSON 解析失败: {exc}") from exc

    problems: list[str] = []
    if user_path.is_file():
        try:
            override = json.loads(user_path.read_text(encoding="utf-8-sig"))
            if not isinstance(override, dict):
                raise ValueError("顶层必须是对象")
            config = _deep_merge(config, override)
        except Exception as exc:  # noqa: BLE001 - 用户配置坏了也要能启动
            problems.append(f"settings.user.json 无法使用，已忽略: {exc}")
    return config, problems


def build_context(
    session: DebugSession,
    *,
    root: str | Path | None = None,
    console_log: bool = True,
) -> AppContext:
    """装配运行上下文。任何缺失都抛 :class:`AppError`，不带病启动。

    ``root`` 只影响**资源**位置；日志与报告始终写到 :func:`writable_root`。
    """
    res_root = Path(root) if root is not None else resource_root()
    config, problems = load_config(res_root)

    registry_path = res_root / "feature_registry.json"
    try:
        registry = FeatureRegistry.load(registry_path)
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"功能注册表载入失败: {exc}") from exc

    out_root = writable_root() if root is None else Path(root)
    log_dir = out_root / str(config.get("debug", {}).get("export_dir", "logs"))
    logger = StructuredLogger(
        "app",
        log_dir=log_dir,
        console=console_log,
        log_raw_serial=bool(config.get("debug", {}).get("log_raw_serial", True)) and session.log_raw_serial,
        raw_limit=int(config.get("debug", {}).get("raw_truncate_bytes", 64)),
    )

    gate = FeatureGate(registry, debug_mode=session.debug)

    findings = audit(registry, config)
    logger.info(
        "context_ready",
        result="ok" if not findings else "partial",
        error_code=None if not findings else "PROTOCOL_UNVERIFIED",
        debug=session.debug,
        dry_run=session.dry_run,
        registry_features=len(registry),
        findings=len(findings),
    )
    for problem in problems:
        logger.warning("config_problem", result="partial", error_code="ENV_ERROR", detail=problem)
    for finding in findings:
        logger.warning("registry_inconsistency", result="partial", detail=finding)

    return AppContext(
        root=out_root,
        session=session,
        config=config,
        registry=registry,
        gate=gate,
        logger=logger,
        config_problems=tuple(problems),
    )


def describe_environment() -> str:
    """一行环境摘要，用于窗口标题栏与日志。"""
    in_venv = sys.prefix != sys.base_prefix
    return f"Python {sys.version.split()[0]} · {'venv' if in_venv else '系统解释器'}"
