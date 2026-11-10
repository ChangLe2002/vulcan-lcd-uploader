# SPDX-License-Identifier: MIT
"""系统相关：权限、服务接管、异常恢复。"""

from .privileges import is_admin, is_windows
from .recovery import RestoreGuard, install_recovery
from .service_control import ServiceController, ServiceError, ServiceState, discover_services

__all__ = [
    "is_admin",
    "is_windows",
    "ServiceController",
    "ServiceError",
    "ServiceState",
    "discover_services",
    "RestoreGuard",
    "install_recovery",
]
