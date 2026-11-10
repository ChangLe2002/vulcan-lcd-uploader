# SPDX-License-Identifier: MIT
"""虚拟环境与依赖自检。

必须在项目虚拟环境内运行：

    .\\.venv_local\\python\\Scripts\\python.exe scripts\\verify_env.py

退出码：
    0 = 全部通过（警告不算失败）
    1 = 存在硬性失败项
"""

from __future__ import annotations

import json
import os
import sys
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_MARKER = ".venv_local"

OK = "PASS"
WARN = "WARN"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


# --------------------------------------------------------------------------- #
# 1. 解释器身份：必须是项目虚拟环境，不能是系统 Python
# --------------------------------------------------------------------------- #
def check_interpreter() -> None:
    exe = Path(sys.executable).resolve()
    prefix = Path(sys.prefix).resolve()

    if VENV_MARKER in exe.parts or VENV_MARKER in prefix.parts:
        record(OK, "sys.executable", str(exe))
        record(OK, "sys.prefix", str(prefix))
    else:
        record(
            FAIL,
            "sys.executable",
            f"{exe} 不在 {VENV_MARKER} 虚拟环境内 —— 拒绝继续，禁止使用系统 Python",
        )

    if sys.base_prefix == sys.prefix:
        record(FAIL, "venv 隔离", "sys.prefix == sys.base_prefix，当前不是虚拟环境")
    else:
        record(OK, "venv 隔离", f"base={sys.base_prefix}")

    ver = sys.version_info
    ver_s = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) in {(3, 10), (3, 11)}:
        record(OK, "Python 版本", ver_s)
    else:
        record(FAIL, "Python 版本", f"{ver_s} 不在 3.10 / 3.11 范围内")

    if sys.maxsize <= 2**32:
        record(FAIL, "架构", "32 位解释器，需要 64 位")
    else:
        record(OK, "架构", "64-bit")


# --------------------------------------------------------------------------- #
# 2. 依赖：版本与可导入性
# --------------------------------------------------------------------------- #
# (发行包名, 导入名, 最低版本, 是否硬性)
REQUIRED = [
    ("pyserial", "serial", "3.5", True),
    ("Pillow", "PIL", "10.4", True),
    ("PySide6-Essentials", "PySide6.QtWidgets", "6.7", True),
    ("nvidia-ml-py", "pynvml", "12.550", True),
    ("psutil", "psutil", "5.9", True),
]

OPTIONAL = [
    ("pyinstaller", "PyInstaller", "6.10"),
    ("pytest", "pytest", "8.0"),
]


def _parse_version(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts)


def check_dist(dist_name: str, import_name: str, min_version: str, hard: bool) -> None:
    try:
        installed = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        record(FAIL if hard else WARN, f"{dist_name}", "未安装")
        return

    if _parse_version(installed) < _parse_version(min_version):
        record(
            FAIL if hard else WARN,
            dist_name,
            f"版本 {installed} < 要求的 {min_version}",
        )
        return

    try:
        __import__(import_name)
    except Exception as exc:  # noqa: BLE001 - 需要把任意导入错误暴露出来
        record(FAIL if hard else WARN, dist_name, f"{installed} 已装但 import {import_name} 失败: {exc!r}")
        return

    record(OK, dist_name, f"{installed}  (import {import_name})")


def check_qtwidgets_runtime() -> None:
    """PySide6 能 import 不代表能创建 QApplication（缺插件时会在运行期崩）。"""
    try:
        from PySide6.QtCore import __version__ as qt_ver  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "PySide6 Qt 版本", f"读取失败: {exc!r}")
        return
    record(OK, "PySide6 Qt 版本", str(qt_ver))


def check_nvml() -> None:
    """驱动侧不可用不算依赖问题，只警告。"""
    try:
        import pynvml  # noqa: PLC0415

        pynvml.nvmlInit()
    except Exception as exc:  # noqa: BLE001
        record(WARN, "NVML 初始化", f"不可用（未装 NVIDIA 驱动或非 N 卡？）: {exc!r}")
        return
    try:
        count = pynvml.nvmlDeviceGetCount()
        names = []
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            raw = pynvml.nvmlDeviceGetName(handle)
            names.append(raw.decode() if isinstance(raw, bytes) else str(raw))
        record(OK, "GPU", f"{count} 张: {', '.join(names) if names else '-'}")
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# 3. 项目文件完整性
# --------------------------------------------------------------------------- #
# (相对路径, 缺失时是否算硬性失败)
# main.py / feature_registry.json 属于后续模块的交付物，缺失只警告。
PROJECT_FILES = [
    ("requirements.txt", True),
    ("README.md", True),
    ("LICENSE", True),
    ("config/settings.default.json", True),
    (".venv_local", True),
    ("main.py", False),
    ("feature_registry.json", False),
]


def check_project_files() -> None:
    for rel, hard in PROJECT_FILES:
        path = PROJECT_ROOT / rel
        if path.exists():
            size = path.stat().st_size if path.is_file() else 0
            record(OK, f"文件 {rel}", f"{size} B" if path.is_file() else "目录")
        else:
            record(FAIL if hard else WARN, f"文件 {rel}", "缺失（后续模块补齐）")


def check_config_json() -> None:
    path = PROJECT_ROOT / "config" / "settings.default.json"
    if not path.is_file():
        record(FAIL, "settings.default.json", "缺失，无法校验")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "settings.default.json", f"JSON 解析失败: {exc!r}")
        return

    proto = data.get("protocol", {})
    cks = proto.get("checksum", {})
    algo = cks.get("algorithm")
    if algo == "sum16_be":
        record(OK, "校验算法配置", "sum16_be（大端，已由实机验证）")
    elif algo == "sum16_le":
        record(
            WARN,
            "校验算法配置",
            "配置写的是 sum16_le（小端），但实机应答证明是 MSB 在前的大端 —— 请修正",
        )
    else:
        record(FAIL, "校验算法配置", f"只允许 16 位累加（sum16_be），实际 {algo!r}；禁止 8 位累加")
    # 握手字节的缺位由 check_protocol_readiness() 统一呈现，避免重复计数。


# --------------------------------------------------------------------------- #
# 4. 协议就绪度：哪些 null / 未验证项还挡着哪个功能
# --------------------------------------------------------------------------- #
#: 注册表不可用时的兜底清单（正常情况下以 feature_registry.json 为准）
FALLBACK_FEATURE_IDS = [
    "gif_upload",
    "static_image",
    "playlist_rotation",
    "gpu_monitor",
    "cpu_monitor",
    "dual_screen_layout",
    "auto_port_scan",
    "service_control",
    "checksum_16le",
    "title_display",
    "ack_wait_optional",
    "venv_bootstrap",
    "pyinstaller_packaging",
]

def _import_policy():
    """从包内导入闸门策略，避免与 features/gate.py 维护两份规则。"""
    src = PROJECT_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from vulcan_lcd.features.gate import audit, evaluate_config  # noqa: PLC0415
    from vulcan_lcd.features.registry import FeatureRegistry, RegistryError  # noqa: PLC0415

    return evaluate_config, audit, FeatureRegistry, RegistryError


def check_protocol_readiness() -> None:
    """打印就绪度表，并只往结果里记一条汇总（避免刷屏警告）。"""
    config_path = PROJECT_ROOT / "config" / "settings.default.json"
    if not config_path.is_file():
        record(WARN, "协议就绪度", "配置缺失，无法评估")
        return
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        record(WARN, "协议就绪度", f"配置无法解析: {exc!r}")
        return

    try:
        evaluate_config, audit, FeatureRegistry, RegistryError = _import_policy()
    except Exception as exc:  # noqa: BLE001 - 包不可用不应阻断环境自检
        record(WARN, "协议就绪度", f"无法加载闸门模块: {exc!r}")
        return

    print("\n-- 协议就绪度 --")
    blocked: set[str] = set()
    for gate in evaluate_config(cfg):
        if gate.ready:
            print(f"[  OK  ] {gate.label}")
        else:
            blocked.update(gate.features)
            print(f"[ 待验证 ] {gate.label}  → 阻塞: {', '.join(gate.features)}")
            print(f"           补齐: {gate.how_to_fix}")

    registry_path = PROJECT_ROOT / "feature_registry.json"
    all_ids = list(FALLBACK_FEATURE_IDS)
    findings: list[str] = []
    if registry_path.is_file():
        try:
            registry = FeatureRegistry.load(registry_path)
        except RegistryError as exc:
            record(WARN, "功能注册表", f"载入失败: {exc}")
        else:
            all_ids = registry.ids()
            statuses: dict[str, int] = {}
            for item in registry:
                statuses[item.status.value] = statuses.get(item.status.value, 0) + 1
                if not item.status.may_write:
                    blocked.add(item.feature_id)
            print("\n  注册表: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
            findings = audit(registry, cfg)
    else:
        record(WARN, "功能注册表", "feature_registry.json 缺失，按兜底清单估算")

    # 派生依赖：轮播 / 双屏都依赖上传能力
    if "gif_upload" in blocked:
        blocked.add("playlist_rotation")
        blocked.add("dual_screen_layout")
    # 打包不属于协议问题，单独看产物文件是否已就位
    if not (PROJECT_ROOT / "main.spec").is_file():
        blocked.add("pyinstaller_packaging")

    ready_features = [f for f in all_ids if f not in blocked]
    print(
        f"\n可写功能: {len(ready_features)}/{len(all_ids)} "
        f"({', '.join(ready_features) if ready_features else '无'})"
    )
    if blocked:
        print(f"被阻挡  : {', '.join(sorted(blocked))}")
        print("说明: 可写 = 配置闸门满足 + 注册表状态允许写。无证据 ≠ 已验证。")
    if findings:
        print("\n  一致性矛盾:")
        for item in findings:
            print(f"    - {item}")
        record(WARN, "注册表一致性", f"{len(findings)} 处矛盾，详见上方")

    record(
        OK if not blocked and not findings else WARN,
        "协议就绪度",
        f"{len(ready_features)}/{len(all_ids)} 功能可写，{len(blocked)} 个被阻挡",
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _force_utf8_stdio() -> None:
    """GBK 控制台下打印中文会 UnicodeEncodeError，这里统一降级为 replace。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 老版本或已重定向时忽略
            pass


def main() -> int:
    _force_utf8_stdio()
    print("=" * 78)
    print("Vulcan LCD Uploader - 环境自检")
    print(f"项目根目录: {PROJECT_ROOT}")
    print("=" * 78)

    check_interpreter()
    print("\n-- 依赖 --")
    for dist, imp, ver, hard in REQUIRED:
        check_dist(dist, imp, ver, hard)
    check_qtwidgets_runtime()
    check_nvml()
    for dist, imp, ver in OPTIONAL:
        check_dist(dist, imp, ver, hard=False)

    print("\n-- 项目文件 --")
    check_project_files()
    check_config_json()
    check_protocol_readiness()

    print("\n" + "=" * 78)
    # Windows PowerShell 5.1 默认不解析 ANSI 转义，故只用纯文本标记。
    width = max(len(n) for _, n, _ in results) if results else 10
    for status, name, detail in results:
        print(f"[{status}] {name.ljust(width)}  {detail}")

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    print("=" * 78)
    print(f"结果: {len(results) - len(fails) - len(warns)} 通过, {len(warns)} 警告, {len(fails)} 失败")

    if fails:
        print("\n失败项（必须修复后才能继续）：")
        for _, name, detail in fails:
            print(f"  - {name}: {detail}")
        bad_names = [name for _, name, _ in fails]
        if any("executable" in n or "venv" in n.lower() for n in bad_names):
            print("\n提示: 请用 .venv_local\\python\\Scripts\\python.exe 运行本脚本，")
            print("      或先执行 scripts\\bootstrap_venv.ps1")
        return 1

    print("\n环境就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
