# -*- coding: utf-8 -*-
"""路径与运行参数：SQLite 与本地照片目录。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("BRIDAL_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "bridal.sqlite3"
PHOTO_DIR = DATA_DIR / "photos"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)


def photo_rel(path: Path) -> str:
    """照片相对 PHOTO_DIR 的路径，供 URL /photos/<rel> 使用。"""
    return path.relative_to(PHOTO_DIR).as_posix()
