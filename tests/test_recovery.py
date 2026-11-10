# SPDX-License-Identifier: MIT
"""恢复守卫测试：退出/崩溃时必须尝试恢复服务，且永不抛异常。"""

from __future__ import annotations

import sys
from typing import Any, Callable

import pytest

from vulcan_lcd.system.recovery import RestoreGuard, install_recovery
from vulcan_lcd.system.service_control import ServiceController, ServiceError


class FakeController(ServiceController):
    """直接伪造状态，不执行任何命令。"""

    def __init__(self, *, stopped: bool = False, fail_release: bool = False) -> None:
        super().__init__("fake", runner=lambda args: (0, ""))
        self._stopped_by_us = stopped
        self.fail_release = fail_release
        self.release_calls = 0

    def release(self) -> bool:
        self.release_calls += 1
        if self.fail_release:
            raise ServiceError("启动失败", error_code="SERVICE_START_FAILED")
        self._stopped_by_us = False
        return True


class FakeLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any]]] = []

    def _record(self, level: str, action: str, **fields: Any) -> None:
        self.entries.append((level, action, fields))

    def info(self, action: str, **fields: Any) -> None:
        self._record("info", action, **fields)

    def error(self, action: str, **fields: Any) -> None:
        self._record("error", action, **fields)

    def warning(self, action: str, **fields: Any) -> None:
        self._record("warning", action, **fields)


# --------------------------------------------------------------------------- #
# 注册
# --------------------------------------------------------------------------- #
def test_arm_registers_atexit_once() -> None:
    calls: list[Callable[[], None]] = []
    guard = RestoreGuard(FakeController(), atexit_register=calls.append)
    guard.arm()
    guard.arm()
    assert len(calls) == 1
    guard.disarm()


def test_arm_replaces_excepthook_and_disarm_restores() -> None:
    original = sys.excepthook
    guard = RestoreGuard(FakeController(), atexit_register=lambda fn: None).arm()
    assert sys.excepthook is not original
    guard.disarm()
    assert sys.excepthook is original


# --------------------------------------------------------------------------- #
# 恢复行为
# --------------------------------------------------------------------------- #
def test_restore_skips_when_service_was_not_stopped() -> None:
    ctl = FakeController(stopped=False)
    guard = RestoreGuard(ctl, atexit_register=lambda fn: None)
    assert guard.restore() is False
    assert ctl.release_calls == 0


def test_restore_releases_when_we_stopped_it() -> None:
    ctl = FakeController(stopped=True)
    logger = FakeLogger()
    guard = RestoreGuard(ctl, logger=logger, atexit_register=lambda fn: None)
    assert guard.restore() is True
    assert ctl.release_calls == 1
    assert any(action == "service_restored" for _, action, _ in logger.entries)


def test_restore_is_idempotent() -> None:
    ctl = FakeController(stopped=True)
    guard = RestoreGuard(ctl, atexit_register=lambda fn: None)
    guard.restore()
    assert guard.restore() is False
    assert ctl.release_calls == 1


def test_restore_swallows_service_error() -> None:
    ctl = FakeController(stopped=True, fail_release=True)
    logger = FakeLogger()
    guard = RestoreGuard(ctl, logger=logger, atexit_register=lambda fn: None)
    assert guard.restore() is False
    assert any(action == "service_restore_failed" for _, action, _ in logger.entries)


def test_restore_swallows_unexpected_exception() -> None:
    class Boom(FakeController):
        def release(self) -> bool:
            raise RuntimeError("boom")

    guard = RestoreGuard(Boom(stopped=True), atexit_register=lambda fn: None)
    assert guard.restore() is False


def test_restore_never_raises_when_logger_breaks() -> None:
    class BadLogger:
        def info(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("log down")

        error = info
        warning = info

    guard = RestoreGuard(FakeController(stopped=True), logger=BadLogger(), atexit_register=lambda fn: None)
    guard.restore()  # 不应抛异常


def test_context_manager_restores() -> None:
    ctl = FakeController(stopped=True)
    calls: list[Callable[[], None]] = []
    with RestoreGuard(ctl, atexit_register=calls.append):
        pass
    assert ctl.release_calls == 1
    sys.excepthook = sys.__excepthook__


def test_install_recovery_returns_armed_guard() -> None:
    guard = install_recovery(FakeController())
    assert isinstance(guard, RestoreGuard)
    guard.disarm()


def test_restore_records_trigger() -> None:
    ctl = FakeController(stopped=True)
    logger = FakeLogger()
    guard = RestoreGuard(ctl, logger=logger, atexit_register=lambda fn: None)
    guard.restore(trigger="uncaught_exception")
    entry = next(e for e in logger.entries if e[1] == "service_restored")
    assert entry[2]["trigger"] == "uncaught_exception"
