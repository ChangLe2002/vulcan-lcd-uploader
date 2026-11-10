# SPDX-License-Identifier: MIT
"""导出调试报告（不启动 GUI）。

用法::

    python tools/export_report.py                 # 生成到项目根目录
    python tools/export_report.py --out reports   # 指定目录
    python tools/export_report.py --debug         # 标记为调试会话

产出的 ``debug_report.md`` 末尾带「给 Harness 的修改指令模板」，可直接复制。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vulcan_lcd.core.port_scanner import list_serial_ports  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.diagnostics.logging_setup import StructuredLogger  # noqa: E402
from vulcan_lcd.diagnostics.report import ReportContext, build_report, write_reports  # noqa: E402
from vulcan_lcd.features.registry import FeatureRegistry  # noqa: E402
from vulcan_lcd.system.privileges import is_admin  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出调试报告")
    ap.add_argument("--out", default=str(REPO))
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--feature", default=None)
    args = ap.parse_args(argv)

    session = DebugSession(debug=args.debug, dry_run=True, feature_filter=args.feature)
    logger = StructuredLogger(
        "export_report",
        log_dir=REPO / "logs",
        console=True,
        log_raw_serial=session.debug,
    )

    registry = FeatureRegistry.load(REPO / "feature_registry.json")
    config = json.loads((REPO / "config" / "settings.default.json").read_text(encoding="utf-8"))

    logger.info("export_start", feature_id=None, out=args.out)

    try:
        ports = tuple(p.device for p in list_serial_ports())
    except Exception as exc:  # noqa: BLE001 - 枚举失败不应阻断报告
        logger.warning("port_enum_failed", result="fail", error_code="ENV_ERROR", detail=str(exc))
        ports = ()

    logger.info(
        "environment_probe",
        result="ok",
        admin=is_admin(),
        port_count=len(ports),
    )

    report = build_report(
        ReportContext(
            registry=registry,
            config=config,
            session=session,
            logger=logger,
            ports=ports,
            handshake=None,
            service_name=str(config.get("service", {}).get("name", "")),
            service_status="unknown（本工具不查询服务状态）",
        )
    )

    md_path, json_path = write_reports(report, args.out)
    print(f"\n已生成:\n  {md_path}\n  {json_path}")
    print(f"关注项: {len(report['attention'])} 个，待验证闸门: {len(report['unmet_gates'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
