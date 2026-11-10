# SPDX-License-Identifier: MIT
"""列出目录下所有 PE 文件，并判断是否为 .NET 托管程序集。"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def is_managed(data: bytes) -> tuple[bool, str]:
    try:
        if data[:2] != b"MZ":
            return False, ""
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] != b"PE\0\0":
            return False, ""
        machine = struct.unpack_from("<H", data, pe + 4)[0]
        num_sections = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        # 数据目录 14 (CLI header)
        if magic == 0x10B:
            dd = opt + 96
        elif magic == 0x20B:
            dd = opt + 112
        else:
            return False, ""
        if dd + 8 * 15 > opt + opt_size:
            return False, ""
        cli_rva, cli_size = struct.unpack_from("<II", data, dd + 8 * 14)
        arch = {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(machine, f"0x{machine:X}")
        return cli_rva != 0, arch
    except Exception:  # noqa: BLE001
        return False, ""


def main(root: str) -> None:
    rows = []
    for path in Path(root).rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".exe", ".dll"):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        managed, arch = is_managed(data)
        rows.append(
            {
                "rel": str(path.relative_to(root)),
                "mb": round(len(data) / 1048576, 2),
                "managed": managed,
                "arch": arch,
            }
        )
    rows.sort(key=lambda r: (-r["mb"], r["rel"]))
    managed = [r for r in rows if r["managed"]]
    native = [r for r in rows if not r["managed"] and r["arch"]]
    print(f"total pe: {len(rows)}  managed: {len(managed)}  native: {len(native)}")
    print("\n== MANAGED ==")
    for r in managed:
        print(f"{r['mb']:7.2f} MB  {r['rel']}")
    print("\n== NATIVE ==")
    for r in native:
        print(f"{r['mb']:7.2f} MB  [{r['arch']}]  {r['rel']}")
    Path(r"F:\shuchu\decomp_all\_inventory.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"E:\iGameCenter")
