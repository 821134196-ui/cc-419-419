"""婚纱礼服试穿与返店清点系统 — 测试套件。

覆盖：
  1. 预约竞争（同一礼服重叠时段 / 双重出店）
  2. 配件完整性（套装编号绑定、出店锁定、返店逐项清点）
  3. 照片配对（出店/返店按 slot 配对、扣款照片关联）
  4. 押金幂等（幂等键去重、重复结算不重复扣款）
  5. 客户隔离（各列表按客户过滤）
另含：清洁门槛、迟到取消、临时换款、已确认返店仅可追加复核、扣款校验、HTTP API。

运行：
    python3 test_bridal.py            # 仅服务层
    python3 test_bridal.py --http     # 额外启动进程内 HTTP 服务做接口测试
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest

# 在导入 core 前指定独立数据目录（SQLite + 照片均落在临时目录）
TMP = tempfile.mkdtemp(prefix="bridal_test_")
os.environ["BRIDAL_DATA_DIR"] = TMP

import core  # noqa: E402


# ---------------------------------------------------------------- 测试工具
def photo(label: str = "p") -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40">'
           f'<rect width="60" height="40" fill="#f2f2f2"/>'
           f'<text x="30" y="25" font-size="12" text-anchor="middle">{label}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def reset_db() -> None:
    conn = core.get_db()
    try:
        for t in ("inspections", "deposits", "cleaning_records", "out_orders",
                  "appointments", "accessory_items", "accessory_sets", "gowns", "customers"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
    core.SETTLEMENT._records.clear()


class BridalTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.a = core.create_customer("客户甲", "13900000001")
        self.b = core.create_customer("客户乙", "13900000002")
        self.g1 = core.create_gown("T-W01", "测试礼服一", "鱼尾", "象牙白", "S", 2000, photo("W01"))
        self.g2 = core.create_gown("T-W02", "测试礼服二", "蓬裙", "米白", "M", 3000, photo("W02"))
        self.g3 = core.create_gown("T-W03", "测试礼服三", "A字", "香槟", "L", 1000, photo("W03"))

    def mk_set(self, code="T-AC1", n=3):
        return core.create_accessory_set(
            code, "测试套装",
            [{"code": f"{code}-{i:02d}", "name": f"配件{i}"} for i in range(1, n + 1)])

    def mk_order(self, gown=None, customer=None, set_id=None, out_slots=("front", "hem")):
        gown = gown or self.g1
        customer = customer or self.a
        photos = [core.save_photo(photo(s), s) for s in out_slots]
        return core.create_out_order(
            gown["id"], customer["id"], set_id, None,
            size_adjustments="腰围收 2cm", pre_stains="无", out_photos=photos,
            expected_return_time="2099-01-01T10:00:00")


# ============================================================ 1. 预约竞争
class TestAppointmentCompetition(BridalTestBase):
    def test_overlapping_slot_rejected(self):
        """同一礼服重叠时段的第二个预约必须被拒绝。"""
        core.create_appointment(self.g1["id"], self.a["id"],
                                "2099-03-01T10:00:00", "2099-03-01T11:00:00")
        with self.assertRaises(core.ServiceError) as cm:
            core.create_appointment(self.g1["id"], self.b["id"],
                                    "2099-03-01T10:30:00", "2099-03-01T11:30:00")
        self.assertIn("已被预约", cm.exception.message)

    def test_non_overlapping_slots_allowed(self):
        """同一礼服不重叠的不同时段可以各自锁定。"""
        core.create_appointment(self.g1["id"], self.a["id"],
                                "2099-03-01T09:00:00", "2099-03-01T10:00:00")
        a2 = core.create_appointment(self.g1["id"], self.b["id"],
                                     "2099-03-01T11:00:00", "2099-03-01T12:00:00")
        self.assertEqual(a2["status"], "booked")
        self.assertEqual(len(core.list_appointments(gown_id=self.g1["id"], status="booked")), 2)

    def test_different_gowns_same_slot_ok(self):
        """不同礼服同一时段互不影响。"""
        core.create_appointment(self.g1["id"], self.a["id"],
                                "2099-03-01T10:00:00", "2099-03-01T11:00:00")
        core.create_appointment(self.g2["id"], self.b["id"],
                                "2099-03-01T10:00:00", "2099-03-01T11:00:00")

    def test_gown_out_cannot_be_appointed_or_re_out(self):
        """已出店礼服不能再预约，也不能开第二张出店单。"""
        self.mk_order()
        with self.assertRaises(core.ServiceError):
            core.create_appointment(self.g1["id"], self.b["id"],
                                    "2099-03-01T10:00:00", "2099-03-01T11:00:00")
        with self.assertRaises(core.ServiceError):
            self.mk_order()

    def test_late_cancel_releases_gown(self):
        """迟到取消后礼服释放，可被重新预约。"""
        a = core.create_appointment(self.g1["id"], self.a["id"],
                                    "2099-03-01T10:00:00", "2099-03-01T11:00:00")
        self.assertEqual(core.get_gown(self.g1["id"])["status"], "reserved")
        core.cancel_appointment(a["id"], late=True)
        self.assertEqual(a_id_status(a["id"]), "late_cancelled")
        self.assertEqual(core.get_gown(self.g1["id"])["status"], "available")
        # 可重新预约同一时段
        core.create_appointment(self.g1["id"], self.b["id"],
                                "2099-03-01T10:00:00", "2099-03-01T11:00:00")

    def test_swap_releases_old_and_locks_new(self):
        """临时换款：旧礼服释放，新礼服锁定，原单号记录 swap_from。"""
        a = core.create_appointment(self.g1["id"], self.a["id"],
                                    "2099-03-01T10:00:00", "2099-03-01T11:00:00")
        core.swap_appointment_gown(a["id"], self.g2["id"])
        moved = core.get_appointment(a["id"])
        self.assertEqual(moved["gown_id"], self.g2["id"])
        self.assertEqual(moved["swap_from_gown_id"], self.g1["id"])
        self.assertEqual(moved["status"], "swapped")
        self.assertEqual(core.get_gown(self.g1["id"])["status"], "available")
        self.assertEqual(core.get_gown(self.g2["id"])["status"], "reserved")
        # g3 被另一客户在重叠时段占用，a 不能换入 g3
        core.create_appointment(self.g3["id"], self.b["id"],
                                "2099-03-01T10:30:00", "2099-03-01T11:30:00")
        with self.assertRaises(core.ServiceError):
            core.swap_appointment_gown(a["id"], self.g3["id"])


def a_id_status(appt_id: int) -> str:
    return core.get_appointment(appt_id)["status"]


# ============================================================ 2. 配件完整性
class TestAccessoryCompleteness(BridalTestBase):
    def test_set_items_bound_by_code(self):
        s = self.mk_set("T-AC9", 4)
        got = core.get_accessory_set(s["id"])
        codes = [i["code"] for i in got["items"]]
        self.assertEqual(codes, ["T-AC9-01", "T-AC9-02", "T-AC9-03", "T-AC9-04"])

    def test_duplicate_item_code_rejected(self):
        with self.assertRaises(core.ServiceError):
            core.create_accessory_set("X", "X", [{"code": "X-1", "name": "a"},
                                                 {"code": "X-1", "name": "b"}])

    def test_set_locked_while_out(self):
        """配件套装随出店单锁定，不能同时绑定第二张有效出店单。"""
        s = self.mk_set()
        self.mk_order(gown=self.g1, set_id=s["id"])
        with self.assertRaises(core.ServiceError) as cm:
            self.mk_order(gown=self.g2, set_id=s["id"])
        self.assertIn("配件套装已随", cm.exception.message)

    def test_return_checklist_contains_every_item(self):
        """返店检查清单必须包含礼服基线项 + 配件逐项。"""
        s = self.mk_set("T-AC2", 3)
        order = self.mk_order(gown=self.g1, set_id=s["id"])
        ins = core.create_return_inspection(order["id"])
        keys = [i["key"] for i in ins["items"]]
        # 7 个礼服检查项
        self.assertEqual(len([k for k in keys if not k.startswith("acc_")]), len(core.GOWN_CHECKLIST))
        # 每个配件都有对应检查项，按编号
        for code in ("T-AC2-01", "T-AC2-02", "T-AC2-03"):
            self.assertIn(f"acc_{code}", keys)

    def test_missing_accessory_blocks_nothing_but_can_deduct(self):
        s = self.mk_set("T-AC3", 2)
        order = self.mk_order(gown=self.g1, set_id=s["id"])
        ins = core.create_return_inspection(order["id"])
        items = [{"key": it["key"], "result": "missing" if it["key"] == "acc_T-AC3-02" else "ok",
                  "note": "缺失" if it["key"] == "acc_T-AC3-02" else ""}
                 for it in ins["items"]]
        core.update_inspection_items(ins["id"], items, [])
        core.add_inspection_deduction(ins["id"], "acc_T-AC3-02", 500, "配件遗失赔偿",
                                      [{"data_url": photo("missing"), "slot": "ded"}])
        ins2 = core.get_inspection(ins["id"])
        self.assertEqual(sum(d["amount"] for d in ins2["deductions"]), 50000)
        self.assertTrue(all(d["photos"] for d in ins2["deductions"]))


# ============================================================ 3. 照片配对
class TestPhotoPairing(BridalTestBase):
    def test_out_return_pairing_by_slot(self):
        order = self.mk_order(out_slots=("front", "hem", "zipper"))
        ins = core.create_return_inspection(order["id"])
        items = [{"key": "hem", "result": "stain", "note": "底边污渍"}]
        # hem 与出店 hem 配对；stains 仅有返店照片（异常新增）
        core.update_inspection_items(ins["id"], items, [
            {"data_url": photo("hem-ret"), "slot": "hem"},
            {"data_url": photo("stain-ret"), "slot": "stains"},
        ])
        pairs = {p["slot"]: p for p in core.get_inspection(ins["id"])["paired_photos"]}
        # hem 出店与返店都在
        self.assertIsNotNone(pairs["hem"]["out"])
        self.assertEqual(len(pairs["hem"]["returns"]), 1)
        # front / zipper 仅出店
        self.assertIsNotNone(pairs["front"]["out"])
        self.assertEqual(pairs["front"]["returns"], [])
        self.assertIsNotNone(pairs["zipper"]["out"])
        # stains 仅返店（异常照片）
        self.assertIsNone(pairs["stains"]["out"])
        self.assertEqual(len(pairs["stains"]["returns"]), 1)

    def test_deduction_photo_is_evidence(self):
        order = self.mk_order()
        ins = core.create_return_inspection(order["id"])
        core.update_inspection_items(
            ins["id"], [{"key": "damage", "result": "damaged", "note": "勾丝"}], [])
        with self.assertRaises(core.ServiceError):
            # 正常项不能扣款
            core.add_inspection_deduction(ins["id"], "zipper", 10, "x",
                                          [{"data_url": photo(), "slot": "d"}])
        with self.assertRaises(core.ServiceError):
            # 缺照片不能扣款
            core.add_inspection_deduction(ins["id"], "damage", 10, "x", [])
        core.add_inspection_deduction(ins["id"], "damage", 10, "勾丝修补",
                                      [{"data_url": photo("damage-proof"), "slot": "ded_damage"}])
        d = core.get_inspection(ins["id"])["deductions"][0]
        self.assertEqual(d["item_key"], "damage")
        self.assertTrue(d["photos"][0]["url"].startswith("/photos/"))


# ============================================================ 4. 押金幂等
class TestDepositIdempotency(BridalTestBase):
    def _confirmed_order(self):
        s = self.mk_set()
        order = self.mk_order(gown=self.g1, set_id=s["id"])
        ins = core.create_return_inspection(order["id"])
        items = [{"key": it["key"],
                  "result": "missing" if it["key"] == "acc_T-AC1-01" else "ok",
                  "note": ""} for it in ins["items"]]
        core.update_inspection_items(ins["id"], items, [])
        core.add_inspection_deduction(ins["id"], "acc_T-AC1-01", 300, "配件赔偿",
                                      [{"data_url": photo(), "slot": "ded"}])
        core.confirm_inspection(ins["id"])
        return order, ins

    def test_settle_adapter_idempotent(self):
        """同一幂等键多次结算返回同一结算号，且标记为重放。"""
        r1 = core.SETTLEMENT.settle("k-1", 100, "首次")
        r2 = core.SETTLEMENT.settle("k-1", 999, "应被忽略")
        self.assertEqual(r1["settlement_no"], r2["settlement_no"])
        self.assertFalse(r1["idempotent_replay"])
        self.assertTrue(r2["idempotent_replay"])
        self.assertEqual(r2["amount"], 100)  # 金额取首次，未重复扣款

    def test_deposit_settled_once(self):
        order, ins = self._confirmed_order()
        dep = core.list_deposits()[0]
        self.assertEqual(dep["out_order_id"], order["id"])
        self.assertEqual(dep["amount"], 200000)          # 押金 2000
        self.assertEqual(dep["deduction_total"], 30000)  # 扣款 300
        self.assertEqual(dep["refund_amount"], 170000)   # 退款 1700
        self.assertEqual(dep["status"], "deducted")
        # 重复确认被拒绝，且不会产生第二笔结算
        with self.assertRaises(core.ServiceError):
            core.confirm_inspection(ins["id"])
        # 幂等键在 deposits 表唯一：另一笔押金使用相同键应被拒绝
        other = self.mk_order(gown=self.g3)
        conn = core.get_db()
        try:
            with self.assertRaises(Exception):
                conn.execute(
                    "INSERT INTO deposits (code, out_order_id, amount, status, idempotency_key, created_at) "
                    "VALUES ('X', ?, 1, 'paid', ?, '')", (other["id"], dep["idempotency_key"]))
        finally:
            conn.close()

    def test_full_refund_when_no_deduction(self):
        order = self.mk_order(gown=self.g2)
        ins = core.create_return_inspection(order["id"])
        core.update_inspection_items(
            ins["id"], [{"key": it["key"], "result": "ok", "note": ""} for it in ins["items"]], [])
        core.confirm_inspection(ins["id"])
        dep = [d for d in core.list_deposits() if d["out_order_id"] == order["id"]][0]
        self.assertEqual(dep["status"], "refunded")
        self.assertEqual(dep["refund_amount"], 300000)
        self.assertEqual(dep["deduction_total"], 0)


# ============================================================ 5. 客户隔离 + 清洁/复核
class TestCustomerIsolationAndLifecycle(BridalTestBase):
    def test_customer_scoped_lists(self):
        # 客户甲：礼服一整套；客户乙：礼服二整套
        oa = self.mk_order(gown=self.g1, customer=self.a)
        ob = self.mk_order(gown=self.g2, customer=self.b)
        ia = core.create_return_inspection(oa["id"])
        ib = core.create_return_inspection(ob["id"])

        a_orders = core.list_out_orders(customer_id=self.a["id"])
        b_orders = core.list_out_orders(customer_id=self.b["id"])
        self.assertEqual([o["id"] for o in a_orders], [oa["id"]])
        self.assertEqual([o["id"] for o in b_orders], [ob["id"]])
        self.assertEqual(
            [i["id"] for i in core.list_inspections(customer_id=self.a["id"])], [ia["id"]])
        self.assertEqual(
            [d["out_order_id"] for d in core.list_deposits(customer_id=self.a["id"])], [oa["id"]])
        self.assertEqual(
            [d["out_order_id"] for d in core.list_deposits(customer_id=self.b["id"])], [ob["id"]])
        # 不带客户参数可看到全部
        self.assertEqual(len(core.list_out_orders()), 2)

    def test_cleaning_gate(self):
        """清洁完成前礼服不能预约；不合格继续阻塞；合格后恢复。"""
        order = self.mk_order(gown=self.g1)
        ins = core.create_return_inspection(order["id"])
        core.update_inspection_items(
            ins["id"], [{"key": x["key"], "result": "ok", "note": ""} for x in ins["items"]], [])
        core.confirm_inspection(ins["id"])
        # 进入清洁：不可预约
        self.assertEqual(core.get_gown(self.g1["id"])["status"], "cleaning")
        self.assertEqual(core.get_gown(self.g1["id"])["cleaning_status"], "pending")
        with self.assertRaises(core.ServiceError):
            core.create_appointment(self.g1["id"], self.a["id"],
                                    "2099-05-01T10:00:00", "2099-05-01T11:00:00")
        # 清洁不合格：仍不可预约，并产生新的待清洁记录
        rec = core.list_cleaning_records(gown_id=self.g1["id"], status="pending")[0]
        core.update_cleaning(rec["id"], "failed", "顽固污渍")
        self.assertEqual(core.get_gown(self.g1["id"])["cleaning_status"], "failed")
        with self.assertRaises(core.ServiceError):
            core.create_appointment(self.g1["id"], self.a["id"],
                                    "2099-05-01T10:00:00", "2099-05-01T11:00:00")
        pending = core.list_cleaning_records(gown_id=self.g1["id"], status="pending")
        self.assertEqual(len(pending), 1)
        # 重新清洁合格：恢复可约
        core.update_cleaning(pending[0]["id"], "passed", "复查通过")
        self.assertEqual(core.get_gown(self.g1["id"])["status"], "available")
        self.assertEqual(core.get_gown(self.g1["id"])["cleaning_status"], "clean")
        core.create_appointment(self.g1["id"], self.a["id"],
                                "2099-05-01T10:00:00", "2099-05-01T11:00:00")

    def test_confirmed_inspection_append_only(self):
        """已确认返店结果只能追加复核，不能改检查项/扣款。"""
        order = self.mk_order()
        ins = core.create_return_inspection(order["id"])
        core.update_inspection_items(
            ins["id"], [{"key": x["key"], "result": "ok", "note": ""} for x in ins["items"]], [])
        core.confirm_inspection(ins["id"])
        with self.assertRaises(core.ServiceError):
            core.update_inspection_items(ins["id"], [], [])
        with self.assertRaises(core.ServiceError):
            core.add_inspection_deduction(ins["id"], "hem", 10, "x",
                                          [{"data_url": photo(), "slot": "d"}])
        core.add_inspection_review(ins["id"], "店长复核：无异议")
        core.add_inspection_review(ins["id"], "财务复核：已退款")
        review = core.get_inspection(ins["id"])["review"]
        self.assertIn("店长复核", review)
        self.assertIn("财务复核", review)


# ============================================================ HTTP API 冒烟
class TestHttpApi(unittest.TestCase):
    server = None
    thread = None
    port = None

    @classmethod
    def setUpClass(cls):
        if "--http" not in sys.argv:
            raise unittest.SkipTest("跳过 HTTP 测试（加 --http 启用）")
        reset_db()
        import threading
        from http.server import ThreadingHTTPServer
        import server as srv
        core.init_db()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def _call(self, method, path, body=None):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except Exception as e:
            payload = getattr(e, "read", lambda: b"{}")()
            return getattr(e, "code", 500), json.loads(payload.decode() or "{}")

    def test_api_flow_and_competition(self):
        _, ca = self._call("POST", "/api/customers", {"name": "接口客户甲"})
        _, cb = self._call("POST", "/api/customers", {"name": "接口客户乙"})
        _, cg = self._call("POST", "/api/gowns",
                           {"code": "API-W1", "name": "接口礼服", "size": "M", "deposit_yuan": 1000})
        gid, aid, bid = cg["data"]["id"], ca["data"]["id"], cb["data"]["id"]
        s1, a1 = self._call("POST", "/api/appointments",
                            {"gown_id": gid, "customer_id": aid,
                             "start_time": "2099-07-01T10:00:00", "end_time": "2099-07-01T11:00:00"})
        self.assertEqual(s1, 200)
        # 重叠竞争返回业务错误
        s2, a2 = self._call("POST", "/api/appointments",
                            {"gown_id": gid, "customer_id": bid,
                             "start_time": "2099-07-01T10:30:00", "end_time": "2099-07-01T11:30:00"})
        self.assertEqual(s2, 400)
        self.assertFalse(a2["ok"])
        # 客户隔离
        _, mine = self._call("GET", f"/api/appointments?customer_id={aid}")
        self.assertTrue(all(x["customer_id"] == aid for x in mine["data"]))
        self.assertEqual(len(mine["data"]), 1)


if __name__ == "__main__":
    core.init_db()
    unittest.main(verbosity=2, argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--http"])
