# -*- coding: utf-8 -*-
"""演示数据：客户、礼服档案（含尺码）、配件套装，以及本地 SVG 照片。

用法：python3 -m app.seed [--reset]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import photos as P
from .config import DB_PATH, PHOTO_DIR, ensure_dirs
from .db import connect, init_db

YEN = 100  # 1 元 = 100 分

CUSTOMERS = [
    ("C001", "林晚", "138-0000-0001"),
    ("C002", "苏绮", "139-0000-0002"),
    ("C003", "周棠", "137-0000-0003"),
]

# code, name, silhouette(裙型), 押金(元), 租金(元), 尺码
GOWNS = [
    ("BW-001", "星月拖尾", "train", 3000, 800,
     [("S", 82, 64, 88), ("M", 86, 68, 92), ("L", 90, 72, 96)]),
    ("BW-002", "云絮 A 字裙", "aline", 2000, 600,
     [("S", 80, 62, 86), ("M", 84, 66, 90)]),
    ("BW-003", "珊瑚鱼尾", "mermaid", 2500, 700,
     [("XS", 78, 60, 84), ("S", 82, 64, 88), ("M", 86, 68, 92)]),
    ("XH-001", "绛纱秀禾", "qunagua", 1800, 500,
     [("M", 86, 70, 92), ("L", 92, 76, 98)]),
    ("BW-004", "珍珠小拖尾", "train", 2200, 650,
     [("S", 82, 64, 88), ("M", 86, 68, 92)]),
]

ACCESSORIES = [
    ("AC-01", "星冕仪式套装", [
        ("V-01", "长款拖地头纱"), ("C-01", "水晶皇冠"), ("E-01", "珍珠耳饰")]),
    ("AC-02", "绢花中式套装", [
        ("F-01", "刺绣团扇"), ("H-01", "鎏金步摇"), ("G-01", "红盖头")]),
    ("AC-03", "极简领证套装", [
        ("V-02", "齐地头纱"), ("N-01", "细钻颈链")]),
]


def _rel(abs_path: str | Path) -> str:
    return Path(abs_path).relative_to(PHOTO_DIR).as_posix()


def seed(reset: bool = False) -> None:
    ensure_dirs()
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect(DB_PATH)
    init_db(conn)
    if conn.execute("SELECT COUNT(*) c FROM gowns").fetchone()["c"]:
        conn.close()
        print("seed: 数据已存在，跳过（--reset 可重建）")
        return
    try:
        # 客户 + 演示头像
        for code, name, phone in CUSTOMERS:
            avatar = P.write_svg(
                PHOTO_DIR / "customers" / f"{code}.svg",
                P.avatar_svg(code, name))
            conn.execute(
                "INSERT INTO customers (code,name,phone,demo_photo)"
                " VALUES (?,?,?,?)",
                (code, name, phone, _rel(avatar)))

        # 礼服 + 封面 + 尺码
        for code, name, sil, dep, fee, sizes in GOWNS:
            cover = P.write_svg(
                PHOTO_DIR / "gowns" / f"{code}.svg",
                P.gown_svg(code, name, sil))
            detail = P.write_svg(
                PHOTO_DIR / "gowns" / f"{code}-detail.svg",
                P.detail_svg(f"{code} 档案细节", "面料/工艺存档照"))
            cur = conn.execute(
                """INSERT INTO gowns
                       (code,name,style,color_note,deposit,rental_fee,
                        cover_photo,detail_photo)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (code, name,
                 {"train": "拖尾", "aline": "A字",
                  "mermaid": "鱼尾", "qunagua": "秀禾"}[sil],
                 "象牙白" if sil != "qunagua" else "绛红绣金",
                 dep * YEN, fee * YEN, _rel(cover), _rel(detail)))
            gown_id = cur.lastrowid
            for label, bust, waist, hip in sizes:
                conn.execute(
                    "INSERT INTO gown_sizes (gown_id,label,bust_cm,waist_cm,hip_cm)"
                    " VALUES (?,?,?,?,?)",
                    (gown_id, label, bust, waist, hip))

        # 配件套装
        for code, name, pieces in ACCESSORIES:
            pic = P.write_svg(
                PHOTO_DIR / "accessories" / f"{code}.svg",
                P.accessory_svg(code, name, [p[1] for p in pieces]))
            conn.execute(
                "INSERT INTO accessory_sets (code,name,pieces,cover_photo)"
                " VALUES (?,?,?,?)",
                (code, name, json.dumps(
                    [{"code": c, "name": n} for c, n in pieces],
                    ensure_ascii=False), _rel(pic)))
        conn.commit()
        print(f"seed: 客户 {len(CUSTOMERS)}、礼服 {len(GOWNS)}、"
              f"配件套装 {len(ACCESSORIES)} 已写入 {DB_PATH}")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    seed(args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
