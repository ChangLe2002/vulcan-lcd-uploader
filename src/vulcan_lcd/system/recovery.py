# SPDX-License-Identifier: MIT
"""异常与退出时的服务恢复。

需求第 3 节要求"程序崩溃或被强制关闭时，通过 atexit 或系统钩子尝试恢复服务"。
这里做两件事：

1. 注册 ``atexit`` —— 覆盖正常退出、``sys.exit``、未捕获异常导致的退出；
2. 包装 ``sys.excepthook`` —— 未捕获异常时先恢复再打印原始 traceback。

**做不到的事要说清楚**：进程被 ``TerminateProcess``（任务管理器结束进程）
或断电时，任何 Python 钩子都不会执行。所以 README 里必须让用户知道
"强制结束后请手动启动服务"，并提供 ``scripts/restore_service.ps1`` 兜底。
"""

from __future__ import annotations

import atexit
import sys
from typing import Any, Callable

from .service_control import ServiceController, ServiceError

__all__ = ["RestoreGuard", "install_recovery"]


class RestoreGuard:
    """持有"是否由我们停止过服务"，并在退出时恢复。"""

    def __init__(
        self,
        controller: ServiceController,
        *,
        logger: Any | None = None,
        atexit_register: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        self._controller = controller
        self._logger = logger
        self._atexit_register = atexit_register or atexit.register
        self._armed = False
        self._original_hook: Callable[..., Any] | None = None
        self.restored = False

    # -- 生命周期 --------------------------------------------------------- #
    def arm(self) -> "RestoreGuard":
        """注册退出钩子（幂等）。"""
        if self._armed:
            return self
        self._atexit_register(self.restore)
        self._original_hook = sys.excepthook
        original = self._original_hook

        def hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
            self.restore(trigger="uncaught_exception")
            if original is not None:
                original(exc_type, exc, tb)

        sys.excepthook = hook
        self._armed = True
        return self

    def disarm(self) -> None:
        if self._original_hook is not None:
            sys.excepthook = self._original_hook
        self._armed = False

    # -- 恢复 ------------------------------------------------------------- #
    def restore(self, *, trigger: str = "exit") -> bool:
        """恢复官方服务。永不抛异常——退出流程里抛错只会让情况更糟。"""
        if self.restored:
            return False
        self.restored = True

        if not self._controller.stopped_by_us:
            self._log("info", "service_restore_skipped", detail="本进程未停止过服务")
            return False

        try:
            started = self._controller.release()
        except ServiceError as exc:
            self._log(
                "error", "service_restore_failed",
                error_code=exc.error_code, detail=exc.message, trigger=trigger,
            )
            return False
        except Exception as exc:  # noqa: BLE001 - 任何异常都不能阻断退出
            self._log("error", "service_restore_failed", error_code="UNKNOWN", detail=str(exc))
            return False

        self._log("info", "service_restored", trigger=trigger, started=started)
        return started

    # -- 上下文 ----------------------------------------------------------- #
    def __enter__(self) -> "RestoreGuard":
        return self.arm()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.restore(trigger="context_exit")

    # -- 内部 ------------------------------------------------------------- #
    def _log(self, level: str, action: str, **fields: Any) -> None:
        if self._logger is None:
            return
        try:
            getattr(self._logger, level)(action, feature_id="service_control", **fields)
        except Exception:  # noqa: BLE001 - 日志失败绝不能影响恢复流程
            pass


def install_recovery(controller: ServiceController, logger: Any | None = None) -> RestoreGuard:
    """便捷函数：创建并注册守卫。"""
    return RestoreGuard(controller, logger=logger).arm()
