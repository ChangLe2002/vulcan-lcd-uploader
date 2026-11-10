# SPDX-License-Identifier: MIT
"""生产闸门：决定某个功能此刻能不能向串口写数据。

两条独立的约束叠加
------------------
1. **注册表状态**（``feature_registry.json``）：只有 ``verified`` 允许写；
   ``experimental`` 永远只读（即使打开调试模式也不放宽写权限）；
   ``disabled`` / ``removed`` / 未知 id 一律拦截。
2. **协议就绪度**（``config/settings.default.json`` 的 ``*_verified`` 标记）：
   即使注册表写 verified，若配置声明"协议未验证"，也视为自相矛盾——由
   :func:`audit` 报出来。

失败方向是**关闭**（fail closed）：未知功能、依赖未验证、配置矛盾，全部拒绝写。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .registry import FeatureRegistry, FeatureStatus

__all__ = [
    "Permission",
    "FeatureBlockedError",
    "ConfigGate",
    "ConfigGateResult",
    "CONFIG_GATES",
    "MANUAL_FEATURE_ID",
    "MANUAL_SEND_ACTION",
    "evaluate_config",
    "FeatureGate",
    "audit",
]

#: 人工原始发送的伪 feature_id（只用于日志与调试报告，不进注册表）
MANUAL_FEATURE_ID = "manual_raw_hex"

#: 人工原始发送的 action 名
MANUAL_SEND_ACTION = "manual_send"


class Permission(str, Enum):
    """写权限。没有"可能可以"这种含糊状态。"""

    WRITE = "write"
    READ_ONLY = "read_only"
    BLOCKED = "blocked"


class FeatureBlockedError(Exception):
    """功能被闸门拦截。"""

    error_code = "FEATURE_BLOCKED"

    def __init__(self, message: str, *, feature_id: str = "", permission: Permission | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.feature_id = feature_id
        self.permission = permission


# --------------------------------------------------------------------------- #
# 协议就绪度闸门（配置层面）
# --------------------------------------------------------------------------- #
def _get(cfg: dict, path: tuple[str, ...], default: object = None) -> object:
    cur: object = cfg
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _flag(cfg: dict, path: tuple[str, ...]) -> bool:
    return bool(_get(cfg, path, False))


@dataclass(frozen=True)
class ConfigGate:
    """一条协议前提条件。"""

    label: str
    features: tuple[str, ...]
    how_to_fix: str
    check: Callable[[dict], bool]


def _gate_handshake(cfg: dict) -> bool:
    return (
        _flag(cfg, ("protocol", "handshake_verified"))
        and _get(cfg, ("protocol", "handshake_tx_hex")) not in (None, "")
        and _get(cfg, ("protocol", "handshake_rx_hex")) not in (None, "")
    )


CONFIG_GATES: tuple[ConfigGate, ...] = (
    ConfigGate(
        "握手请求/应答字节",
        ("auto_port_scan", "service_control"),
        "抓包官方软件握手会话，填 handshake_tx_hex / handshake_rx_hex 并置 handshake_verified=true",
        _gate_handshake,
    ),
    ConfigGate(
        "图片帧校验范围",
        ("gif_upload", "static_image"),
        "抓包确认 GIF/图片帧的校验覆盖区间，置 range_verified_for_image_frames=true",
        lambda c: _flag(c, ("protocol", "checksum", "range_verified_for_image_frames")),
    ),
    ConfigGate(
        "分包大小",
        ("gif_upload", "static_image"),
        "抓包确认单包载荷长度，置 transport.chunk_size_verified=true",
        lambda c: _flag(c, ("transport", "chunk_size_verified")),
    ),
    ConfigGate(
        "帧间延时",
        ("gif_upload", "static_image"),
        "抓包确认包间间隔，置 transport.inter_packet_delay_verified=true",
        lambda c: _flag(c, ("transport", "inter_packet_delay_verified")),
    ),
    ConfigGate(
        "像素格式",
        ("static_image", "dual_screen_layout"),  # gif_upload 走 JPEG 直传，不涉及 RGB565
        "抓包确认 RGB565 的字节排列（RGB 还是 BGR、高低字节序），置 media.pixel_format_verified=true",
        lambda c: _flag(c, ("media", "pixel_format_verified")),
    ),
    ConfigGate(
        "官方服务名",
        ("service_control",),
        "用 Get-Service 确认服务名后置 service.name_confirmed=true",
        lambda c: _flag(c, ("service", "name_confirmed")),
    ),
    ConfigGate(
        "监控帧格式",
        ("gpu_monitor", "cpu_monitor"),
        "抓包官方软件监控模式的数据流，置 monitor.frame_format_verified=true",
        lambda c: _flag(c, ("monitor", "frame_format_verified")),
    ),
    ConfigGate(
        "双屏分区指令",
        ("dual_screen_layout",),
        "抓包确认是否存在分区/局部刷新指令，置 dual_screen.partition_verified=true",
        lambda c: _flag(c, ("dual_screen", "partition_verified")),
    ),
    ConfigGate(
        "可选 ACK 机制",
        ("ack_wait_optional",),
        "抓包确认是否存在逐包 ACK；未确认前即使 enabled=true 也不得开启等待",
        lambda c: _flag(c, ("transport", "ack_wait", "verified")),
    ),
)


@dataclass(frozen=True)
class ConfigGateResult:
    label: str
    ready: bool
    features: tuple[str, ...]
    how_to_fix: str


def evaluate_config(cfg: dict) -> list[ConfigGateResult]:
    """逐条评估配置闸门。单条判定异常视为"未就绪"（fail closed）。"""
    results: list[ConfigGateResult] = []
    for gate in CONFIG_GATES:
        try:
            ready = bool(gate.check(cfg))
        except Exception:  # noqa: BLE001 - 配置畸形不应让整个评估崩掉
            ready = False
        results.append(
            ConfigGateResult(
                label=gate.label,
                ready=ready,
                features=gate.features,
                how_to_fix=gate.how_to_fix,
            )
        )
    return results


# --------------------------------------------------------------------------- #
# 功能闸门
# --------------------------------------------------------------------------- #
class FeatureGate:
    """把注册表状态翻译成"能不能写串口"。"""

    def __init__(
        self,
        registry: FeatureRegistry,
        *,
        debug_mode: bool = False,
    ) -> None:
        self.registry = registry
        self.debug_mode = debug_mode

    # -- 单个功能 --------------------------------------------------------- #
    def permission(self, feature_id: str, _seen: frozenset[str] = frozenset()) -> Permission:
        record = self.registry.get(feature_id)
        if record is None:
            return Permission.BLOCKED
        if not record.status.is_loaded:
            return Permission.BLOCKED
        if record.status is FeatureStatus.DISABLED:
            return Permission.BLOCKED
        if record.status is FeatureStatus.EXPERIMENTAL:
            # 调试模式也不放宽写权限：未验证的协议永远不写
            return Permission.READ_ONLY
        # verified
        if feature_id in _seen:  # 依赖环：配置错误，直接拦截而非降级
            return Permission.BLOCKED
        for dep in record.depends_on:
            dep_perm = self.permission(dep, _seen | {feature_id})
            if dep_perm is Permission.BLOCKED:
                # 依赖被禁用/移除/成环 → 父功能也写不了，避免"半个功能"跑起来
                return Permission.BLOCKED
            if dep_perm is not Permission.WRITE:
                return Permission.READ_ONLY
        return Permission.WRITE

    def can_write(self, feature_id: str) -> bool:
        return self.permission(feature_id) is Permission.WRITE

    def require_write(self, feature_id: str) -> None:
        """写操作入口必须调用本方法；不通过则抛异常。"""
        perm = self.permission(feature_id)
        if perm is Permission.WRITE:
            return
        record = self.registry.get(feature_id)
        detail = record.error_summary if record and record.error_summary else ""
        raise FeatureBlockedError(
            f"功能 {feature_id} 当前权限为 {perm.value}，拒绝向串口写入。"
            f"{(' 原因：' + detail) if detail else ''}",
            feature_id=feature_id,
            permission=perm,
        )

    # -- 批量 ------------------------------------------------------------- #
    def report(self) -> list[tuple[str, Permission]]:
        return [(r.feature_id, self.permission(r.feature_id)) for r in self.registry]

    def writable(self) -> list[str]:
        return [fid for fid, perm in self.report() if perm is Permission.WRITE]

    # -- 人工原始发送（受控例外）------------------------------------------ #
    def require_manual_raw(
        self,
        *,
        confirmed: bool,
        config: dict | None = None,
    ) -> None:
        """人工原始 hex 发送的唯一入口。

        这是对"功能驱动发送一律禁止未验证数据"的**唯一例外**，条件全部满足才放行：

        1. 必须处于调试模式（``debug_mode=True``）；
        2. 必须由人显式二次确认（``confirmed=True``），且配置未关闭确认要求；
        3. 调用方必须记录 ``feature_id=manual_raw_hex``、``action=manual_send``。

        放行的理由是责任归属清晰：**这是人输入的字节，不是程序在猜。**
        """
        if not self.debug_mode:
            raise FeatureBlockedError(
                "人工发送仅在调试模式（--debug）下可用；生产模式一律禁止。",
                feature_id=MANUAL_FEATURE_ID,
                permission=Permission.BLOCKED,
            )

        require_confirm = bool(
            _get(config or {}, ("debug", "require_confirm_for_manual_hex"), True)
        )
        if require_confirm and not confirmed:
            raise FeatureBlockedError(
                "人工发送需要二次确认：未收到 confirmed=True，已拒绝写入。",
                feature_id=MANUAL_FEATURE_ID,
                permission=Permission.BLOCKED,
            )

    def manual_raw_allowed(self, *, confirmed: bool, config: dict | None = None) -> bool:
        """:meth:`require_manual_raw` 的非抛异常版本，供 UI 决定按钮是否可点。"""
        try:
            self.require_manual_raw(confirmed=confirmed, config=config)
        except FeatureBlockedError:
            return False
        return True


# --------------------------------------------------------------------------- #
# 一致性审计
# --------------------------------------------------------------------------- #
def audit(registry: FeatureRegistry, cfg: dict) -> list[str]:
    """检查注册表与配置是否互相矛盾。

    典型矛盾：注册表说"协议已验证"，配置里的 ``*_verified`` 却还是 false。
    这种不一致比单个错误更危险——两处都说自己是对的。
    """
    findings: list[str] = list(registry.problems)
    results = evaluate_config(cfg)
    ready_by_feature: dict[str, bool] = {}
    for result in results:
        for fid in result.features:
            ready_by_feature[fid] = ready_by_feature.get(fid, True) and result.ready

    for record in registry:
        gate_ready = ready_by_feature.get(record.feature_id)
        if gate_ready is None:
            continue
        if record.protocol_verified and not gate_ready:
            findings.append(
                f"{record.feature_id}: 注册表 protocol_verified=true，"
                "但配置闸门未满足 —— 两处说法矛盾，按未验证处理"
            )
        elif not record.protocol_verified and gate_ready:
            findings.append(
                f"{record.feature_id}: 配置闸门已全部满足，但注册表仍标 protocol_verified=false "
                "—— 可能忘了更新注册表"
            )
    return findings
