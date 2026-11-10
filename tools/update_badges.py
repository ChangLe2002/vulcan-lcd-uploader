# SPDX-License-Identifier: MIT
"""更新 README 顶部徽章。

注意：本机网络环境下，shields.io 的 ``github/*`` 徽章只要带查询参数（``?style=`` 等）
就会返回 404，所以 GitHub 相关徽章一律使用**不带参数**的地址；
纯静态徽章（Python / Platform）自带 logo 参数可正常返回。
"""

from __future__ import annotations

from pathlib import Path

README = Path(r"F:\shuchu\README.md")
REPO = "ChangLe2002/vulcan-lcd-uploader"

NEW_BADGES = f"""<a href="https://github.com/{REPO}/releases"><img src="https://img.shields.io/github/v/release/{REPO}" alt="Release"></a>
<a href="https://github.com/{REPO}/blob/main/LICENSE"><img src="https://img.shields.io/github/license/{REPO}" alt="License"></a>
<a href="https://github.com/{REPO}/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/{REPO}/tests.yml" alt="Tests"></a>
<img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white" alt="Platform">
"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    start = text.find('<a href="https://github.com/')
    if start == -1:
        start = text.find("[![Release]")
    end = text.find('alt="Platform">')
    if end == -1 or start == -1:
        raise SystemExit("未找到徽章区块，请检查 README 结构")
    end += len('alt="Platform">') + 1

    README.write_text(text[:start] + NEW_BADGES + text[end:], encoding="utf-8")
    print("README 徽章已更新（无查询参数版本）")
    print("\n".join(NEW_BADGES.splitlines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
