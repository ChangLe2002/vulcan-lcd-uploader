# SPDX-License-Identifier: MIT
"""「关于」窗口：作者署名、许可证、目录说明。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..meta import (
    DEFAULT_INSTALL_DIR,
    APP_AUTHOR,
    APP_AUTHOR_FULL,
    APP_LICENSE,
    APP_NAME,
    APP_NAME_EN,
    APP_VERSION,
    PROJECT_TAGLINE,
    PROJECT_URL,
    runtime_folder_rows,
)
from . import theme

__all__ = ["AboutDialog", "about_html"]


def about_html(install_dir: Path | str | None = None) -> str:
    """生成关于窗口的富文本（目录按实际安装位置替换占位符）。"""
    base = str(install_dir) if install_dir else "<安装目录>"
    rows = "".join(
        f"<tr><td style='color:#59cfff; padding:3px 10px 3px 0; white-space:nowrap'>{name}</td>"
        f"<td style='padding:3px 10px 3px 0; white-space:nowrap'><code>{path}</code></td>"
        f"<td style='color:#7c8798'>{desc}</td></tr>"
        for name, path, desc in runtime_folder_rows()
    )
    return f"""
<style>
  body {{ color:#e8edf5; font-family:"Microsoft YaHei UI"; font-size:12px; line-height:1.65; }}
  h2 {{ color:#fcee0a; font-size:15px; margin:0 0 4px 0; }}
  h3 {{ color:#59cfff; font-size:12px; margin:14px 0 4px 0; }}
  p, td {{ color:#c8d2e0; }}
  code {{ color:#fcee0a; background:#161b23; padding:1px 4px; }}
  .muted {{ color:#7c8798; font-size:11px; }}
</style>

<h2>{APP_NAME}</h2>
<p class="muted">{APP_NAME_EN} · v{APP_VERSION}</p>
<p>{PROJECT_TAGLINE}</p>

<h3>作者</h3>
<p><b>{APP_AUTHOR}</b>（Changle）　·　非官方个人项目</p>

<h3>许可证</h3>
<p>{APP_LICENSE} License —— 可自由使用、修改、分发，保留版权声明即可。<br>
项目地址：<code>{PROJECT_URL}</code></p>

<h3>安装/运行会创建哪些文件</h3>
<p>当前安装目录：<code>{base}</code></p>
<table cellspacing="0" cellpadding="0">
{rows}
</table>
<p class="muted">上表的「安装目录」就是本程序当前所在的实际位置（不同电脑会不同）。
绿色包的默认位置是 <code>{DEFAULT_INSTALL_DIR}</code>；把程序整个文件夹移到别处也能正常运行，
配置与日志会跟着走。</p>
<p class="muted">提示：卸载不会删除你上传到「屏幕」上的图片；屏幕内部存储需要在本软件的
「清理设备缓存」里处理。</p>

<p class="muted">本程序不修改显卡固件/VBIOS/SPI Flash，也不提供刷机功能；使用本工具属于非官方用法，风险自负。</p>

"""


class AboutDialog(QDialog):
    """深色风格的关于窗口。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        install_dir: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self._install_dir = Path(install_dir) if install_dir else None
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setStyleSheet(theme.STYLE_SHEET)
        self.setMinimumSize(720, 560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel(f"{APP_NAME}  v{APP_VERSION}")
        title.setStyleSheet(f"color:{theme.ACCENT}; font-size:15px; font-weight:700;")
        layout.addWidget(title)

        author = QLabel(f"作者：{APP_AUTHOR}　·　{APP_LICENSE} License　·　{APP_NAME_EN}")
        author.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(author)

        view = QTextBrowser()
        view.setHtml(about_html(install_dir))
        view.setOpenExternalLinks(True)
        view.setStyleSheet(
            f"QTextBrowser {{ background:{theme.PANEL}; border:1px solid {theme.BORDER};"
            f" border-radius:4px; padding:8px; color:{theme.TEXT}; }}"
        )
        layout.addWidget(view, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)

        if self._install_dir is not None:
            open_dir = QPushButton("打开安装目录")
            open_dir.setMinimumWidth(120)
            open_dir.setMinimumHeight(30)
            open_dir.clicked.connect(self._open_install_dir)
            footer.addWidget(open_dir)

        close = QPushButton("关闭")
        close.setMinimumWidth(90)
        close.setMinimumHeight(30)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _open_install_dir(self) -> None:
        """在资源管理器里打开程序所在目录。"""
        if self._install_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._install_dir)))
