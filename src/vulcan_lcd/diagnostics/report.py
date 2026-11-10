# SPDX-License-Identifier: MIT
"""调试报告导出（需求 §9.5）。

产出两个文件：

* ``debug_report.md`` —— 给人看的：环境、设备、注册表快照、失败清单、建议动作，
  末尾附**可直接复制**的「给 Harness 的修改指令模板」；
* ``debug_report.json`` —— 给机器看的：同样的内容，结构化，便于以后做统计或比对。

报告的唯一意图是：**让拿到它的人（或 AI）不需要再问一句"你的环境是什么"**。
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..features.gate import evaluate_config
from ..features.registry import FeatureRegistry, FeatureStatus
from ..system.privileges import is_admin, is_windows
from .debug_session import DebugSession
from .logging_setup import StructuredLogger

__all__ = [
    "ReportContext",
    "collect_environment",
    "build_report",
    "render_markdown",
    "write_reports",
    "harness_instruction",
]

#: 视为"需要关注"的 last_result 取值
_ATTENTION_RESULTS = {"fail", "partial"}

_REPRO_STEPS = (
    "1) 关闭 iGameCenter（或在服务管理器停止 iGameCenterService）",
    "2) 在项目目录执行: .\\.venv_local\\python\\Scripts\\python.exe main.py --debug --feature={feature_id}",
    "3) 复现该操作，观察日志面板与 logs/debug_YYYYMMDD.log",
    "4) 点击「导出调试报告」",
)


@dataclass(frozen=True)
class ReportContext:
    """生成报告所需的全部输入（显式传入，不读全局状态）。"""

    registry: FeatureRegistry
    config: dict
    session: DebugSession
    logger: StructuredLogger | None = None
    ports: tuple[str, ...] = ()
    handshake: dict[str, Any] | None = None
    service_name: str = ""
    service_status: str = "unknown"
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 环境
# --------------------------------------------------------------------------- #
def collect_environment() -> dict[str, Any]:
    """采集运行环境。字段名与需求 §9.5 一一对应。"""
    in_venv = sys.prefix != sys.base_prefix
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": sys.executable,
        "venv_prefix": sys.prefix,
        "venv_active": in_venv,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "is_windows": is_windows(),
        "is_admin": is_admin(),
        "cwd": str(Path.cwd()),
    }


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def _is_attention(record: Any) -> bool:
    return record.status is not FeatureStatus.VERIFIED or record.last_result in _ATTENTION_RESULTS


def _log_excerpt(logger: StructuredLogger | None, feature_id: str, limit: int = 5) -> list[dict[str, Any]]:
    if logger is None:
        return []
    return [event.to_dict() for event in logger.recent(feature_id=feature_id, limit=limit)]


def build_report(ctx: ReportContext) -> dict[str, Any]:
    """组装报告字典。"""
    gates = evaluate_config(ctx.config)
    unmet = [
        {"label": g.label, "features": list(g.features), "how_to_fix": g.how_to_fix}
        for g in gates
        if not g.ready
    ]

    attention: list[dict[str, Any]] = []
    for record in ctx.registry:
        if not _is_attention(record):
            continue
        attention.append(
            {
                "feature_id": record.feature_id,
                "name": record.name,
                "module": record.module,
                "status": record.status.value,
                "protocol_verified": record.protocol_verified,
                "last_result": record.last_result,
                "error_summary": record.error_summary,
                "suggested_action": record.suggested_action,
                "repro_steps": [s.format(feature_id=record.feature_id) for s in _REPRO_STEPS],
                "recent_logs": _log_excerpt(ctx.logger, record.feature_id),
            }
        )

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "environment": collect_environment(),
        "session": ctx.session.to_dict(),
        "device": {
            "service_name": ctx.service_name,
            "service_status": ctx.service_status,
            "ports": list(ctx.ports),
            "handshake": ctx.handshake,
        },
        "registry": ctx.registry.snapshot(),
        "unmet_gates": unmet,
        "attention": attention,
        "extra": ctx.extra,
    }


# --------------------------------------------------------------------------- #
# 给 Harness 的指令模板
# --------------------------------------------------------------------------- #
def harness_instruction(feature_id: str, reason: str, log_excerpt: str = "") -> str:
    """生成一段可直接复制给 AI 助手的修改指令（需求 §9.5 的模板）。"""
    reason = (reason or "未提供").replace("\n", " ").strip()
    excerpt = (log_excerpt or "（无相关日志）").replace("\n", " ").strip()
    return (
        f"请仅修改 feature_id={feature_id} 对应模块；"
        f"失败原因={reason}；"
        f"相关日志={excerpt}；"
        "保留第 3 节安全约束（不碰驱动/不写固件/异常可恢复）和第 9 节日志/注册表机制；"
        "不要改动其他 verified 功能；"
        "修改后更新 feature_registry.json 和 CHANGELOG.md。"
    )


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """渲染为 Markdown。结构固定，便于人工扫读与机器解析。"""
    env = report["environment"]
    device = report["device"]
    session = report["session"]
    registry = report["registry"]

    out: list[str] = []
    out.append("# 火神智屏工具 · 调试报告")
    out.append("")
    out.append(f"- 生成时间：`{report['generated_at']}`")
    out.append(f"- 模式：{'调试' if session['debug'] else '生产'}"
               f"{' · dry-run' if session['dry_run'] else ''}"
               f"{' · 只看 ' + str(session['feature_filter']) if session['feature_filter'] else ''}")
    out.append("")

    # 1. 环境
    out.append("## 1. 运行环境")
    out.append("")
    out.append(
        _md_table(
            ["项目", "值"],
            [
                ["Python", f"{env['python_version']} ({env['python_implementation']})"],
                ["sys.executable", f"`{env['executable']}`"],
                ["虚拟环境", f"`{env['venv_prefix']}`（{'已激活' if env['venv_active'] else '⚠️ 未激活'}）"],
                ["管理员权限", "是" if env["is_admin"] else "**否**"],
                ["平台", env["platform"]],
                ["工作目录", f"`{env['cwd']}`"],
            ],
        )
    )
    out.append("")

    # 2. 设备
    out.append("## 2. 设备与服务")
    out.append("")
    hs = device.get("handshake") or {}
    hs_text = "未执行"
    if hs:
        hs_text = "成功" if hs.get("matched") else f"失败（{hs.get('reason', '未知')}）"
    out.append(
        _md_table(
            ["项目", "值"],
            [
                ["官方服务名", f"`{device.get('service_name') or '未确认'}`"],
                ["服务状态", str(device.get("service_status"))],
                ["串口列表", ", ".join(device.get("ports") or []) or "（未扫描）"],
                ["握手结果", hs_text],
            ],
        )
    )
    out.append("")

    # 3. 注册表快照
    out.append("## 3. 功能注册表快照")
    out.append("")
    counts = registry.get("counts", {})
    out.append(
        "统计：" + "，".join(f"{k} = {v}" for k, v in counts.items() if v)
    )
    out.append("")
    rows = [
        [
            f"`{f['feature_id']}`",
            f["status"],
            "是" if f["protocol_verified"] else "否",
            str(f["last_result"]),
            f["suggested_action"],
        ]
        for f in registry.get("features", [])
    ]
    out.append(_md_table(["feature_id", "状态", "协议已验证", "最近结果", "建议动作"], rows))
    out.append("")

    # 4. 未就绪功能
    out.append("## 4. 未就绪功能与失败详情")
    out.append("")
    attention = report.get("attention") or []
    if not attention:
        out.append("无。所有功能均为 verified。")
        out.append("")
    for item in attention:
        out.append(f"### `{item['feature_id']}` — {item['name']}")
        out.append("")
        out.append(f"- 状态：`{item['status']}`，最近结果：`{item['last_result']}`")
        out.append(f"- 所属模块：`{item['module']}`")
        if item.get("error_summary"):
            out.append(f"- 失败摘要：{item['error_summary']}")
        out.append(f"- 建议动作：**{item['suggested_action']}**")
        out.append("- 复现步骤：")
        for step in item["repro_steps"]:
            out.append(f"  {step}")
        logs = item.get("recent_logs") or []
        if logs:
            out.append("- 最近日志：")
            out.append("```json")
            for entry in logs:
                out.append(json.dumps(entry, ensure_ascii=False))
            out.append("```")
        out.append("")

    # 5. 待验证协议项
    out.append("## 5. 待验证协议项")
    out.append("")
    unmet = report.get("unmet_gates") or []
    if not unmet:
        out.append("无。所有协议闸门均已满足。")
    else:
        out.append(_md_table(["闸门", "阻塞功能"], [[g["label"], ", ".join(g["features"])] for g in unmet]))
        out.append("")
        for gate in unmet:
            out.append(f"- **{gate['label']}**：{gate['how_to_fix']}")
    out.append("")

    # 6. Harness 指令模板
    out.append("## 6. 给 Harness 的修改指令模板")
    out.append("")
    out.append("> 直接把下面整段复制给 AI 助手。默认只建议**禁用**，不自动删代码。")
    out.append("")
    if not attention:
        out.append("```text")
        out.append(harness_instruction("<FEATURE_ID>", "<失败摘要>", "<日志片段>"))
        out.append("```")
    else:
        for item in attention:
            excerpt = ""
            if item.get("recent_logs"):
                first = item["recent_logs"][-1]
                excerpt = f"{first.get('action')} result={first.get('result')} err={first.get('error_code')}"
            out.append("```text")
            out.append(
                harness_instruction(
                    item["feature_id"],
                    item.get("error_summary") or f"status={item['status']}, last_result={item['last_result']}",
                    excerpt,
                )
            )
            out.append("```")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def write_reports(
    report: dict[str, Any],
    out_dir: str | Path = ".",
    *,
    stem: str = "debug_report",
) -> tuple[Path, Path]:
    """写出 ``.md`` 与 ``.json``，返回两个路径。"""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    md_path = directory / f"{stem}.md"
    json_path = directory / f"{stem}.json"

    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return md_path, json_path
