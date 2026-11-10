# SPDX-License-Identifier: MIT
"""官方服务接管：停止 / 启动 / 状态查询 / 自动恢复。

为什么用 ``sc.exe`` 而不是 win32service
--------------------------------------
``sc`` 系统自带、无额外依赖、输出稳定。为一个 API 引入 pywin32 不值得。

安全约束（需求第 3 节）
----------------------
* 只停止/启动**已存在**的服务，绝不安装、删除或改配置；
* 停止前记录原状态，失败不谎报成功；
* 恢复是幂等的：只恢复**自己停过**的服务；
* 服务不存在是合法状态，返回"未找到"而不是抛异常炸掉调用方。

两个实机踩过的坑（务必保留）
----------------------------
1. ``sc query`` 的状态行解析**不能用 ``isalpha()``** —— ``START_PENDING`` 含下划线，
   会被误判从而返回 "STATE"（曾导致启动等待永远超时）。
2. 在 ``START_PENDING`` / ``STOP_PENDING`` 期间发 stop/start，Windows 可能**直接忽略**，
   服务会继续朝原方向完成。所以必须先 :meth:`ServiceController._settle`
   等过渡态结束，再操作，且失败允许重试一次。
"""

from __future__ import annotations

from .proc import run as _run_hidden

import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Sequence

__all__ = [
    "ServiceError",
    "ServiceState",
    "ServiceController",
    "default_runner",
    "discover_services",
    "TARGET_RUNNING",
    "TARGET_STOPPED",
]

TARGET_RUNNING = "RUNNING"
TARGET_STOPPED = "STOPPED"

# sc.exe 退出码
_SC_NOT_FOUND = 1060
_SC_ACCESS_DENIED = 5
_SC_NOT_STARTED = 1062
_SC_ALREADY_RUNNING = 1056
_SC_CANNOT_ACCEPT_CTRL = 1061
_SC_DID_NOT_RESPOND = 1053

#: 这些错误表示"现在不行，等会儿再试"，不是致命失败
_RETRYABLE = frozenset({_SC_CANNOT_ACCEPT_CTRL, _SC_DID_NOT_RESPOND})


# 独立模式：为 True 时本工具**完全不碰**官方服务（不查、不停、不启）。
# 用于"没装/不想用 iGame Center"的场景：串口本来就空闲，无需接管。
_STANDALONE = False


def set_standalone(enabled: bool) -> None:
    """设置独立模式（全局生效，进程内所有 ServiceController 都遵守）。"""
    global _STANDALONE
    _STANDALONE = bool(enabled)


def is_standalone() -> bool:
    """当前是否处于独立模式。"""
    return _STANDALONE


class ServiceError(Exception):
    """服务操作失败。"""

    def __init__(self, message: str, *, error_code: str = "SERVICE_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


@dataclass(frozen=True)
class ServiceState:
    name: str
    exists: bool
    status: str          # RUNNING / STOPPED / START_PENDING / ... / UNKNOWN

    @property
    def is_running(self) -> bool:
        return self.status == TARGET_RUNNING

    @property
    def is_stopped(self) -> bool:
        return self.status == TARGET_STOPPED

    @property
    def is_pending(self) -> bool:
        return self.status.endswith("_PENDING")

    def describe(self) -> str:
        if not self.exists:
            return f"{self.name}: 未安装"
        return f"{self.name}: {self.status}"


def default_runner(args: Sequence[str]) -> tuple[int, str]:
    """执行命令，返回 ``(退出码, 合并输出)``。

    编码坑：``sc.exe`` 在中文系统上用 GBK 输出，``text=True`` 会抛
    UnicodeDecodeError。这里按字节取回再逐级解码。
    """
    try:
        proc = _run_hidden(  # noqa: S603 - 参数固定，无 shell；不弹控制台
            list(args),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ServiceError(f"找不到命令 {args[0]}", error_code="ENV_ERROR") from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"命令超时: {' '.join(args)}", error_code="TIMEOUT") from exc

    raw = (proc.stdout or b"") + (proc.stderr or b"")
    for encoding in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return proc.returncode, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return proc.returncode, raw.decode("utf-8", errors="replace")


class ServiceController:
    """单个服务的接管器。

    Args:
        name: 服务名（如 ``iGameCenterService``）。
        runner: 命令执行器，测试注入假实现。
        timeout_s: 单次 stop/start 的总时间预算。
        attempt_timeout_s: 单次尝试等待状态变化的上限（小于总预算才有重试空间）。
        poll_s: 轮询间隔。
        sleeper: 休眠函数，测试注入以便立即返回。
    """

    def __init__(
        self,
        name: str,
        *,
        runner: Callable[[Sequence[str]], tuple[int, str]] = default_runner,
        timeout_s: float = 20.0,
        attempt_timeout_s: float = 12.0,
        poll_s: float = 0.4,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not name:
            raise ValueError("服务名不能为空")
        self.name = name
        self._run = runner
        self._timeout_s = timeout_s
        self._attempt_timeout_s = attempt_timeout_s
        self._poll_s = poll_s
        self._sleep = sleeper
        self._stopped_by_us = False

    # -- 查询 ------------------------------------------------------------- #
    def query(self) -> ServiceState:
        code, output = self._run(["sc", "query", self.name])
        if code == _SC_NOT_FOUND:
            return ServiceState(self.name, False, "UNKNOWN")
        if code == _SC_ACCESS_DENIED:
            raise ServiceError(
                f"没有权限查询服务 {self.name}，请以管理员身份运行。",
                error_code="PERMISSION_DENIED",
            )
        status = _parse_status(output)
        exists = "SERVICE_NAME" in output.upper() or code == 0
        return ServiceState(self.name, exists, status)

    @property
    def is_running(self) -> bool:
        return self.query().is_running

    @property
    def exists(self) -> bool:
        return self.query().exists

    @property
    def stopped_by_us(self) -> bool:
        """本进程是否停止过该服务（决定退出时要不要恢复）。"""
        return self._stopped_by_us

    # -- 操作 ------------------------------------------------------------- #
    def stop(self) -> bool:
        """停止服务。已停止返回 ``False``；成功停止返回 ``True``。

        独立模式下**不做任何操作**，直接返回 False（服务不归我们管）。

        Raises:
            ServiceError: 不存在 / 无权限 / 重试后仍未停止（SERVICE_TIMEOUT）。
        """
        if _STANDALONE:
            return False
        state = self.query()
        if not state.exists:
            raise ServiceError(f"服务不存在: {self.name}", error_code="SERVICE_NOT_FOUND")
        if state.is_stopped:
            return False

        self._settle()
        if self.query().is_stopped:
            self._stopped_by_us = True
            return True

        deadline = time.monotonic() + self._timeout_s
        attempts = 0
        last_detail = ""

        while attempts < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempts += 1

            code, output = self._run(["sc", "stop", self.name])
            if code == _SC_ACCESS_DENIED:
                raise ServiceError(
                    f"没有权限停止 {self.name}，请以管理员身份运行。",
                    error_code="PERMISSION_DENIED",
                )
            if code == _SC_NOT_STARTED:
                self._stopped_by_us = True
                return True
            if code in _RETRYABLE:
                # 1061 / 1053：服务此刻不接受控制消息（常见于刚启动完），稍等重试
                last_detail = f"sc stop 返回 {code}（服务暂不接受控制消息）"
                self._sleep(self._poll_s)
                self._settle()
                continue
            if code != 0:
                raise ServiceError(
                    f"停止 {self.name} 失败（退出码 {code}）：{output.strip()}",
                    error_code="SERVICE_STOP_FAILED",
                )

            budget = min(self._attempt_timeout_s, remaining)
            if self._wait_for(TARGET_STOPPED, timeout_s=budget):
                self._stopped_by_us = True
                return True

            last_detail = f"当前状态 {self.query().status}"
            self._settle()
            if self.query().is_stopped:
                # 慢了一点，但在 settle 期间完成了
                self._stopped_by_us = True
                return True

        hint = ""
        if str(_SC_CANNOT_ACCEPT_CTRL) in last_detail:
            hint = (
                " 服务当前拒绝控制消息（1061），可能处于异常状态："
                "请关闭 iGame Center 后重试，或重启电脑；也可用任务管理器结束 "
                "iGameCenter.Service 进程让其自动重启。"
            )
        raise ServiceError(
            f"停止 {self.name} 未生效（已尝试 {attempts} 次；{last_detail}）。{hint}",
            error_code="SERVICE_TIMEOUT",
        )

    def start(self) -> bool:
        """启动服务。已在运行返回 ``False``；成功启动返回 ``True``。"""
        state = self.query()
        if not state.exists:
            raise ServiceError(f"服务不存在: {self.name}", error_code="SERVICE_NOT_FOUND")
        if state.is_running:
            return False

        self._settle()
        if self.query().is_running:
            self._stopped_by_us = False
            return False

        deadline = time.monotonic() + self._timeout_s
        attempts = 0
        last_detail = ""

        while attempts < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempts += 1

            code, output = self._run(["sc", "start", self.name])
            if code == _SC_ACCESS_DENIED:
                raise ServiceError(
                    f"没有权限启动 {self.name}，请以管理员身份运行。",
                    error_code="PERMISSION_DENIED",
                )
            if code == _SC_ALREADY_RUNNING:
                self._stopped_by_us = False
                return False
            if code in _RETRYABLE:
                last_detail = f"sc start 返回 {code}（服务暂不接受控制消息）"
                self._sleep(self._poll_s)
                self._settle()
                continue
            if code != 0:
                raise ServiceError(
                    f"启动 {self.name} 失败（退出码 {code}）：{output.strip()}",
                    error_code="SERVICE_START_FAILED",
                )

            budget = min(self._attempt_timeout_s, remaining)
            if self._wait_for(TARGET_RUNNING, timeout_s=budget):
                self._stopped_by_us = False
                return True

            last_detail = f"当前状态 {self.query().status}"
            self._settle()
            if self.query().is_running:
                # 启动较慢，但在 settle 期间完成了（实测约 10s）
                self._stopped_by_us = False
                return True

        raise ServiceError(
            f"启动 {self.name} 未生效（已尝试 {attempts} 次；{last_detail}）。",
            error_code="SERVICE_TIMEOUT",
        )

    # -- 接管 / 恢复 ------------------------------------------------------ #
    def takeover(self) -> bool:
        """为传输做准备：确保服务已停止。返回是否**本次**执行了停止。

        独立模式下什么都不做（假定串口本来就空闲）。
        """
        if _STANDALONE:
            return False
        try:
            return self.stop()
        except ServiceError as exc:
            if exc.error_code == "SERVICE_NOT_FOUND":
                return False
            raise

    def release(self) -> bool:
        """恢复官方控制。只恢复**自己停过**的服务，避免抢用户的设置。"""
        if _STANDALONE:
            return False
        if not self._stopped_by_us:
            return False
        return self.start()

    # -- 内部 ------------------------------------------------------------- #
    def _settle(self, *, timeout_s: float = 15.0) -> str:
        """等 ``*_PENDING`` 落定，避免请求被系统忽略。"""
        limit = min(self._timeout_s, timeout_s)
        deadline = time.monotonic() + limit
        status = self.query().status
        while status.endswith("_PENDING") and time.monotonic() < deadline:
            self._sleep(self._poll_s)
            status = self.query().status
        return status

    def _wait_for(self, target: str, *, timeout_s: float) -> bool:
        """轮询到 ``target`` 返回 True；超时返回 False（由调用方决定是否重试）。"""
        started = time.monotonic()
        while time.monotonic() - started < timeout_s:
            if self.query().status == target:
                return True
            self._sleep(self._poll_s)
        return self.query().status == target


def _parse_status(output: str) -> str:
    """从 ``sc query`` 输出里取状态名。

    Windows 不同语言的本地化只影响说明文字，``STATE`` 行的状态名仍是英文常量
    （``RUNNING`` / ``STOPPED`` / ``START_PENDING`` …）。

    注意：**不能用 ``isalpha()`` 过滤** —— ``START_PENDING`` 含下划线会被判为
    非字母，从而退化成返回 "STATE"（本项目踩过：导致启动等待永远超时）。
    这里改为"冒号后第一个既非纯数字、又含字母的 token"。
    """
    for line in output.splitlines():
        if "STATE" not in line.upper():
            continue
        after = line.split(":", 1)[1] if ":" in line else line
        for token in after.split():
            cleaned = token.strip(",()")
            if not cleaned or cleaned.isdigit():
                continue
            if cleaned.upper() == cleaned and any(ch.isalpha() for ch in cleaned):
                return cleaned
    return "UNKNOWN"


def discover_services(
    pattern: str = "igame",
    *,
    runner: Callable[[Sequence[str]], tuple[int, str]] = default_runner,
) -> list[str]:
    """列出名字匹配 ``pattern`` 的服务（大小写不敏感）。

    用途：配置里的服务名只是默认值；换机器/换版本时用它确认实际名字。
    """
    code, output = runner(["sc", "query", "type=", "service", "state=", "all"])
    if code != 0:
        return []
    needle = pattern.lower()
    names: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SERVICE_NAME:"):
            name = stripped.split(":", 1)[1].strip()
            if needle in name.lower():
                names.append(name)
    return names
