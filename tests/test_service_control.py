# SPDX-License-Identifier: MIT
"""服务接管测试：全部用假 runner，不碰真实服务。"""

from __future__ import annotations

from typing import Sequence

import pytest

from vulcan_lcd.system.service_control import (
    ServiceController,
    ServiceError,
    _parse_status,
    discover_services,
)

SERVICE = "iGameCenterService"


class FakeSC:
    """模拟 sc.exe 的状态机。"""

    def __init__(
        self,
        *,
        exists: bool = True,
        status: str = "RUNNING",
        deny: bool = False,
        stop_fails: bool = False,
        stuck: bool = False,
    ) -> None:
        self.exists = exists
        self.status = status
        self.deny = deny
        self.stop_fails = stop_fails
        self.stuck = stuck          # 状态永不改变 → 触发超时
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        args = list(args)
        self.calls.append(args)
        if self.deny:
            return 5, "拒绝访问。"

        if args[:2] == ["sc", "query"]:
            if not self.exists:
                return 1060, "指定的服务未安装。"
            return 0, (
                f"SERVICE_NAME: {SERVICE}\n"
                "        TYPE               : 10  WIN32_OWN_PROCESS\n"
                f"        STATE              : 4  {self.status}\n"
            )

        if args[:2] == ["sc", "stop"]:
            if self.stop_fails:
                return 1062, "服务尚未启动。"
            if not self.stuck:
                self.status = "STOPPED"
            return 0, "SERVICE_NAME: ..."

        if args[:2] == ["sc", "start"]:
            if not self.stuck:
                self.status = "RUNNING"
            return 0, "SERVICE_NAME: ..."

        return 1, ""


def controller(fake: FakeSC, **kw: object) -> ServiceController:
    return ServiceController(
        SERVICE,
        runner=fake,
        poll_s=0,
        sleeper=lambda _s: None,
        attempt_timeout_s=0.05,
        **kw,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# 状态解析
# --------------------------------------------------------------------------- #
def test_parse_status_running() -> None:
    assert _parse_status("        STATE              : 4  RUNNING\n") == "RUNNING"


def test_parse_status_with_trailing_notes() -> None:
    text = "        STATE              : 1  STOPPED\n                                (NOT_STOPPABLE)\n"
    assert _parse_status(text) == "STOPPED"


def test_parse_status_start_pending_with_underscore() -> None:
    """回归：START_PENDING 含下划线，早期实现会误返回 'STATE' 导致超时。"""
    assert _parse_status("        STATE              : 2  START_PENDING\n") == "START_PENDING"


def test_parse_status_stop_pending() -> None:
    assert _parse_status("        STATE              : 3  STOP_PENDING\n") == "STOP_PENDING"


def test_parse_status_unknown() -> None:
    assert _parse_status("garbage") == "UNKNOWN"


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def test_query_running() -> None:
    state = controller(FakeSC()).query()
    assert state.exists is True
    assert state.is_running is True
    assert "RUNNING" in state.describe()


def test_query_missing_service_is_not_an_error() -> None:
    state = controller(FakeSC(exists=False)).query()
    assert state.exists is False
    assert "未安装" in state.describe()


def test_query_permission_denied_raises() -> None:
    with pytest.raises(ServiceError) as excinfo:
        controller(FakeSC(deny=True)).query()
    assert excinfo.value.error_code == "PERMISSION_DENIED"


# --------------------------------------------------------------------------- #
# 停止 / 启动
# --------------------------------------------------------------------------- #
def test_stop_changes_state_and_waits() -> None:
    fake = FakeSC(status="RUNNING")
    ctl = controller(fake)
    assert ctl.stop() is True
    assert fake.status == "STOPPED"
    assert ctl.stopped_by_us is True


def test_stop_already_stopped_is_noop() -> None:
    fake = FakeSC(status="STOPPED")
    ctl = controller(fake)
    assert ctl.stop() is False
    assert not any(call[:2] == ["sc", "stop"] for call in fake.calls)


def test_stop_missing_service_raises() -> None:
    with pytest.raises(ServiceError) as excinfo:
        controller(FakeSC(exists=False)).stop()
    assert excinfo.value.error_code == "SERVICE_NOT_FOUND"


def test_stop_not_started_exit_code_is_treated_as_success() -> None:
    """sc 返回 1062（服务未启动）时，目标状态已达成。"""
    fake = FakeSC(status="RUNNING", stop_fails=True)
    ctl = controller(fake)
    assert ctl.stop() is True
    assert ctl.stopped_by_us is True


def test_stop_times_out() -> None:
    fake = FakeSC(status="RUNNING", stuck=True)
    with pytest.raises(ServiceError) as excinfo:
        controller(fake, timeout_s=0.05).stop()
    assert excinfo.value.error_code == "SERVICE_TIMEOUT"


def test_start_changes_state() -> None:
    fake = FakeSC(status="STOPPED")
    ctl = controller(fake)
    assert ctl.start() is True
    assert fake.status == "RUNNING"


def test_start_already_running_is_noop() -> None:
    fake = FakeSC(status="RUNNING")
    assert controller(fake).start() is False


def test_access_denied_on_stop() -> None:
    with pytest.raises(ServiceError) as excinfo:
        controller(FakeSC(deny=True)).stop()
    assert excinfo.value.error_code == "PERMISSION_DENIED"


# --------------------------------------------------------------------------- #
# 接管 / 恢复
# --------------------------------------------------------------------------- #
def test_takeover_stops_and_marks() -> None:
    fake = FakeSC(status="RUNNING")
    ctl = controller(fake)
    assert ctl.takeover() is True
    assert ctl.stopped_by_us is True


def test_takeover_tolerates_missing_service() -> None:
    """没装官方软件是合法状态，不应该炸。"""
    assert controller(FakeSC(exists=False)).takeover() is False


def test_release_without_takeover_does_nothing() -> None:
    fake = FakeSC(status="STOPPED")
    ctl = controller(fake)
    assert ctl.release() is False
    assert fake.status == "STOPPED"


def test_release_restarts_service_it_stopped() -> None:
    fake = FakeSC(status="RUNNING")
    ctl = controller(fake)
    ctl.takeover()
    assert ctl.release() is True
    assert fake.status == "RUNNING"
    assert ctl.stopped_by_us is False


def test_release_is_idempotent() -> None:
    fake = FakeSC(status="RUNNING")
    ctl = controller(fake)
    ctl.takeover()
    ctl.release()
    starts = [c for c in fake.calls if c[:2] == ["sc", "start"]]
    assert len(starts) == 1


# --------------------------------------------------------------------------- #
# 过渡状态与"请求被忽略"（真实踩过的坑）
# --------------------------------------------------------------------------- #
class IgnoringStopSC(FakeSC):
    """第一次 sc stop 被系统忽略：服务继续运行。"""

    def __init__(self) -> None:
        super().__init__(status="RUNNING")
        self.stop_calls = 0

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        if list(args)[:2] == ["sc", "stop"]:
            self.stop_calls += 1
            self.calls.append(list(args))
            if self.stop_calls == 1:
                self.status = "RUNNING"
                return 0, ""
            self.status = "STOPPED"
            return 0, ""
        return super().__call__(args)


def test_stop_retries_when_request_is_ignored() -> None:
    fake = IgnoringStopSC()
    ctl = ServiceController(
        SERVICE,
        runner=fake,
        poll_s=0,
        sleeper=lambda _s: None,
        attempt_timeout_s=0.01,
        timeout_s=0.2,
    )
    assert ctl.stop() is True
    assert fake.stop_calls == 2
    assert fake.status == "STOPPED"


class PendingThenRunningSC(FakeSC):
    """初始处于 START_PENDING，几次查询后落定到 RUNNING。"""

    def __init__(self) -> None:
        super().__init__(status="START_PENDING")
        self.queries = 0

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        if list(args)[:2] == ["sc", "query"]:
            self.queries += 1
            if self.status == "START_PENDING" and self.queries >= 2:
                self.status = "RUNNING"
        return super().__call__(args)


def test_stop_settles_pending_state_first() -> None:
    fake = PendingThenRunningSC()
    ctl = controller(fake)
    assert ctl.stop() is True
    assert fake.status == "STOPPED"


class StopPendingThenStoppedSC(FakeSC):
    def __init__(self) -> None:
        super().__init__(status="STOP_PENDING")
        self.queries = 0

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        if list(args)[:2] == ["sc", "query"]:
            self.queries += 1
            if self.status == "STOP_PENDING" and self.queries >= 2:
                self.status = "STOPPED"
        return super().__call__(args)


def test_start_settles_pending_state_first() -> None:
    fake = StopPendingThenStoppedSC()
    ctl = controller(fake)
    assert ctl.start() is True
    assert fake.status == "RUNNING"


# --------------------------------------------------------------------------- #
# 实机故障回归：1061（服务拒绝控制消息）
# --------------------------------------------------------------------------- #
class CannotAcceptControlSC(FakeSC):
    """模拟实机故障：服务对 stop/start 返回 1061。"""

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        if list(args)[:2] in (["sc", "stop"], ["sc", "start"]):
            self.calls.append(list(args))
            return 1061, "The service cannot accept control messages at this time."
        return super().__call__(args)


def test_stop_1061_gives_actionable_hint() -> None:
    ctl = ServiceController(
        SERVICE,
        runner=CannotAcceptControlSC(status="RUNNING"),
        poll_s=0,
        sleeper=lambda _s: None,
        attempt_timeout_s=0.01,
        timeout_s=0.2,
    )
    with pytest.raises(ServiceError) as excinfo:
        ctl.stop()
    assert excinfo.value.error_code == "SERVICE_TIMEOUT"
    assert "1061" in excinfo.value.message
    assert "重启" in excinfo.value.message


def test_stop_succeeds_when_state_reaches_target_late() -> None:
    """服务比预算慢一点，但在第二次查询时已完成 → 仍应判成功。"""

    class LateSC(FakeSC):
        def __init__(self) -> None:
            super().__init__(status="RUNNING")
            self.requested = False

        def __call__(self, args: Sequence[str]) -> tuple[int, str]:
            if list(args)[:2] == ["sc", "stop"]:
                self.requested = True
                self.status = "STOP_PENDING"
                self.calls.append(list(args))
                return 0, ""
            if (
                list(args)[:2] == ["sc", "query"]
                and self.requested
                and self.status == "STOP_PENDING"
            ):
                self.status = "STOPPED"
            return super().__call__(args)

    ctl = ServiceController(
        SERVICE, runner=LateSC(), poll_s=0, sleeper=lambda _s: None, attempt_timeout_s=0
    )
    assert ctl.stop() is True


# --------------------------------------------------------------------------- #
# 发现
# --------------------------------------------------------------------------- #
def test_discover_services_filters_by_pattern() -> None:
    listing = (
        "SERVICE_NAME: iGameCenterService\n"
        "SERVICE_NAME: PresentMon\n"
        "SERVICE_NAME: igamehelper\n"
    )
    assert discover_services("igame", runner=lambda args: (0, listing)) == [
        "iGameCenterService",
        "igamehelper",
    ]


def test_discover_services_returns_empty_on_failure() -> None:
    assert discover_services("igame", runner=lambda args: (5, "")) == []
