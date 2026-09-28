# -*- coding: utf-8 -*-
"""照片配对：出店照 ⇄ 返店照按检查项配对，单边照片标记待配对。"""
from __future__ import annotations

from tests.fixtures import BridalCase


class PhotoPairingTests(BridalCase):
    def test_pair_marked_when_both_phases(self):
        o = self.make_order()
        iid = self.item_id(o["id"], "裙摆")
        # 出店已有照片（make_order 注入），此时单边
        before = self.conn.execute(
            "SELECT paired FROM photos WHERE item_id=? AND phase='outgoing'",
            (iid,)).fetchone()["paired"]
        self.assertEqual(before, 0)
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        self.svc.set_item_result(o["id"], 1, iid, "stained", "酒渍",
                                 photo_path="t/ret-hem.svg")
        after = self.conn.execute(
            "SELECT paired FROM photos WHERE item_id=?", (iid,)).fetchall()
        self.assertTrue(all(r["paired"] for r in after))

    def test_return_only_stays_unpaired(self):
        # 出店项不带照片，返店拍照：仍提示待配对
        o = self.make_order(items=[
            {"label": "拉链", "category": "detail", "outgoing_note": "正常"}],
            with_photos=False)
        iid = self.item_id(o["id"], "拉链")
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        self.svc.set_item_result(o["id"], 1, iid, "ok", "",
                                 photo_path="t/ret.svg")
        flags = [r["paired"] for r in self.conn.execute(
            "SELECT paired FROM photos WHERE item_id=?", (iid,))]
        self.assertEqual(flags, [0])

    def test_attach_outgoing_then_pair(self):
        o = self.make_order(items=[
            {"label": "拉链", "category": "detail", "outgoing_note": "正常"}],
            with_photos=False)
        iid = self.item_id(o["id"], "拉链")
        self.svc.attach_outgoing_photo(o["id"], 1, iid, "detail",
                                       "t/out-zip.svg", "出店补拍")
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        self.svc.set_item_result(o["id"], 1, iid, "ok", "",
                                 photo_path="t/ret-zip.svg")
        rows = [r for r in self.conn.execute(
            "SELECT phase, paired FROM photos WHERE item_id=?", (iid,))]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["paired"] for r in rows))

    def test_late_item_added_on_overdue(self):
        o = self.make_order(planned="2026-10-03 18:00")
        self.svc.start_return(o["id"], 1, "2026-10-03 19:20")
        late = self.conn.execute(
            "SELECT id FROM inspection_items WHERE order_id=? AND label='超时返店'",
            (o["id"],)).fetchone()
        self.assertIsNotNone(late)
        detail = self.svc.order_detail(o["id"])
        self.assertTrue(detail["is_late"])
