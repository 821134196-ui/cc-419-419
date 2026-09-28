# -*- coding: utf-8 -*-
"""客户隔离：不能到店/取消/换款他人预约，不能检查/扣款/结算/复核他人订单。"""
from __future__ import annotations

from app.services import NotOwner
from tests.fixtures import BridalCase


class CustomerIsolationTests(BridalCase):
    def test_cannot_arrive_foreign_appointment(self):
        a = self.book(cid=1, gown=1)
        with self.assertRaises(NotOwner):
            self.svc.mark_arrived(a["id"], 2)

    def test_cannot_late_cancel_foreign(self):
        a = self.book(cid=1, gown=1)
        with self.assertRaises(NotOwner):
            self.svc.late_cancel(a["id"], 2, 20)

    def test_cannot_swap_foreign(self):
        a = self.book(cid=1, gown=1)
        with self.assertRaises(NotOwner):
            self.svc.swap_appointment(a["id"], 2, to_gown_id=2, to_size="S")

    def test_cannot_inspect_foreign_order(self):
        o = self.make_order(cid=1, gown=1)
        with self.assertRaises(NotOwner):
            self.svc.start_return(o["id"], 2, "2026-10-03 17:00")
        with self.assertRaises(NotOwner):
            self.svc.order_detail(o["id"], customer_id=2)

    def test_cannot_deduct_foreign_order(self):
        o = self.make_order(cid=1, gown=1)
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        iid = self.item_id(o["id"], "裙摆")
        self.svc.set_item_result(o["id"], 1, iid, "stained", "污渍",
                                 photo_path="t/ret.svg")
        pid = self.return_photo_id(iid)
        with self.assertRaises(NotOwner):
            self.svc.deduct_deposit(o["id"], 2, iid, pid, 10000, "越权扣款")
        with self.assertRaises(NotOwner):
            self.svc.settle_deposit(o["id"], 2)
        with self.assertRaises(NotOwner):
            self.svc.add_review(o["id"], 2, "越权复核")

    def test_calendar_filtered_by_customer(self):
        self.book(cid=1, gown=1)
        self.book(cid=2, gown=2)
        rows = self.svc.calendar("2026-10-01", "2026-10-31", customer_id=2)
        self.assertTrue(rows)
        self.assertTrue(all(r["customer_id"] == 2 for r in rows))
