# -*- coding: utf-8 -*-
"""测试夹具：临时目录中的全新 SQLite + 最小演示数据。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.services import BridalService

DATE = "2026-10-02"


class BridalCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self.conn = connect(self.dir / "test.sqlite3")
        init_db(self.conn)
        self._fixture()
        self.svc = BridalService(self.conn)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def _fixture(self):
        c = self.conn
        c.execute("INSERT INTO customers (code,name,phone) VALUES"
                  " ('C001','林晚','138-1'),('C002','苏绮','138-2'),"
                  " ('C003','周棠','138-3')")
        for cid, code, dep in ((1, "BW-001", 300000), (2, "BW-002", 200000),
                               (3, "BW-003", 250000)):
            c.execute("""INSERT INTO gowns
                 (code,name,style,color_note,deposit,rental_fee,cover_photo)
                 VALUES (?,?, '拖尾','象牙白',?, 80000,'t/x.svg')""",
                      (code, f"礼服{cid}", dep))
            for lbl in ("S", "M"):
                c.execute("INSERT INTO gown_sizes (gown_id,label) VALUES (?,?)",
                          (cid, lbl))
        accs = [
            (1, "AC-01", [("V-01", "头纱"), ("C-01", "皇冠"), ("E-01", "耳饰")]),
            (2, "AC-02", [("F-01", "团扇"), ("H-01", "步摇")]),
        ]
        for aid, code, pieces in accs:
            c.execute("INSERT INTO accessory_sets (code,name,pieces)"
                      " VALUES (?,?,?)",
                      (code, code, json.dumps(
                          [{"code": x, "name": n} for x, n in pieces],
                          ensure_ascii=False)))
        c.commit()

    # ------------------------------------------------- 业务构造助手
    def book(self, cid=1, gown=1, start="10:00", end="11:00", date=DATE,
             acc=None, svc=None):
        svc = svc or self.svc
        return svc.create_appointment(cid, gown, "M", date, start, end,
                                      accessory_set_id=acc)

    def make_order(self, cid=1, gown=1, acc=1,
                   planned="2026-10-03 18:00", svc=None,
                   items=None, with_photos=True):
        """预约→到店→出店，返回 order 行。默认检查项各带出店照片。"""
        svc = svc or self.svc
        appt = self.book(cid, gown, acc=acc, svc=svc)
        svc.mark_arrived(appt["id"], cid)
        items = items or [
            {"label": "裙摆", "category": "stain",
             "outgoing_note": "出店无污渍"},
            {"label": "内衬", "category": "detail",
             "outgoing_note": "无勾丝"},
        ]
        photos = {i: {"path": f"t/out-{i}.svg",
                      "category": it.get("category", "detail")}
                  for i, it in enumerate(items, start=1)} \
            if with_photos else None
        return svc.create_outgoing_order(
            cid, appt["id"], gown, acc,
            size_adjust={"waist": "收 2cm", "photo": "t/adjust.svg"},
            planned_return=planned, items=items, outgoing_photos=photos)

    def item_id(self, oid, label):
        return self.conn.execute(
            "SELECT id FROM inspection_items WHERE order_id=? AND label=?",
            (oid, label)).fetchone()["id"]

    def return_photo_id(self, item_id):
        return self.conn.execute(
            "SELECT id FROM photos WHERE item_id=? AND phase='return'",
            (item_id,)).fetchone()["id"]

    def check_all_ok(self, oid, cid=1, svc=None, actual="2026-10-03 17:00"):
        """返店：全部勾选正常（配件项也齐全）并确认。"""
        svc = svc or self.svc
        svc.start_return(oid, cid, actual)
        rows = self.conn.execute(
            "SELECT id FROM inspection_items WHERE order_id=? ORDER BY seq",
            (oid,)).fetchall()
        for r in rows:
            svc.set_item_result(oid, cid, r["id"], "ok", "无异常",
                                photo_path="t/ret.svg")
        return svc.confirm_return(oid, cid)
