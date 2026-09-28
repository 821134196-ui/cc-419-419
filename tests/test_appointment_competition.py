# -*- coding: utf-8 -*-
"""预约竞争：重叠时段、有效出店单、清洁锁定、并发抢约、配件同时段互斥。"""
from __future__ import annotations

import threading

from app.services import Conflict
from tests.fixtures import BridalCase, DATE


class AppointmentCompetitionTests(BridalCase):
    def test_overlapping_slot_rejected(self):
        self.book(gown=1, start="10:00", end="11:00")
        with self.assertRaises(Conflict):
            self.book(gown=1, start="10:30", end="11:30")

    def test_adjacent_slots_allowed(self):
        self.book(gown=1, start="10:00", end="11:00")
        self.book(gown=1, start="11:00", end="12:00")  # 首尾相接不算重叠

    def test_different_gown_same_slot_allowed(self):
        self.book(gown=1, start="10:00", end="11:00")
        self.book(gown=2, start="10:00", end="11:00")

    def test_late_cancelled_slot_releases(self):
        a = self.book(gown=1)
        self.svc.mark_arrived(a["id"], 1)
        self.svc.late_cancel(a["id"], 1, 30, "迟到")
        self.book(gown=1, start="10:00", end="11:00")  # 释放后可再约

    def test_swap_closes_old_and_opens_new(self):
        a = self.book(gown=1)
        new = self.svc.swap_appointment(a["id"], 1, to_gown_id=2,
                                        to_size="S")
        self.assertEqual(new["gown_id"], 2)
        # 原礼服时段释放，可被他人预约
        self.book(cid=2, gown=1, start="10:00", end="11:00")
        # 新礼服该时段已占
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=2, start="10:00", end="11:00")

    def test_active_order_blocks_gown(self):
        self.make_order()
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=1, start="10:00", end="11:00")
        with self.assertRaises(Conflict):
            self.make_order(cid=2, gown=1)

    def test_cleaning_blocks_until_passed(self):
        o = self.make_order()
        self.check_all_ok(o["id"])
        # 清洁中不可约
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=1, date="2026-10-10")
        self.svc.cleaning_qc(o["id"], "failed", "残留印子返工")
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=1, date="2026-10-10")
        self.svc.cleaning_qc(o["id"], "passed", "复洗合格")
        self.book(cid=2, gown=1, date="2026-10-10")  # 合格释放

    def test_accessory_overlap_rejected(self):
        self.book(gown=1, acc=1)
        with self.assertRaises(Conflict):
            self.book(cid=2, gown=2, acc=1)

    def test_concurrent_bookings_only_one_wins(self):
        """两个线程同时抢同一礼服同一时段：恰好一个成功。"""
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def worker(ok_holder):
            conn = self.svc.conn  # 同连接受全局锁串行，改用独立连接
            from app.db import connect as db_connect
            c = db_connect(self.dir / "test.sqlite3")
            from app.services import BridalService
            s = BridalService(c)
            barrier.wait()
            try:
                s.create_appointment(
                    2, 1, "M", DATE, "14:00", "15:00",
                    code=f"APT-C{id(ok_holder)}", _immediate=True)
                ok_holder.append(True)
            except Conflict:
                ok_holder.append(False)
            finally:
                c.close()

        t1, t2 = [], []
        th = [threading.Thread(target=worker, args=(t1,)),
              threading.Thread(target=worker, args=(t2,))]
        for x in th:
            x.start()
        for x in th:
            x.join()
        self.assertEqual(sorted(t1 + t2), [False, True])
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM appointments WHERE gown_id=1"
            " AND slot_date=? AND status IN ('booked','arrived')",
            (DATE,)).fetchone()["c"]
        self.assertEqual(n, 1)  # 并发中仅一笔胜出
