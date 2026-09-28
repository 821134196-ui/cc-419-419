# -*- coding: utf-8 -*-
"""配件完整性：逐项清点、缺件冻结套装、补齐回库。"""
from __future__ import annotations

from app.services import Conflict
from tests.fixtures import BridalCase


class AccessoryIntegrityTests(BridalCase):
    def _return_with(self, results: dict[str, str]):
        o = self.make_order()  # AC-01：头纱/皇冠/耳饰
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        for label, result in results.items():
            iid = self.item_id(o["id"], label)
            self.svc.set_item_result(o["id"], 1, iid, result, "返店核对",
                                     photo_path="t/ret.svg")
        return o

    def test_all_pieces_back_keeps_available(self):
        labels = ["配件 · V-01 头纱", "配件 · C-01 皇冠",
                  "配件 · E-01 耳饰"]
        o = self._return_with({l: "ok" for l in labels})
        # 礼服两项也要勾选才能确认
        for lbl in ("裙摆", "内衬"):
            self.svc.set_item_result(
                o["id"], 1, self.item_id(o["id"], lbl), "ok", "")
        self.svc.confirm_return(o["id"], 1)
        acc = self.conn.execute(
            "SELECT status FROM accessory_sets WHERE id=1").fetchone()
        self.assertEqual(acc["status"], "available")

    def test_missing_piece_freezes_set(self):
        labels_ok = {"配件 · V-01 头纱": "ok",
                     "配件 · C-01 皇冠": "missing",
                     "配件 · E-01 耳饰": "ok",
                     "裙摆": "ok", "内衬": "ok"}
        o = self._return_with(labels_ok)
        self.svc.confirm_return(o["id"], 1)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM accessory_sets WHERE id=1"
        ).fetchone()["status"], "incomplete")
        # 缺件套装不可再预约
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=2, acc=1, date="2026-10-10")

    def test_restock_unfreezes(self):
        labels = {"配件 · V-01 头纱": "ok",
                  "配件 · C-01 皇冠": "missing",
                  "配件 · E-01 耳饰": "ok",
                  "裙摆": "ok", "内衬": "ok"}
        o = self._return_with(labels)
        self.svc.confirm_return(o["id"], 1)
        self.svc.restock_accessory(1, "皇冠找回")
        self.book(cid=2, gown=2, acc=1, date="2026-10-10")

    def test_confirm_blocked_when_pending_items(self):
        o = self.make_order()
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        with self.assertRaises(Conflict):
            self.svc.confirm_return(o["id"], 1)  # 逐项未勾完
