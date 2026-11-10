# SPDX-License-Identifier: MIT
"""首次启动的免责声明 / 使用说明对话框。

设计约束：
* 必须停留 ``seconds`` 秒（默认 20）才能关闭 —— 期间点 X、按 Esc、点按钮都无效；
* 倒计时结束前按钮显示剩余秒数并保持禁用；
* 只在第一次启动时出现（接受后写入 ``ui_prefs.json``）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import theme

__all__ = ["DisclaimerDialog", "DISCLAIMER_HTML"]

DISCLAIMER_HTML = """
<style>
  body { color: #e8edf5; font-family: "Microsoft YaHei UI"; font-size: 12px; line-height: 1.7; }
  h2 { color: #fcee0a; font-size: 14px; margin: 16px 0 6px 0; }
  h3 { color: #59cfff; font-size: 12px; margin: 12px 0 4px 0; }
  p, li { color: #c8d2e0; }
  b { color: #ffffff; }
  code { color: #fcee0a; background: #161b23; padding: 1px 4px; }
  .warn { color: #ffb020; }
  .small { color: #7c8798; font-size: 11px; }
</style>

<h2>一、免责声明</h2>
<p>
<b>本软件是第三方非官方工具，与七彩虹（Colorful）/ iGame 及其关联公司没有任何隶属、授权或合作关系。</b>
它通过逆向分析得到的串口协议直接与「火神」显卡智屏通信，属于个人学习与自用性质的项目。
</p>
<ul>
  <li>软件按「现状」提供，<b>不提供任何明示或暗示的担保</b>，包括但不限于适用性、稳定性、不侵权。</li>
  <li>使用本软件造成的任何后果（屏幕显示异常、设备需要断电重启、数据丢失、保修争议等）
      由<b>使用者自行承担</b>；作者不承担任何直接或间接责任。</li>
  <li>请先备份你设备上原有的图片/动画。本工具会向屏幕写入文件，并可能删除设备上的
      `img2` 及之后的槽位（清理缓存功能，需二次确认）。</li>
  <li class="warn">软件不对设备固件、VBIOS、SPI Flash 做任何读写，也不提供刷机/恢复出厂类功能；
      但任何非官方写入都存在风险，请自行评估。</li>
  <li>请勿将本软件用于商业分发或二次售卖；如需转载，请保留作者信息与本文档。</li>
</ul>

<h2>二、这款软件是做什么的</h2>
<p>
iGame 火神 RTX 50 系显卡附带一块 <b>1024×240 的 LCD 副屏</b>（设备自报型号 LCD5A）。
官方只能用它自带的 iGame Center 上传图片和动画，而本工具让你可以：
</p>
<ul>
  <li>把任意 <b>GIF / PNG / JPEG</b> 上传到屏幕并循环播放；</li>
  <li>做<b>播放列表轮播</b>，每张图可单独设置停留秒数；</li>
  <li>把 <b>GPU / CPU 的实时数据</b>交给屏幕自己渲染（不用上传图片，也不依赖官方软件）；</li>
  <li>读取设备信息、调亮度、设置开机图、切换开机动画；</li>
  <li>清理设备上的无效缓存，把被占用的空间收回来。</li>
</ul>

<h2>三、各项功能怎么用</h2>

<h3>01 设备连接</h3>
<p>
启动后自动检测串口（形如 <code>COM5</code>）。这一栏只做展示，不需要手动连接：
</p>
<ul>
  <li><b>串口号 · USB-SERIAL</b>：绿点表示已识别到设备。</li>
  <li><b>iGameCenterService</b>：官方服务状态。上传时本工具会临时把它停掉（串口是独占的），
      传完自动恢复；如果显示 <b>独立模式</b>，说明你勾选了「文件 → 独立模式」，此时完全不碰官方服务。</li>
  <li><b>可用内存</b>：屏幕剩余空间（每次上传/清理后更新）。</li>
  <li><b>扫描</b>：手动重新检测一次串口（平时 10 秒自动刷新）。</li>
</ul>

<h3>02 硬件监控</h3>
<ul>
  <li>本机直接读取传感器（NVIDIA NVML + psutil），<b>不需要 iGame Center 在运行</b>。</li>
  <li>三条彩色进度条：CPU 占用 / GPU 占用 / 内存占用，前面是温度。</li>
  <li><b>上屏内容</b> 下拉有两种布局：
    <br>· <code>显卡：负载/温度/频率</code> —— 屏幕上显示显卡三个数值；
    <br>· <code>处理器：负载/频率/内存（轮显）</code> —— 两页轮流显示。</li>
  <li>点 <b>上屏</b> 开始把数值交给屏幕（设备自己画，不是传图片）；再点一次停止。</li>
</ul>

<h3>03 播放列表</h3>
<ul>
  <li><b>添加</b> 选多个 GIF/图片，<b>移除</b> / <b>清空</b> 管理列表。</li>
  <li><b>停留</b> 列可双击修改，每一项单独生效；上方「停留 [5] 秒」是新增项时的默认值。</li>
  <li>点 <b>轮播</b> 开始：工具先全部编码上传 → 校验设备清单 → 静置 → 按停留时间循环切换。</li>
  <li>点 <b>停止</b> 结束轮播。</li>
</ul>

<h3>04 投屏内容</h3>
<ul>
  <li><b>选择文件</b>（或从 <b>素材库</b> 下拉选最近用过的）→ 上方画布立即显示预览。</li>
  <li><b>适配</b>固定为「原始尺寸」：与官方一致，按素材原始像素贴入，屏幕显示时自动裁掉黑边铺满。</li>
  <li><b>旋转</b>：面板是倒装的，默认「不旋转」即已帮你转过 180°；如果你自己把图转反了，
      选「旋转180°」可以再翻回来。<b>切换后预览会立刻跟着变。</b></li>
  <li><b>上传到屏幕</b>：编码 → 上传 → 切到屏幕显示。上传期间按钮变成「停止显示」。</li>
  <li>中间<b>机箱图上的小屏</b>就是竖屏预览，点击可放大查看。</li>
  <li><b>文字投屏</b>：输入 A-Z、0-9、小数点、空格（其它字符会被忽略），点发送。
      发送时会自动停官方服务 → 开串口 → 发帧 → 恢复服务，不用你手动操作。</li>
</ul>

<h3>05 设备设置</h3>
<ul>
  <li><b>亮度</b>：0–10，拖动后点「应用」，会写回并读回校验。</li>
  <li><b>开机图</b>：先点「读取设备」拿到设备上的文件清单，再在下拉里选一个，点「设置」。</li>
  <li><b>切换 Vulcan</b> / <b>播放动画</b>：设置/播放官方开机动画（部分机型只支持 Vulcan 主题）。</li>
</ul>

<h3>06 调试</h3>
<p>实时显示最新日志；点「导出日志」会生成 <code>debug_report.md / .json</code>，出问题时把它发给开发者即可定位。</p>

<h3>文件菜单</h3>
<ul>
  <li><b>清理设备缓存…</b>：两种模式 —— 只删本工具上传过的（安全）／彻底清理（与官方垃圾桶一致，删 <code>img2</code> 及以后，回收空间）。</li>
  <li><b>独立模式（不管理官方服务）</b>：没装或不用 iGame Center 时勾选，工具就完全不去碰它。</li>
  <li><b>关闭窗口时最小化到托盘</b>（默认开启）、<b>开机自启动</b>。</li>
  <li><b>导出调试报告</b>、<b>退出</b>。</li>
</ul>

<h3>托盘 / 资源占用</h3>
<ul>
  <li>关闭窗口默认最小化到托盘，双击图标恢复。</li>
  <li>窗口隐藏后所有轮询会停止：<b>托盘状态 CPU 0%、内存约 20 MB</b>；窗口可见时约 1% 单核。</li>
</ul>

<h2>四、协议来源与合规说明</h2>
<p>
本软件只使用<b>已经公开或经自己抓包/反编译验证</b>的协议事实，不发送任何猜测性指令：
</p>
<ul>
  <li>串口参数、帧结构（<code>5A 9F A9</code> 帧头、长度、16 位累加和）、分辨率等事实性参数，
      来自一篇公开的逆向分析文章（CSDN，作者 whgjjim，2025-06，CC BY-SA 4.0）。
      <b>本项目只引用其中的事实性参数，未转载、未改写其原文表述</b>，因此不构成对 CC BY-SA 内容的演绎。</li>
  <li>参考了开源项目 <b>wiselike/LCD</b>（MIT）的协议事实与收发流程，<b>未复制其源码</b>，本项目为独立的 Python 实现。</li>
  <li>功能细节（pak 容器格式、槽位规则、设备端渲染帧、清理缓存行为）来自对官方 .NET 程序集的
      <b>反编译查证</b>与 USB 抓包，结论都记录在 <code>docs/PROTOCOL.md</code>（含原始字节证据）。</li>
  <li>本项目自身以 <b>MIT 许可证</b>发布；第三方组件许可见 <code>THIRD_PARTY_NOTICES.md</code>。</li>
  <li>软件<b>不联网、不上报、不收集任何数据</b>；除「停止/启动官方服务」外不需要管理员权限。</li>
  <li>所有串口写操作都有闸门：只有登记为「已验证」的功能才允许写设备，另有 <code>--dry-run</code> 只读模式。</li>
</ul>

<h2>五、它是怎么做出来的</h2>
<ul>
  <li><b>编程语言</b>：Python 3.11（主程序）+ 少量 C#/.NET 仅用于阅读官方程序集，不参与运行。</li>
  <li><b>界面</b>：PySide6（Qt 6）—— 自绘按钮、深色主题、QSS 样式表。</li>
  <li><b>串口</b>：pyserial；按逆推出的帧格式自己组包、校验、分包写入。</li>
  <li><b>图像</b>：Pillow 解码 GIF 各帧；<b>ffmpeg</b> 按官方同样的滤镜链编码 JPEG
      （<code>rotate=180 → pad 1024×240 → fps=30 → qscale 6</code>），再按官方 pak 容器格式打包。</li>
  <li><b>监控</b>：NVIDIA NVML 读显卡、psutil 读 CPU/内存；按反编译得到的帧结构交给屏幕自己渲染。</li>
  <li><b>打包</b>：PyInstaller（onedir）生成免安装程序；Inno Setup / 脚本安装包做安装程序。</li>
  <li><b>质量</b>：441 项自动化测试覆盖协议、编码、状态机与界面结构。</li>
</ul>

<h2>六、使用前请确认</h2>
<ul>
  <li>显卡为 iGame 火神 RTX 50 系且副屏正常显示（其它机型不保证可用）。</li>
  <li>若同时开着 <b>「游戏加加」(GamePP)</b> 等带 overlay 注入的软件，可能出现崩溃，请先退出。</li>
  <li>设备文件表偶尔会卡住（写入有应答但不建档），<b>断电 10 秒</b>即可恢复。</li>
</ul>

<p class="small">
继续即表示你已阅读并同意上述条款。此提示只在首次启动时显示，之后可在「帮助 → 免责声明」中重新查看。
</p>
"""


class DisclaimerDialog(QDialog):
    """首次启动的强制阅读窗口：倒计时结束前无法关闭。"""

    accepted_once = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        seconds: int = 20,
        root: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self._root = Path(root) if root is not None else None
        self._remaining = max(0, int(seconds))
        self._unlocked = self._remaining == 0

        self.setWindowTitle("使用前必读 · 免责声明与功能说明")
        self.setStyleSheet(theme.STYLE_SHEET)
        self.setMinimumSize(780, 640)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("使用前必读")
        title.setStyleSheet(f"color:{theme.ACCENT}; font-size:15px; font-weight:700;")
        layout.addWidget(title)

        subtitle = QLabel(
            "请花 20 秒阅读以下内容。倒计时结束前窗口无法关闭。"
            if seconds > 0
            else "请阅读以下内容。"
        )
        subtitle.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(subtitle)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(DISCLAIMER_HTML)
        self.view.setStyleSheet(
            f"QTextBrowser {{ background:{theme.PANEL}; border:1px solid {theme.BORDER};"
            f" border-radius:4px; padding:8px; color:{theme.TEXT}; }}"
        )
        layout.addWidget(self.view, 1)

        footer = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{theme.WARN}; font-size:11px;")
        footer.addWidget(self.hint, 1)

        self.btn_accept = QPushButton()
        self.btn_accept.setEnabled(self._unlocked)
        self.btn_accept.setMinimumWidth(220)
        self.btn_accept.setMinimumHeight(34)
        self.btn_accept.clicked.connect(self._on_accept)
        footer.addWidget(self.btn_accept)
        layout.addLayout(footer)

        self._update_button()
        if self._remaining > 0:
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    # -- 倒计时 ----------------------------------------------------------- #
    def _update_button(self) -> None:
        if self._unlocked:
            self.btn_accept.setText("我已阅读并同意")
            self.btn_accept.setStyleSheet(
                f"QPushButton {{ background:{theme.ACCENT}; color:#0a0a0a;"
                " border:none; border-radius:4px; font-weight:700; }}"
            )
        else:
            self.btn_accept.setText(f"我已阅读并同意（{self._remaining} 秒）")
            self.btn_accept.setStyleSheet(
                f"QPushButton {{ background:#191d24; color:{theme.MUTED};"
                f" border:1px solid {theme.BORDER}; border-radius:4px; }}"
            )

    def _tick(self) -> None:
        self._remaining = max(0, self._remaining - 1)
        if self._remaining == 0:
            self._unlocked = True
            self.btn_accept.setEnabled(True)
            if hasattr(self, "_timer"):
                self._timer.stop()
        self._update_button()

    # -- 关闭保护 --------------------------------------------------------- #
    def _on_accept(self) -> None:
        if not self._unlocked:
            return
        if self._root is not None:
            from ..features.ui_prefs import DISCLAIMER_ACCEPTED, load_prefs, save_prefs

            prefs = load_prefs(self._root)
            prefs[DISCLAIMER_ACCEPTED] = True
            save_prefs(self._root, prefs)
        self.accepted_once.emit()
        self.accept()

    def closeEvent(self, event: object) -> None:  # noqa: N802
        if not self._unlocked:
            # 倒计时期间点 X 不关闭，改为提示还剩几秒
            self.hint.setText(f"请阅读完（还剩 {self._remaining} 秒）")
            event.ignore()  # type: ignore[attr-defined]
            return
        super().closeEvent(event)  # type: ignore[arg-type]

    def reject(self) -> None:  # Esc 也走这里
        if not self._unlocked:
            self.hint.setText(f"请阅读完（还剩 {self._remaining} 秒）")
            return
        super().reject()

    def keyPressEvent(self, event: object) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4) and not self._unlocked:  # type: ignore[attr-defined]
            self.hint.setText(f"请阅读完（还剩 {self._remaining} 秒）")
            event.ignore()  # type: ignore[attr-defined]
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]
