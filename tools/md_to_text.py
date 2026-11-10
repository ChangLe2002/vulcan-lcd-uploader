# SPDX-License-Identifier: MIT
"""把 CHANGELOG.md 转成纯文本版，放进 D:\\igame。"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(r"F:\shuchu\CHANGELOG.md")
DST = Path(r"D:\igame\CHANGELOG.txt")

HEADER = """================================================================
 火神智屏图传工具 (Vulcan LCD Uploader) —— 版本变更记录
================================================================

本文件由仓库里的 CHANGELOG.md 转换而来，按时间倒序排列（最新在最前）。

项目：https://github.com/ChangLe2002/vulcan-lcd-uploader
发布：https://github.com/ChangLe2002/vulcan-lcd-uploader/releases

"""

LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`([^`]+)`")
BLANK_RE = re.compile(r"\n{3,}")


def convert(markdown: str) -> str:
    lines: list[str] = [HEADER]
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
            lines += ["=" * 64, " " + title, "=" * 64, ""]
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            lines += ["", "-" * 64, " " + title, "-" * 64]
            continue
        if line.startswith("### "):
            lines.append("  · " + line[4:].strip())
            continue
        if line.startswith("|"):        # 丢掉 markdown 表格
            continue
        line = LINK_RE.sub(r"\1", line)
        line = BOLD_RE.sub(r"\1", line)
        line = CODE_RE.sub(r"\1", line)
        lines.append(line)

    text = "\n".join(lines)
    text = BLANK_RE.sub("\n\n", text).rstrip() + "\n"
    return text


def main() -> int:
    text = convert(SRC.read_text(encoding="utf-8"))
    DST.write_text(text, encoding="utf-8-sig")
    print(f"CHANGELOG.txt: {DST.stat().st_size / 1024:.1f} KB")
    print("---- 预览 ----")
    print("\n".join(text.splitlines()[:28]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
