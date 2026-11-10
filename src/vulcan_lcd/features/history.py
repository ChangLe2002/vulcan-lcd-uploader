# SPDX-License-Identifier: MIT
"""上传历史 / 素材库：记录用过的素材，下次一键选回。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["RecentItem", "History", "MAX_ITEMS"]

MAX_ITEMS = 30


@dataclass
class RecentItem:
    path: str
    used_at: str = ""
    seconds: float = 5.0

    @property
    def name(self) -> str:
        return Path(self.path).name

    def exists(self) -> bool:
        return Path(self.path).is_file()


class History:
    """最近使用的素材（按使用时间倒序，最多 MAX_ITEMS 条）。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    # -- 读写 ------------------------------------------------------------- #
    def load(self) -> list[RecentItem]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        items: list[RecentItem] = []
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict) or not raw.get("path"):
                continue
            try:
                seconds = float(raw.get("seconds", 5.0))
            except (TypeError, ValueError):
                seconds = 5.0
            items.append(
                RecentItem(
                    path=str(raw["path"]),
                    used_at=str(raw.get("used_at", "")),
                    seconds=max(1.0, min(3600.0, seconds)),
                )
            )
        return items[:MAX_ITEMS]

    def _save(self, items: list[RecentItem]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    [{"path": i.path, "used_at": i.used_at, "seconds": i.seconds} for i in items],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    # -- 维护 ------------------------------------------------------------- #
    def add(self, path: str | Path, *, seconds: float = 5.0) -> list[RecentItem]:
        """记录一次使用（同路径去重并提到最前）。"""
        target = str(Path(path).resolve())
        items = [i for i in self.load() if i.path != target]
        items.insert(
            0,
            RecentItem(
                path=target,
                used_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                seconds=seconds,
            ),
        )
        items = items[:MAX_ITEMS]
        self._save(items)
        return items

    def prune_missing(self) -> list[RecentItem]:
        """去掉已经不存在的文件（在 UI 里顺手调用）。"""
        items = [i for i in self.load() if i.exists()]
        self._save(items)
        return items

    def clear(self) -> None:
        self._save([])
