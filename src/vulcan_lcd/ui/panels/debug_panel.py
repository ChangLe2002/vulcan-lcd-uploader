# SPDX-License-Identifier: MIT
"""调试面板：功能状态 / 原始收发 / 日志过滤 / 导出报告 / 人工发送。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...app import AppContext
from ...core.port_scanner import list_serial_ports
from ...diagnostics.logging_setup import read_events
from ...diagnostics.report import ReportContext, build_report, write_reports
from ..link import SerialLink
from ..widgets import HexView, Section

__all__ = ["DebugPanel"]

_STATUS_COLORS = {
    "verified": "#e8f5e9",
    "experimental": "#fff8e1",
    "disabled": "#ffebee",
    "removed": "#eceff1",
}


class DebugPanel(Section):
    def __init__(self, ctx: AppContext, link: SerialLink, parent: QWidget | None = None) -> None:
        super().__init__("调试", parent)
        self._ctx = ctx
        self._link = link
        self._build()
        self.reload_features()
        self.reload_logs()

    # -- 构建 ------------------------------------------------------------- #
    def _build(self) -> None:
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["feature_id", "状态", "协议已验证", "最近结果", "建议动作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(220)
        self.body.addWidget(self.table)

        self.hex = HexView()
        self.hex.setMinimumHeight(140)
        self.body.addWidget(self.hex)

        row = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("全部 feature", None)
        for feature in self._ctx.registry:
            self.filter.addItem(feature.feature_id, feature.feature_id)
        self.btn_logs = QPushButton("刷新日志")
        self.btn_export = QPushButton("导出调试报告")
        row.addWidget(QLabel("日志过滤"))
        row.addWidget(self.filter, 1)
        row.addWidget(self.btn_logs)
        row.addWidget(self.btn_export)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("人工发送：十六进制，例如 5A9FA90004E01F02A5")
        self.chk_risk = QCheckBox("我理解风险")
        self.btn_manual = QPushButton("发送")
        row2.addWidget(self.manual, 1)
        row2.addWidget(self.chk_risk)
        row2.addWidget(self.btn_manual)
        self.body.addLayout(row2)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#666;")
        self.body.addWidget(self.hint)

        self.btn_logs.clicked.connect(self.reload_logs)
        self.btn_export.clicked.connect(self.export_report)
        self.btn_manual.clicked.connect(self.send_manual)
        self.filter.currentIndexChanged.connect(self.reload_logs)
        self._apply_gate()

    def _apply_gate(self) -> None:
        allowed = self._ctx.session.allows_manual_hex
        self.btn_manual.setEnabled(allowed)
        self.manual.setEnabled(allowed)
        self.chk_risk.setEnabled(allowed)
        if allowed:
            self.hint.setText(
                "人工发送仅在调试模式可用，需勾选确认。所有人工发送记录为 feature_id=manual_raw_hex。"
            )
        else:
            self.hint.setText("人工发送已禁用：仅 --debug 模式可用（生产模式一律禁止）。")

    # -- 功能表 ----------------------------------------------------------- #
    def reload_features(self) -> None:
        records = list(self._ctx.registry)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                record.feature_id,
                record.status.value,
                "是" if record.protocol_verified else "否",
                record.last_result,
                record.suggested_action,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setBackground(_color(_STATUS_COLORS.get(record.status.value, "#ffffff")))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    # -- 日志 ------------------------------------------------------------- #
    def reload_logs(self) -> None:
        feature_id = self.filter.currentData()
        log_path = self._ctx.log_dir / f"debug_{date.today():%Y%m%d}.log"
        if not Path(log_path).is_file():
            self.hex.append_text("（今天还没有日志）")
            return
        try:
            events = read_events(log_path, feature_id=feature_id, limit=50)
        except Exception as exc:  # noqa: BLE001
            self.hex.append_text(f"读取日志失败：{exc}")
            return
        self.hex.clear_all()
        for event in events:
            self.hex.append_text(
                f"{event.get('timestamp','')[11:23]} {event.get('level',''):<7} "
                f"{event.get('feature_id') or '-':<18} {event.get('action','')}  "
                f"result={event.get('result')}"
                + (f" err={event.get('error_code')}" if event.get("error_code") else "")
            )

    # -- 导出 ------------------------------------------------------------- #
    def export_report(self) -> None:
        try:
            ports = tuple(p.device for p in list_serial_ports())
        except Exception:  # noqa: BLE001
            ports = ()

        report = build_report(
            ReportContext(
                registry=self._ctx.registry,
                config=self._ctx.config,
                session=self._ctx.session,
                logger=self._ctx.logger,
                ports=ports,
                handshake=None,
                service_name=self._ctx.service_name,
                service_status="unknown（未查询）",
            )
        )
        md_path, json_path = write_reports(report, self._ctx.root)
        self._ctx.logger.info("report_exported", result="ok", md=str(md_path), json=str(json_path))
        QMessageBox.information(
            self,
            "已导出",
            f"已生成：\n{md_path}\n{json_path}\n\n报告末尾含可直接复制的 Harness 指令模板。",
        )

    # -- 人工发送 --------------------------------------------------------- #
    def send_manual(self) -> None:
        text = self.manual.text().strip()
        if not text:
            return
        try:
            payload = bytes.fromhex(text.replace(" ", "").replace(":", ""))
        except ValueError:
            QMessageBox.warning(self, "格式错误", "不是合法的十六进制字符串。")
            return
        if not self.chk_risk.isChecked():
            QMessageBox.warning(self, "需要确认", "请先勾选「我理解风险」。")
            return
        confirm = QMessageBox.question(
            self,
            "二次确认",
            f"确认向串口发送 {len(payload)} 字节？\n\n{payload.hex(' ')}\n\n"
            "未验证的字节可能导致设备无响应，需要重新插拔。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self._link.send_manual_hex(payload, confirmed=True):
            self.hex.append_hex("tx(manual)", payload, "人工发送")


def _color(hex_color: str):  # noqa: ANN202 - Qt 类型在运行时才可用
    from PySide6.QtGui import QColor  # noqa: PLC0415

    return QColor(hex_color)
