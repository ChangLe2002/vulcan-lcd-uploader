# SPDX-License-Identifier: MIT
"""上传台账：记录本工具往设备写过哪些文件。

作用：清理缓存时**只删我们自己的文件**，绝不碰用户原有的素材。
存放位置与配置同一目录（打包后是 exe 旁边），JSON 格式。
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["UploadLedger"]

_FILENAME = "uploaded_files.json"


class UploadLedger:
    """极简台账：一组文件名。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[str]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        names = data.get("names", []) if isinstance(data, dict) else []
        return [str(n) for n in names if isinstance(n, str)]

    def add(self, name: str) -> None:
        names = self.load()
        if name not in names:
            names.append(name)
        self._save(names)

    def remove(self, name: str) -> None:
        names = [n for n in self.load() if n != name]
        self._save(names)

    def clear(self) -> None:
        self._save([])

    def _save(self, names: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"names": names}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
