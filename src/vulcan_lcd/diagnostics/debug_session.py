# SPDX-License-Identifier: MIT
"""调试会话：把命令行开关收敛成一个不可变对象。

支持（需求 §9.2）::

    --debug                 调试模式：功能面板 + 原始收发 + 日志过滤
    --dry-run               空跑：所有串口写入只记录 hex 预览，不实际发送
    --feature=<feature_id>  只加载/只关注指定功能

设计要点：解析结果用 frozen dataclass 表示，**没有任何"全局开关"**。
需要知道模式的地方一律显式接收它，避免"某处偷偷读了 sys.argv"。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from typing import Sequence

__all__ = ["DebugSession", "parse_session"]


@dataclass(frozen=True)
class DebugSession:
    """一次运行的调试上下文。"""

    debug: bool = False
    dry_run: bool = False
    feature_filter: str | None = None
    log_raw_serial: bool = True

    # -- 派生属性 --------------------------------------------------------- #
    @property
    def is_production(self) -> bool:
        return not self.debug

    @property
    def allows_manual_hex(self) -> bool:
        """人工原始发送只在调试模式可用（还需二次确认，见 gate）。"""
        return self.debug

    def matches(self, feature_id: str) -> bool:
        """当前会话是否关注该功能（``--feature`` 未指定时全部关注）。"""
        if self.feature_filter is None:
            return True
        return feature_id == self.feature_filter

    def with_dry_run(self, value: bool = True) -> "DebugSession":
        return replace(self, dry_run=value)

    def to_dict(self) -> dict[str, object]:
        return {
            "debug": self.debug,
            "dry_run": self.dry_run,
            "feature_filter": self.feature_filter,
            "log_raw_serial": self.log_raw_serial,
        }


def parse_session(argv: Sequence[str] | None = None) -> DebugSession:
    """解析命令行。未知参数会抛 ``SystemExit``（argparse 默认行为）。"""
    parser = argparse.ArgumentParser(
        prog="vulcan-lcd",
        description="火神智屏图传工具",
        add_help=True,
    )
    parser.add_argument("--debug", action="store_true", help="调试模式")
    parser.add_argument("--dry-run", action="store_true", help="空跑：不向串口写任何字节")
    parser.add_argument(
        "--feature",
        default=None,
        metavar="FEATURE_ID",
        help="只加载/只关注指定功能，例如 gif_upload",
    )
    parser.add_argument(
        "--no-raw-log",
        action="store_true",
        help="不记录串口原始十六进制（减小日志体积）",
    )

    args = parser.parse_args(argv)

    feature = args.feature
    if feature is not None:
        feature = str(feature).strip()
        if not feature:
            feature = None

    return DebugSession(
        debug=bool(args.debug),
        dry_run=bool(args.dry_run),
        feature_filter=feature,
        log_raw_serial=not args.no_raw_log,
    )
