# SPDX-License-Identifier: MIT
"""入口：解析参数 → 装配上下文 → 检查权限 → 起窗口。

启动顺序刻意固定，便于定位"打开就崩"这类问题：

1. 解析命令行（``--debug`` / ``--dry-run`` / ``--feature``）；
2. 装配上下文（配置 + 注册表 + 闸门 + 日志）——失败就打印原因并退出，不弹空窗口；
3. 权限检查：非管理员时**询问**是否以管理员重启（不静默提权，也不静默降级）；
4. 创建 QApplication 与主窗。

``--dry-run`` 下不询问提权——空跑不需要碰硬件。
"""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from vulcan_lcd.app import AppError, build_context, describe_environment  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession, parse_session  # noqa: E402
from vulcan_lcd.system.privileges import is_admin  # noqa: E402


def _ask_elevation() -> bool:
    """弹窗问是否以管理员重启。返回 True 表示已请求提权、本进程应退出。"""
    try:
        import ctypes  # noqa: PLC0415

        result = ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None,
            "本工具需要管理员权限才能接管 iGameCenter 服务。\n\n"
            "是否以管理员身份重新启动？\n（选「否」将以只读模式继续，无法控制屏幕）",
            "权限不足",
            0x00000004 | 0x00000030,  # MB_YESNO | MB_ICONWARNING
        )
        if result != 6:  # IDYES
            return False

        params = " ".join(f'"{a}"' if " " in a else a for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", sys.executable, f'"{Path(sys.argv[0]).resolve()}" {params}'.strip(), None, 1
        )
        return True
    except Exception:  # noqa: BLE001 - 非 Windows 或 UI 不可用
        return False


def _self_check() -> int:
    """``--check``：不加载 Qt，只验证装配是否完好。

    打包成 GUI 子系统后 stdout 不可见，所以结果同时写入
    ``logs/startup_check.txt``，退出码供脚本判断（0=通过）。
    """
    from vulcan_lcd.app import is_frozen, resource_root, writable_root  # noqa: PLC0415

    lines: list[str] = []

    def say(text: str = "") -> None:
        lines.append(text)
        print(text)

    say("=" * 60)
    say("Vulcan LCD Uploader - 启动自检")
    say("=" * 60)
    say(f"frozen        : {is_frozen()}")
    say(f"executable    : {sys.executable}")
    say(f"resource_root : {resource_root()}")
    say(f"writable_root : {writable_root()}")
    say(f"venv          : {sys.prefix != sys.base_prefix}")

    def flush(code: int) -> int:
        try:
            out_dir = writable_root() / "logs"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "startup_check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001 - 写不出诊断文件不应改变退出码
            pass
        return code

    try:
        ctx = build_context(DebugSession(dry_run=True), console_log=True)
    except AppError as exc:
        say(f"[FAIL] 装配失败: {exc}")
        return flush(2)

    say(f"features      : {len(ctx.registry)}（可写 {len(ctx.gate.writable())}）")
    say(f"service       : {ctx.service_name}")
    say(f"log_dir       : {ctx.log_dir}")
    say(f"config warn   : {len(ctx.config_problems)}")

    # 打包产物常常缺 DLL/数据文件，这里顺手验证关键依赖能否导入
    import importlib  # noqa: PLC0415

    for module in ("serial", "PIL", "PySide6.QtWidgets", "pynvml", "psutil"):
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001
            say(f"[FAIL] import {module}: {exc}")
            return flush(3)
        say(f"import ok     : {module}")

    say("")
    say("自检通过。")
    return flush(0)


def _encode_diagnostic(path: str) -> int:
    """打包版编码自检：打印耗时/帧数，用于排查"卡在编码"。"""
    import time

    from vulcan_lcd.media.encode import encode_media_to_pak, find_ffmpeg

    print(f"ffmpeg: {find_ffmpeg()}")
    start = time.perf_counter()
    try:
        result = encode_media_to_pak(Path(path), target_fps=0)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 编码异常：{exc}")
        return 1
    print(
        f"编码完成：{time.perf_counter() - start:.2f}s, "
        f"{result.frames} 帧, {result.size / 1024 / 1024:.2f} MB, q~{result.quality}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # --smoke[=毫秒]：起窗后自动退出。用于打包产物的无人值守验证，
    # 否则 GUI 进程会一直活着，脚本永远等不到结束。
    smoke_ms = 0
    filtered: list[str] = []
    for item in args:
        if item == "--smoke" or item.startswith("--smoke="):
            _, _, value = item.partition("=")
            smoke_ms = int(value) if value.isdigit() else 3000
        else:
            filtered.append(item)
    # --ui=old|new：切换界面（默认新界面；旧界面保留以便回退）
    ui_style = "new"
    rest: list[str] = []
    for item in filtered:
        if item.startswith("--ui"):
            _, _, value = item.partition("=")
            ui_style = value.strip().lower() or "new"
        else:
            rest.append(item)
    args = rest

    if "--check" in args:
        return _self_check()

    # --encode <路径>：只做一次编码并退出。用于排查"卡在编码"这类问题，
    # 打包产物也能跑（`VulcanLCDUploader.exe --encode x.gif`）。
    if "--encode" in args:
        index = args.index("--encode")
        if index + 1 >= len(args):
            print("用法：--encode <媒体文件路径>", file=sys.stderr)
            return 2
        return _encode_diagnostic(args[index + 1])

    session = parse_session(args)

    try:
        ctx = build_context(session)
    except AppError as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        print("请检查 config/settings.default.json 与 feature_registry.json 是否存在且合法。", file=sys.stderr)
        return 2

    admin = is_admin()
    if not admin and not session.dry_run and sys.platform == "win32":
        if _ask_elevation():
            return 0

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415 - 延迟导入，避免无 GUI 场景加载 Qt

    from vulcan_lcd.features.ui_prefs import (  # noqa: PLC0415
        DISCLAIMER_ACCEPTED,
        STANDALONE,
        load_prefs,
    )
    from vulcan_lcd.system.service_control import set_standalone  # noqa: PLC0415
    from vulcan_lcd.ui.main_window import MainWindow  # noqa: PLC0415
    from vulcan_lcd.ui2.window import NewMainWindow  # noqa: PLC0415

    ctx.logger.info(
        "app_start",
        result="ok",
        debug=session.debug,
        dry_run=session.dry_run,
        admin=admin,
        env=describe_environment(),
    )

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])

    # 应用图标（任务栏 / 标题栏 / 托盘都跟着用）
    try:
        from pathlib import Path as _Path  # noqa: PLC0415

        from PySide6.QtGui import QIcon  # noqa: PLC0415

        from vulcan_lcd.app import resource_root  # noqa: PLC0415

        icon_path = _Path(resource_root()) / app.ico
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:  # noqa: BLE001 - 图标缺失不影响启动
        pass
    # 显式指定字体：样式表设置字体会丢掉字体族，某些控件会回退到衬线体，
    # 数字被渲染成 l/O 之类怪字形（实测）。
    from PySide6.QtGui import QFont  # noqa: PLC0415
    app.setFont(QFont("Microsoft YaHei UI", 9))
    # 系统区域是 zh_HK 时，Qt 会用「杭州数字」做本地数字（120 → 〡〢〇），
    # 导致 QSpinBox 显示成 〩〩、解析成乱值。强制用阿拉伯数字的区域设置。
    from PySide6.QtCore import QLocale  # noqa: PLC0415
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app.setApplicationName("Vulcan LCD Uploader")
    app.setApplicationDisplayName("火神智屏图传工具")

    # 独立模式：不管理官方服务（在创建任何窗口之前生效）
    try:
        set_standalone(bool(load_prefs(ctx.root).get(STANDALONE, False)))
    except Exception:  # noqa: BLE001 - 偏好读取失败不影响启动
        pass

    # 首次启动：强制阅读 20 秒免责声明与使用说明（接受后写入偏好，不再打扰）
    try:
        from vulcan_lcd.ui2.disclaimer import DisclaimerDialog  # noqa: PLC0415

        _prefs = load_prefs(ctx.root)
        if not _prefs.get(DISCLAIMER_ACCEPTED, False):
            dialog = DisclaimerDialog(seconds=20, root=ctx.root)
            dialog.exec()
    except Exception as exc:  # noqa: BLE001 - 声明弹窗失败不该阻止启动
        ctx.logger.warning('disclaimer_failed', detail=str(exc))

    if ui_style == "old":
        window = MainWindow(ctx, admin=admin)
    else:
        window = NewMainWindow(ctx)
    window.show()

    if smoke_ms:
        from PySide6.QtCore import QTimer  # noqa: PLC0415

        QTimer.singleShot(smoke_ms, window.close)
        QTimer.singleShot(smoke_ms + 500, app.quit)

    code = app.exec()

    ctx.logger.info("app_exit", result="ok", exit_code=code)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
