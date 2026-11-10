# SPDX-License-Identifier: MIT
"""批量反编译 iGame 自研程序集（跳过框架/第三方库）。

用法：python decompile_all.py
输出：F:\\shuchu\\decomp_all\\<程序集名>\\  以及 _manifest.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ILSPY = r"F:\shuchu\tools\ilspy_winx64\tools\any\win-x64\ilspycmd.exe"
SRC = Path(r"E:\iGameCenter")
OUT = Path(r"F:\shuchu\decomp_all")
PROJECTS = OUT / "src"

# iGame 自研（或必须读的封装层）；其余框架/第三方/Vendor SDK 不反编译
TARGETS = [
    "iGameCenter.exe",
    "iGameCenter.Service.exe",
    "iGameCenter.Resource.dll",
    "iGameCenter.Hardware.dll",
    "iGameCenter.Web.dll",
    "iGameCenter.ConfigManager.dll",
    "iGameCenter.Contracts.dll",
    "iGameCenter.DB.dll",
    "iGameCenter.Utils.dll",
    "iGameCenter.Share.dll",
    "iGameCenter.PresentMonInterface.dll",
    "iGameCenter.Update.exe",
    "iGameAPI.LCD.CSharp.dll",
    "iGameAPI.Contracts.dll",
    "iGameAPI.NVAPI.CSharp.dll",
    "iGameAPI.UpdateDevice.CSharp.dll",
    "iGameAPI.Notebook.Common.dll",
    "iGameAPI.Notebook.Contracts.dll",
    "iGameAPI.AMDX3DCCD.dll",
    "iGameAPI.MBoard.WinRing0.dll",
    "iGCExtendsAPI.dll",
    "iGCExtendsModels.dll",
    r"iGCBootstrapper\iGCBootstrapper.exe",
    r"iGCBootstrapper\iGCActive.exe",
    r"ImageProcessor\iGameCenter.ImageProcessor.exe",
    r"iGameAPI\Audio\iGameAPI.Audio.CSharp.dll",
    r"iGameAPI\MBoardOverclock\iGameAPI.MBoard.Overclock.dll",
    r"iGameAPI\MBoardOverclock\ProfileHelperModel.dll",
    r"iGameAPI\Bluetooth\iGameAPI.Bluetooth.WinRT.dll",
    r"iGameAPI\Notebook\NotebookSDK\Clevo\iGameAPI.Clevo.dll",
    r"iGameAPI\Notebook\NotebookSDK\N14\iGameAPI.N14.dll",
    r"iGameAPI\Notebook\NotebookSDK\N15_25\iGameAPI.N15_25.dll",
    r"iGameAPI\Notebook\NotebookSDK\Clevo_26\iGameAPI.Clevo_26.dll",
    r"iGameAPI\Notebook\NotebookSDK\S1Pro\iGameAPI.S1Pro.dll",
    r"iGameAPI\Notebook\NotebookSDK\Quanta_26\iGameAPI.Quanta_26.dll",
    r"iGameAPI\Notebook\WaterCooling\iGameAPI.Bluetooth.WaterCooling.dll",
]


def main() -> int:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rel in TARGETS:
        src = SRC / rel
        name = src.stem
        dest = PROJECTS / name
        started = time.time()
        if not src.exists():
            manifest.append({"assembly": rel, "status": "missing"})
            print(f"[skip] {rel} 不存在", flush=True)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [ILSPY, "-p", "-o", str(dest), str(src)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, encoding="utf-8", errors="replace")
            ok = proc.returncode == 0
            err = "" if ok else (proc.stderr or proc.stdout)[-400:]
        except subprocess.TimeoutExpired:
            ok, err = False, "timeout 3600s"
        elapsed = round(time.time() - started, 1)
        files = list(dest.rglob("*.cs"))
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        manifest.append(
            {
                "assembly": rel,
                "status": "ok" if ok else "failed",
                "seconds": elapsed,
                "cs_files": len(files),
                "kb": round(size / 1024),
                "error": err,
            }
        )
        print(f"[{'ok' if ok else 'FAIL'}] {rel:<70} {elapsed:6.1f}s  {len(files):5d} files  {size/1048576:7.1f} MB", flush=True)

    (OUT / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in manifest if m.get("status") == "ok")
    print(f"\n完成 {ok}/{len(manifest)}", flush=True)
    return 0 if ok == len(manifest) else 1


if __name__ == "__main__":
    sys.exit(main())
