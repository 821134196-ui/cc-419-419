# -*- coding: utf-8 -*-
"""押金幂等：扣款关联检查项+照片、重复扣款不重复入账、超额拒绝、结算幂等、
清洁前不可扣款结算之外的边界，以及冻结结果只可复核。"""
from __future__ import annotations

from app.services import Conflict, DomainError
from tests.fixtures import BridalCase


class DepositIdempotencyTests(BridalCase):
    def _abnormal_order(self):
        """出店 → 返店：裙摆污渍（带返店照）→ 确认。返回 (oid,item,photo)。"""
        o = self.make_order()
        self.svc.start_return(o["id"], 1, "2026-10-03 17:00")
        iid = self.item_id(o["id"], "裙摆")
        self.svc.set_item_result(o["id"], 1, iid, "stained", "酒渍",
                                 photo_path="t/ret-stain.svg")
        self.svc.set_item_result(
            o["id"], 1, self.item_id(o["id"], "内衬"), "ok", "")
        for lbl in ("配件 · V-01 头纱", "配件 · C-01 皇冠",
                    "配件 · E-01 耳饰"):
            self.svc.set_item_result(
                o["id"], 1, self.item_id(o["id"], lbl), "ok", "")
        self.svc.confirm_return(o["id"], 1)
        return o["id"], iid, self.return_photo_id(iid)

    def test_deduction_requires_item_and_photo(self):
        oid, iid, pid = self._abnormal_order()
        # 必须是返店阶段照片
        out_photo = self.conn.execute(
            "SELECT id FROM photos WHERE item_id=? AND phase='outgoing'",
            (iid,)).fetchone()["id"]
        with self.assertRaises(Conflict):
            self.svc.deduct_deposit(oid, 1, iid, out_photo, 10000, "无效凭据")
        # 照片必须属于该检查项
        other = self.item_id(oid, "内衬")
        with self.assertRaises(Conflict):
            self.svc.deduct_deposit(oid, 1, other, pid, 10000, "项照不符")

    def test_deduction_idempotent_same_key(self):
        oid, iid, pid = self._abnormal_order()
        kw = dict(idem_key="manual-1")
        d1 = self.svc.deduct_deposit(oid, 1, iid, pid, 30000, "清洗费", **kw)
        d2 = self.svc.deduct_deposit(oid, 1, iid, pid, 30000, "清洗费", **kw)
        self.assertEqual(d1["id"], d2["id"])
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM deposit_deductions WHERE idem_key='manual-1'"
        ).fetchone()["c"]
        self.assertEqual(n, 1)
        n_pay = self.conn.execute(
            "SELECT COUNT(*) c FROM payment_ledger WHERE kind='deduct'"
        ).fetchone()["c"]
        self.assertEqual(n_pay, 1)

    def test_repeated_form_submit_deduped_by_natural_key(self):
        oid, iid, pid = self._abnormal_order()
        d1 = self.svc.deduct_deposit(oid, 1, iid, pid, 20000, "重放提交")
        d2 = self.svc.deduct_deposit(oid, 1, iid, pid, 20000, "重放提交")
        self.assertEqual(d1["id"], d2["id"])

    def test_deduction_cannot_exceed_deposit(self):
        oid, iid, pid = self._abnormal_order()  # 押金 3000 元
        self.svc.deduct_deposit(oid, 1, iid, pid, 290000, "大额")
        with self.assertRaises(Conflict):
            self.svc.deduct_deposit(
                oid, 1, iid, pid, 20000, "超额", idem_key="x2")

    def test_zero_amount_rejected(self):
        oid, iid, pid = self._abnormal_order()
        with self.assertRaises((DomainError, Conflict)):
            self.svc.deduct_deposit(oid, 1, iid, pid, 0, "零元")

    def test_settle_idempotent_and_refund(self):
        oid, iid, pid = self._abnormal_order()
        self.svc.deduct_deposit(oid, 1, iid, pid, 30000, "清洗")
        s1 = self.svc.settle_deposit(oid, 1)
        self.assertEqual(s1["status"], "settled")
        self.assertEqual(s1["refunded"], 270000)
        s2 = self.svc.settle_deposit(oid, 1)  # 重复结算幂等
        self.assertEqual(s1["id"], s2["id"])
        refunds = self.conn.execute(
            "SELECT COUNT(*) c FROM payment_ledger WHERE kind='refund'"
        ).fetchone()["c"]
        self.assertEqual(refunds, 1)
        # 已结算不可再扣
        with self.assertRaises(Conflict):
            self.svc.deduct_deposit(
                oid, 1, iid, pid, 1000, "事后补扣", idem_key="late")

    def test_confirmed_result_append_review_only(self):
        oid, iid, pid = self._abnormal_order()
        # 已确认订单不能再改检查项
        with self.assertRaises(Conflict):
            self.svc.set_item_result(oid, 1, iid, "ok", "想改结果",
                                     photo_path="t/x.svg")
        r = self.svc.add_review(oid, 1, "店长复核：扣款成立")
        self.assertTrue(r["id"])
        with self.assertRaises(DomainError):
            self.svc.add_review(oid, 1, "   ")
