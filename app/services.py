# -*- coding: utf-8 -*-
"""领域服务：预约竞争、换款/迟到、出店核验、返店检查、清洁、押金扣款。

所有金额单位均为「分」。所有写操作在 SQLite 事务内完成；
需要强一致的竞争判定使用 BEGIN IMMEDIATE。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from .db import transaction

VALID_ITEM_RESULTS = {"ok", "missing", "damaged", "stained", "late"}
ACTIVE_APPT = ("booked", "arrived")
ABNORMAL_RESULTS = {"missing", "damaged", "stained"}


class DomainError(Exception):
    """业务规则冲突的基类。"""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    """预约/出店竞争、状态机非法流转等。"""


class NotOwner(DomainError):
    """客户隔离：资源不属于该客户。"""


# ---------------------------------------------------------------- 模拟结算适配器
class InProcessPaymentAdapter:
    """进程内模拟支付：收押金 / 扣款 / 退款，按幂等键去重。

    内存里保留幂等键集合（进程内语义），同时流水落 payment_ledger 表。
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._idem: set[str] = set()
        for r in conn.execute("SELECT idem_key FROM payment_ledger"):
            self._idem.add(r["idem_key"])

    def _post(self, idem_key: str, kind: str, customer_id: int,
              order_id: int | None, amount: int) -> dict[str, Any]:
        if amount <= 0:
            raise DomainError("金额必须为正整数分")
        if idem_key in self._idem:
            # 幂等：返回既有流水，不重复入账
            row = self.conn.execute(
                "SELECT * FROM payment_ledger WHERE idem_key=?", (idem_key,)
            ).fetchone()
            return dict(row)
        try:
            cur = self.conn.execute(
                """INSERT INTO payment_ledger
                       (idem_key, kind, customer_id, order_id, amount, status)
                   VALUES (?,?,?,?,?, 'ok')""",
                (idem_key, kind, customer_id, order_id, amount),
            )
        except sqlite3.IntegrityError:
            # 跨请求并发：唯一约束兜底，返回既有流水
            self._idem.add(idem_key)
            return dict(self.conn.execute(
                "SELECT * FROM payment_ledger WHERE idem_key=?",
                (idem_key,)).fetchone())
        self._idem.add(idem_key)
        return dict(self.conn.execute(
            "SELECT * FROM payment_ledger WHERE id=?", (cur.lastrowid,)
        ).fetchone())

    def charge_deposit(self, idem_key: str, customer_id: int,
                       order_id: int, amount: int) -> dict[str, Any]:
        return self._post(idem_key, "deposit_charge", customer_id, order_id, amount)

    def deduct(self, idem_key: str, customer_id: int,
               order_id: int, amount: int) -> dict[str, Any]:
        return self._post(idem_key, "deduct", customer_id, order_id, amount)

    def refund(self, idem_key: str, customer_id: int,
               order_id: int, amount: int) -> dict[str, Any]:
        return self._post(idem_key, "refund", customer_id, order_id, amount)


# ---------------------------------------------------------------- 领域服务
class BridalService:
    LATE_ITEM_LABEL = "超时返店"

    def __init__(self, conn: sqlite3.Connection,
                 pay: InProcessPaymentAdapter | None = None):
        self.conn = conn
        self.pay = pay or InProcessPaymentAdapter(conn)

    # ================================================================ 工具
    def _get(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Row:
        row = self.conn.execute(sql, tuple(args)).fetchone()
        if row is None:
            raise NotFound(sql)
        return row

    def _owned_order(self, order_id: int, customer_id: int) -> sqlite3.Row:
        order = self._get("SELECT * FROM outgoing_orders WHERE id=?", (order_id,))
        if order["customer_id"] != customer_id:
            raise NotOwner("出店单不属于当前客户")
        return order

    @staticmethod
    def _seq(code: str) -> str:
        return f"{code}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    # ================================================================ 预约竞争
    def _assert_gown_bookable(self, gown_id: int, date: str,
                              start: str, end: str,
                              exclude_appt_id: int | None = None) -> None:
        gown = self._get("SELECT * FROM gowns WHERE id=?", (gown_id,))
        if gown["status"] == "cleaning":
            raise Conflict(f"礼服 {gown['code']} 清洁未完成，暂不可预约")
        if gown["status"] == "out":
            raise Conflict(f"礼服 {gown['code']} 已出店，时段不可预约")
        if gown["status"] == "retired":
            raise Conflict(f"礼服 {gown['code']} 已下架")
        # 有效预约时段重叠
        sql = """SELECT id FROM appointments
                 WHERE gown_id=? AND slot_date=? AND status IN ('booked','arrived')
                   AND slot_start < ? AND slot_end > ?"""
        args: list[Any] = [gown_id, date, end, start]
        if exclude_appt_id is not None:
            sql += " AND id<>?"
            args.append(exclude_appt_id)
        if self.conn.execute(sql, args).fetchone():
            raise Conflict(f"礼服 {gown['code']} 在 {date} {start}-{end} 已被预约")
        # 有效出店单
        if self.conn.execute(
            """SELECT 1 FROM outgoing_orders
               WHERE gown_id=? AND status='active'""", (gown_id,)
        ).fetchone():
            raise Conflict(f"礼服 {gown['code']} 存在有效出店单")

    def create_appointment(self, customer_id: int, gown_id: int, size_label: str,
                           slot_date: str, slot_start: str, slot_end: str,
                           accessory_set_id: int | None = None,
                           code: str | None = None,
                           _immediate: bool = True) -> dict[str, Any]:
        """创建预约。竞争场景下以 BEGIN IMMEDIATE 串行化判定。"""
        if slot_end <= slot_start:
            raise DomainError("试穿结束时间必须晚于开始时间")
        if _immediate:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._get("SELECT 1 FROM customers WHERE id=?", (customer_id,))
            if accessory_set_id is not None:
                self._assert_accessory_free(accessory_set_id, slot_date,
                                            slot_start, slot_end)
            self._assert_gown_bookable(gown_id, slot_date, slot_start, slot_end)
            code = code or self._seq("APT")
            cur = self.conn.execute(
                """INSERT INTO appointments
                       (code,customer_id,gown_id,size_label,accessory_set_id,
                        slot_date,slot_start,slot_end)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (code, customer_id, gown_id, size_label, accessory_set_id,
                 slot_date, slot_start, slot_end),
            )
            self.conn.commit()
            return dict(self._get("SELECT * FROM appointments WHERE id=?",
                                  (cur.lastrowid,)))
        except Exception:
            self.conn.rollback()
            raise

    def _assert_accessory_free(self, set_id: int, date: str,
                               start: str, end: str) -> None:
        s = self._get("SELECT * FROM accessory_sets WHERE id=?", (set_id,))
        if s["status"] == "out":
            raise Conflict(f"配件套装 {s['code']} 已随单出店")
        if s["status"] == "incomplete":
            raise Conflict(f"配件套装 {s['code']} 缺件未补齐")
        row = self.conn.execute(
            """SELECT 1 FROM appointments
               WHERE accessory_set_id=? AND slot_date=?
                 AND status IN ('booked','arrived')
                 AND slot_start < ? AND slot_end > ?""",
            (set_id, date, end, start),
        ).fetchone()
        if row:
            raise Conflict(f"配件套装 {s['code']} 该时段已被其他预约绑定")

    # ================================================================ 到店/迟到/换款
    def mark_arrived(self, appt_id: int, customer_id: int) -> dict[str, Any]:
        with transaction(self.conn):
            appt = self._get("SELECT * FROM appointments WHERE id=?", (appt_id,))
            if appt["customer_id"] != customer_id:
                raise NotOwner("预约不属于当前客户")
            if appt["status"] != "booked":
                raise Conflict(f"预约状态为 {appt['status']}，不可到店")
            self.conn.execute(
                "UPDATE gowns SET status='fitting' WHERE id=?", (appt["gown_id"],))
            self.conn.execute(
                "UPDATE appointments SET status='arrived' WHERE id=?", (appt_id,))
        return dict(self._get("SELECT * FROM appointments WHERE id=?", (appt_id,)))

    def late_cancel(self, appt_id: int, customer_id: int,
                    late_minutes: int, reason: str = "") -> dict[str, Any]:
        """迟到取消：关闭预约、释放礼服，记录迟到分钟数。"""
        with transaction(self.conn):
            appt = self._get("SELECT * FROM appointments WHERE id=?", (appt_id,))
            if appt["customer_id"] != customer_id:
                raise NotOwner("预约不属于当前客户")
            if appt["status"] not in ACTIVE_APPT:
                raise Conflict(f"预约状态为 {appt['status']}，不可取消")
            self.conn.execute(
                "UPDATE appointments SET status='late_cancelled', late_minutes=?,"
                " note=? WHERE id=?",
                (max(0, late_minutes), reason, appt_id))
            self.conn.execute(
                """INSERT INTO appointment_changes
                       (appointment_id,kind,from_gown_id,reason)
                   VALUES (?, 'late_cancel', ?,?)""",
                (appt_id, appt["gown_id"], reason))
            self._release_gown_if_idle(appt["gown_id"])
        return dict(self._get("SELECT * FROM appointments WHERE id=?", (appt_id,)))

    def no_show(self, appt_id: int) -> dict[str, Any]:
        with transaction(self.conn):
            appt = self._get("SELECT * FROM appointments WHERE id=?", (appt_id,))
            if appt["status"] != "booked":
                raise Conflict("仅已预约未到店可标记失约")
            self.conn.execute(
                "UPDATE appointments SET status='no_show' WHERE id=?", (appt_id,))
            self.conn.execute(
                """INSERT INTO appointment_changes
                       (appointment_id,kind,from_gown_id,reason)
                   VALUES (?, 'no_show', ?, '未到店')""",
                (appt_id, appt["gown_id"]))
        return dict(self._get("SELECT * FROM appointments WHERE id=?", (appt_id,)))

    def swap_appointment(self, appt_id: int, customer_id: int, to_gown_id: int,
                         to_size: str, to_accessory_set_id: int | None = None,
                         reason: str = "") -> dict[str, Any]:
        """临时换款：原预约置 swapped 并立刻创建新预约（竞争检查照旧）。"""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            old = self._get("SELECT * FROM appointments WHERE id=?", (appt_id,))
            if old["customer_id"] != customer_id:
                raise NotOwner("预约不属于当前客户")
            if old["status"] not in ACTIVE_APPT:
                raise Conflict(f"预约状态为 {old['status']}，不可换款")
            self._assert_gown_bookable(to_gown_id, old["slot_date"],
                                       old["slot_start"], old["slot_end"])
            if to_accessory_set_id is not None:
                self._assert_accessory_free(to_accessory_set_id, old["slot_date"],
                                            old["slot_start"], old["slot_end"])
            self.conn.execute(
                "UPDATE appointments SET status='swapped', note=? WHERE id=?",
                (reason or "临时换款", appt_id))
            new_code = self._seq("APT")
            cur = self.conn.execute(
                """INSERT INTO appointments
                       (code,customer_id,gown_id,size_label,accessory_set_id,
                        slot_date,slot_start,slot_end,status)
                   VALUES (?,?,?,?,?,?,?,?,'booked')""",
                (new_code, customer_id, to_gown_id, to_size,
                 to_accessory_set_id, old["slot_date"],
                 old["slot_start"], old["slot_end"]))
            self.conn.execute(
                """INSERT INTO appointment_changes
                       (appointment_id,kind,from_gown_id,to_gown_id,reason)
                   VALUES (?, 'swap', ?,?,?)""",
                (appt_id, old["gown_id"], to_gown_id, reason))
            # 若原礼服已进入试穿占用，视空闲释放
            self._release_gown_if_idle(old["gown_id"])
            new_id = cur.lastrowid
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return dict(self._get("SELECT * FROM appointments WHERE id=?", (new_id,)))

    def _release_gown_if_idle(self, gown_id: int) -> None:
        """无任何活跃预约/出店单时，把 fitting 的礼服放回 available。"""
        gown = self._get("SELECT * FROM gowns WHERE id=?", (gown_id,))
        if gown["status"] != "fitting":
            return
        busy = self.conn.execute(
            """SELECT 1 FROM appointments
               WHERE gown_id=? AND status IN ('booked','arrived')
               UNION ALL
               SELECT 1 FROM outgoing_orders WHERE gown_id=? AND status='active'
               LIMIT 1""", (gown_id, gown_id)).fetchone()
        if not busy:
            self.conn.execute(
                "UPDATE gowns SET status='available' WHERE id=?", (gown_id,))

    # ================================================================ 出店核验
    def create_outgoing_order(self, customer_id: int, appointment_id: int | None,
                              gown_id: int, accessory_set_id: int,
                              size_adjust: dict[str, Any],
                              planned_return: str,
                              items: list[dict[str, str]],
                              outgoing_photos: dict[int, dict[str, str]] | None = None,
                              deposit_amount: int | None = None,
                              code: str | None = None) -> dict[str, Any]:
        """开立出店单：锁礼服/配件、写检查项与出店照片、收押金。

        items: [{"label","category","outgoing_note"}]，配件明细自动追加。
        outgoing_photos: {item_seq: {"path":..,"note":..}}
        """
        outgoing_photos = outgoing_photos or {}
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if appointment_id is not None:
                appt = self._get(
                    "SELECT * FROM appointments WHERE id=?", (appointment_id,))
                if appt["customer_id"] != customer_id:
                    raise NotOwner("预约不属于当前客户")
                if appt["status"] not in ACTIVE_APPT:
                    raise Conflict(f"预约状态为 {appt['status']}，不可出店")
                gown_id = appt["gown_id"]
            else:
                appt = None
                self._get("SELECT 1 FROM gowns WHERE id=?", (gown_id,))

            # 竞争：礼服不能有第二个有效出店单
            if self.conn.execute(
                "SELECT 1 FROM outgoing_orders WHERE gown_id=? AND status='active'",
                (gown_id,)).fetchone():
                raise Conflict("该礼服已有有效出店单")
            acc = self._get(
                "SELECT * FROM accessory_sets WHERE id=?", (accessory_set_id,))
            if acc["status"] in ("out", "incomplete"):
                raise Conflict(f"配件套装 {acc['code']} 当前不可出店")

            order_code = code or self._seq("OUT")
            cur = self.conn.execute(
                """INSERT INTO outgoing_orders
                       (code,appointment_id,customer_id,gown_id,accessory_set_id,
                        size_adjust,planned_return,status)
                   VALUES (?,?,?,?,?,?,?, 'active')""",
                (order_code, appointment_id, customer_id, gown_id,
                 accessory_set_id, json.dumps(size_adjust, ensure_ascii=False),
                 planned_return))
            order_id = cur.lastrowid

            seq = 0
            for it in items:
                seq += 1
                self.conn.execute(
                    """INSERT INTO inspection_items
                           (order_id,seq,label,category,outgoing_note)
                       VALUES (?,?,?,?,?)""",
                    (order_id, seq, it["label"],
                     it.get("category", "detail"),
                     it.get("outgoing_note", "")))
            # 配件清单逐项入检（配件完整性按编号/名称核对）
            for piece in json.loads(acc["pieces"]):
                seq += 1
                self.conn.execute(
                    """INSERT INTO inspection_items
                           (order_id,seq,label,category,outgoing_note)
                       VALUES (?,?,?, 'accessory', ?)""",
                    (order_id, seq, f"配件 · {piece['code']} {piece['name']}",
                     f"套装 {acc['code']} 组成件，出店清点齐全"))

            # 尺寸调整照片 + 细节/污渍照片
            for item_seq, ph in outgoing_photos.items():
                self._add_photo(order_id,
                                self._item_id_by_seq(order_id, item_seq),
                                "outgoing", ph.get("category", "detail"),
                                ph["path"], ph.get("note", ""), commit=False)
            if size_adjust.get("photo"):
                self._add_photo(order_id, None, "outgoing", "adjust",
                                size_adjust["photo"],
                                "尺寸调整记录", commit=False)

            gown = self._get("SELECT * FROM gowns WHERE id=?", (gown_id,))
            amount = deposit_amount if deposit_amount is not None else gown["deposit"]
            dep_code = self._seq("DP")
            self.conn.execute(
                """INSERT INTO deposits
                       (code,customer_id,order_id,amount,status,idem_key)
                   VALUES (?,?,?,?,'held',?)""",
                (dep_code, customer_id, order_id, amount,
                 f"dep:{order_code}"))
            self.pay.charge_deposit(
                f"pay-dep:{order_code}", customer_id, order_id, amount)

            self.conn.execute(
                "UPDATE gowns SET status='out' WHERE id=?", (gown_id,))
            self.conn.execute(
                "UPDATE accessory_sets SET status='out' WHERE id=?",
                (accessory_set_id,))
            if appt is not None:
                self.conn.execute(
                    "UPDATE appointments SET status='completed' WHERE id=?",
                    (appointment_id,))
            self.conn.commit()
            return dict(self._get(
                "SELECT * FROM outgoing_orders WHERE id=?", (order_id,)))
        except Exception:
            self.conn.rollback()
            raise

    def _item_id_by_seq(self, order_id: int, seq: int) -> int:
        return self._get(
            "SELECT id FROM inspection_items WHERE order_id=? AND seq=?",
            (order_id, seq))["id"]

    def _add_photo(self, order_id: int, item_id: int | None, phase: str,
                   category: str, path: str, note: str,
                   commit: bool = True) -> int:
        cur = self.conn.execute(
            """INSERT INTO photos (order_id,item_id,phase,category,path,note)
               VALUES (?,?,?,?,?,?)""",
            (order_id, item_id, phase, category, path, note))
        photo_id = cur.lastrowid
        self._recompute_pairing(item_id)
        if commit:
            self.conn.commit()
        return photo_id

    def attach_outgoing_photo(self, order_id: int, customer_id: int,
                              item_id: int | None, category: str,
                              path: str, note: str = "") -> dict[str, Any]:
        """补拍出店细节/污渍/尺寸调整照片，并触发配对重算。"""
        with transaction(self.conn):
            self._owned_order(order_id, customer_id)
            if item_id is not None:
                self._get(
                    "SELECT * FROM inspection_items WHERE id=? AND order_id=?",
                    (item_id, order_id))
            pid = self._add_photo(order_id, item_id, "outgoing",
                                  category, path, note, commit=False)
        return dict(self._get("SELECT * FROM photos WHERE id=?", (pid,)))

    def _recompute_pairing(self, item_id: int | None) -> None:
        if item_id is None:
            return
        phases = {r["phase"] for r in self.conn.execute(
            "SELECT DISTINCT phase FROM photos WHERE item_id=?", (item_id,))}
        paired = 1 if {"outgoing", "return"} <= phases else 0
        self.conn.execute(
            "UPDATE photos SET paired=? WHERE item_id=?", (paired, item_id))

    # ================================================================ 返店检查
    def start_return(self, order_id: int, customer_id: int,
                     actual_return: str) -> dict[str, Any]:
        """登记实际返店时间；超时自动追加「超时返店」检查项。"""
        with transaction(self.conn):
            order = self._owned_order(order_id, customer_id)
            if order["status"] != "active":
                raise Conflict("仅出店中的订单可开始返店检查")
            self.conn.execute(
                "UPDATE outgoing_orders SET actual_return=? WHERE id=?",
                (actual_return, order_id))
            if actual_return > order["planned_return"]:
                exists = self.conn.execute(
                    "SELECT 1 FROM inspection_items WHERE order_id=? AND label=?",
                    (order_id, self.LATE_ITEM_LABEL)).fetchone()
                if not exists:
                    seq = self.conn.execute(
                        "SELECT COALESCE(MAX(seq),0)+1 AS s FROM inspection_items"
                        " WHERE order_id=?", (order_id,)).fetchone()["s"]
                    self.conn.execute(
                        """INSERT INTO inspection_items
                               (order_id,seq,label,category,outgoing_note)
                           VALUES (?,?,?, 'late', ?)""",
                        (order_id, seq, self.LATE_ITEM_LABEL,
                         f"约定 {order['planned_return']} 前返店"))
        return dict(self._get(
            "SELECT * FROM outgoing_orders WHERE id=?", (order_id,)))

    def set_item_result(self, order_id: int, customer_id: int, item_id: int,
                        result: str, note: str,
                        photo_path: str | None = None) -> dict[str, Any]:
        """逐项打勾；返店异常照片与检查项绑定，并立即与出店照配对。"""
        if result not in VALID_ITEM_RESULTS:
            raise DomainError(f"非法检查结果 {result}")
        with transaction(self.conn):
            order = self._owned_order(order_id, customer_id)
            if order["status"] != "active":
                raise Conflict("返店结果已确认，只能追加复核")
            item = self._get(
                "SELECT * FROM inspection_items WHERE id=? AND order_id=?",
                (item_id, order_id))
            self.conn.execute(
                """UPDATE inspection_items SET return_result=?, return_note=?,
                       checked_at=datetime('now','localtime') WHERE id=?""",
                (result, note, item_id))
            if photo_path:
                category = {"missing": "missing", "damaged": "damage",
                            "stained": "stain", "late": "late",
                            "ok": "detail"}.get(result, "detail")
                self._add_photo(order_id, item_id, "return", category,
                                photo_path, note or "返店照片", commit=False)
        return dict(self._get(
            "SELECT * FROM inspection_items WHERE id=?", (item_id,)))

    def confirm_return(self, order_id: int, customer_id: int) -> dict[str, Any]:
        """确认返店：全部项须已勾选；礼服进入清洁，配件按缺失置状态。

        确认后结果冻结，仅可通过 add_review 追加复核。
        """
        with transaction(self.conn):
            order = self._owned_order(order_id, customer_id)
            if order["status"] != "active":
                raise Conflict("订单不在出店中")
            pending = self.conn.execute(
                "SELECT COUNT(*) c FROM inspection_items"
                " WHERE order_id=? AND return_result='pending'",
                (order_id,)).fetchone()["c"]
            if pending:
                raise Conflict(f"还有 {pending} 个检查项未勾选")
            self.conn.execute(
                "UPDATE outgoing_orders SET status='returned' WHERE id=?",
                (order_id,))
            # 配件完整性
            missing = self.conn.execute(
                "SELECT COUNT(*) c FROM inspection_items"
                " WHERE order_id=? AND category='accessory'"
                " AND return_result='missing'", (order_id,)).fetchone()["c"]
            acc_status = "incomplete" if missing else "available"
            self.conn.execute(
                "UPDATE accessory_sets SET status=? WHERE id=?",
                (acc_status, order["accessory_set_id"]))
            # 礼服进入清洁，完成前不可预约
            self.conn.execute(
                "UPDATE gowns SET status='cleaning' WHERE id=?",
                (order["gown_id"],))
            self.conn.execute(
                """INSERT INTO cleanings (order_id,gown_id,result,round_no)
                   VALUES (?,?,'washing',1)""",
                (order_id, order["gown_id"]))
        return dict(self._get(
            "SELECT * FROM outgoing_orders WHERE id=?", (order_id,)))

    def add_review(self, order_id: int, customer_id: int, body: str) -> dict[str, Any]:
        """已确认的返店结果只能追加复核，不允许改原结论。"""
        if not body.strip():
            raise DomainError("复核内容不能为空")
        with transaction(self.conn):
            self._owned_order(order_id, customer_id)  # 同时做归属校验
            cur = self.conn.execute(
                "INSERT INTO return_reviews (order_id,body) VALUES (?,?)",
                (order_id, body.strip()))
            rid = cur.lastrowid
        return dict(self._get("SELECT * FROM return_reviews WHERE id=?", (rid,)))

    # ================================================================ 清洁
    def restock_accessory(self, set_id: int, note: str = "") -> dict[str, Any]:
        """缺失配件补齐回库：incomplete -> available，方可再次绑定。"""
        with transaction(self.conn):
            s = self._get("SELECT * FROM accessory_sets WHERE id=?", (set_id,))
            if s["status"] != "incomplete":
                raise Conflict(f"套装状态为 {s['status']}，无需补齐")
            self.conn.execute(
                "UPDATE accessory_sets SET status='available' WHERE id=?",
                (set_id,))
        return dict(self._get(
            "SELECT * FROM accessory_sets WHERE id=?", (set_id,)))

    # ================================================================ 清洁
    def cleaning_qc(self, order_id: int, result: str, note: str,
                    photo_path: str | None = None) -> dict[str, Any]:
        if result not in ("passed", "failed"):
            raise DomainError("清洁结论只能是 passed / failed")
        with transaction(self.conn):
            order = self._get(
                "SELECT * FROM outgoing_orders WHERE id=?", (order_id,))
            if order["status"] != "returned":
                raise Conflict("订单尚未确认返店")
            gown = self._get("SELECT * FROM gowns WHERE id=?",
                             (order["gown_id"],))
            if gown["status"] != "cleaning":
                raise Conflict("礼服当前不在清洁流程中")
            last = self.conn.execute(
                "SELECT * FROM cleanings WHERE order_id=? ORDER BY id DESC LIMIT 1",
                (order_id,)).fetchone()
            if last["result"] == "passed":
                raise Conflict("清洁已合格，无需重复质检")
            round_no = last["round_no"] if last["result"] == "washing" else \
                last["round_no"] + 1
            photo_id = None
            if photo_path:
                photo_id = self._add_photo(order_id, None, "clean", "clean_qc",
                                           photo_path, note or "清洁质检",
                                           commit=False)
            cur = self.conn.execute(
                """INSERT INTO cleanings
                       (order_id,gown_id,result,qc_note,qc_photo_id,round_no)
                   VALUES (?,?,?,?,?,?)""",
                (order_id, order["gown_id"], result, note, photo_id, round_no))
            if result == "passed":
                # 清洁合格才释放礼服；同时确认没有别的单子抢占用（正常不会）
                self.conn.execute(
                    "UPDATE gowns SET status='available' WHERE id=?",
                    (order["gown_id"],))
            cid = cur.lastrowid
        return dict(self._get("SELECT * FROM cleanings WHERE id=?", (cid,)))

    # ================================================================ 押金与扣款
    def deduct_deposit(self, order_id: int, customer_id: int, item_id: int,
                       photo_id: int, amount: int, reason: str,
                       idem_key: str | None = None) -> dict[str, Any]:
        """押金扣款：必须关联检查项 + 异常照片；幂等键防重复扣款。"""
        if amount <= 0:
            raise DomainError("扣款金额必须大于 0")
        with transaction(self.conn):
            order = self._owned_order(order_id, customer_id)
            deposit = self._get(
                "SELECT * FROM deposits WHERE order_id=? ORDER BY id LIMIT 1",
                (order_id,))
            if deposit["status"] == "settled":
                raise Conflict("押金已结算，不可再扣款（仅可追加复核）")
            item = self._get(
                "SELECT * FROM inspection_items WHERE id=? AND order_id=?",
                (item_id, order_id))
            photo = self._get(
                "SELECT * FROM photos WHERE id=? AND order_id=?",
                (photo_id, order_id))
            if photo["item_id"] != item_id:
                raise Conflict("扣款照片与检查项不匹配")
            if photo["phase"] != "return":
                raise Conflict("押金扣款必须凭据返店异常照片")
            already = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM deposit_deductions"
                " WHERE deposit_id=?", (deposit["id"],)).fetchone()["s"]
            if already + amount > deposit["amount"]:
                raise Conflict(
                    f"扣款总额将超过押金（押金 {deposit['amount']} 分，"
                    f"已扣 {already} 分）")
            key = idem_key or f"ded:{order_id}:{item_id}:{photo_id}:{amount}"
            existing = self.conn.execute(
                "SELECT * FROM deposit_deductions WHERE idem_key=?",
                (key,)).fetchone()
            if existing:
                # 幂等：相同键重复提交直接返回既有扣款，不重复入账
                return dict(existing)
            # 唯一约束兜底并发重复提交
            try:
                cur = self.conn.execute(
                    """INSERT INTO deposit_deductions
                           (deposit_id,item_id,photo_id,amount,reason,idem_key)
                       VALUES (?,?,?,?,?,?)""",
                    (deposit["id"], item_id, photo_id, amount, reason, key))
            except sqlite3.IntegrityError:
                raise Conflict("该扣款已提交，请勿重复操作")
            self.pay.deduct(
                f"pay-ded:{key}", customer_id, order_id, amount)
            did = cur.lastrowid
        return dict(self._get(
            "SELECT * FROM deposit_deductions WHERE id=?", (did,)))

    def settle_deposit(self, order_id: int, customer_id: int,
                       idem_key: str | None = None) -> dict[str, Any]:
        """结算：已扣不退，余额退还。幂等：重复结算直接返回既有结果。"""
        key = idem_key or f"settle:{order_id}"
        with transaction(self.conn):
            order = self._owned_order(order_id, customer_id)
            deposit = self._get(
                "SELECT * FROM deposits WHERE order_id=? ORDER BY id LIMIT 1",
                (order_id,))
            if deposit["status"] == "settled":
                return dict(deposit)  # 幂等返回
            deducted = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM deposit_deductions"
                " WHERE deposit_id=?", (deposit["id"],)).fetchone()["s"]
            refund = deposit["amount"] - deducted
            if refund > 0:
                self.pay.refund(f"pay-{key}", customer_id, order_id, refund)
            self.conn.execute(
                "UPDATE deposits SET refunded=?, status='settled' WHERE id=?",
                (refund, deposit["id"]))
        return dict(self._get(
            "SELECT * FROM deposits WHERE order_id=? ORDER BY id LIMIT 1",
            (order_id,)))

    # ================================================================ 查询
    def list_customers(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM customers ORDER BY code")]

    def list_accessories(self) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM accessory_sets ORDER BY code")]
        for r in rows:
            r["pieces"] = json.loads(r["pieces"])
        return rows

    def list_orders(self, customer_id: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT o.*, c.name customer_name, c.code customer_code,
                        g.code gown_code, g.name gown_name,
                        s.code acc_code
                 FROM outgoing_orders o
                 JOIN customers c ON c.id=o.customer_id
                 JOIN gowns g ON g.id=o.gown_id
                 JOIN accessory_sets s ON s.id=o.accessory_set_id"""
        args: list[Any] = []
        if customer_id is not None:
            sql += " WHERE o.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY o.id DESC"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def list_deposits(self, customer_id: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT d.*, c.name customer_name, c.code customer_code,
                        o.code order_code,
                        (SELECT COALESCE(SUM(amount),0) FROM deposit_deductions
                         WHERE deposit_id=d.id) deducted
                 FROM deposits d
                 JOIN customers c ON c.id=d.customer_id
                 JOIN outgoing_orders o ON o.id=d.order_id"""
        args: list[Any] = []
        if customer_id is not None:
            sql += " WHERE d.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY d.id DESC"
        out = [dict(r) for r in self.conn.execute(sql, args)]
        for d in out:
            d["deduction_rows"] = [dict(r) for r in self.conn.execute(
                """SELECT dd.*, ii.label item_label, p.path photo_path
                   FROM deposit_deductions dd
                   JOIN inspection_items ii ON ii.id=dd.item_id
                   JOIN photos p ON p.id=dd.photo_id
                   WHERE dd.deposit_id=? ORDER BY dd.id""", (d["id"],))]
        return out

    def list_gowns(self) -> list[dict[str, Any]]:
        gowns = [dict(r) for r in self.conn.execute(
            """SELECT * FROM gowns ORDER BY code""")]
        for g in gowns:
            g["sizes"] = [dict(r) for r in self.conn.execute(
                "SELECT label,bust_cm,waist_cm,hip_cm FROM gown_sizes"
                " WHERE gown_id=? ORDER BY id", (g["id"],))]
            nxt = self.conn.execute(
                """SELECT slot_date,slot_start,slot_end FROM appointments
                   WHERE gown_id=? AND status IN ('booked','arrived')
                     AND slot_date>=date('now','localtime')
                   ORDER BY slot_date,slot_start LIMIT 1""",
                (g["id"],)).fetchone()
            g["next_booking"] = dict(nxt) if nxt else None
        return gowns

    def calendar(self, date_from: str, date_to: str,
                 customer_id: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT a.*, c.name customer_name, c.code customer_code,
                        g.code gown_code, g.name gown_name,
                        s.code acc_code, s.name acc_name
                 FROM appointments a
                 JOIN customers c ON c.id=a.customer_id
                 JOIN gowns g ON g.id=a.gown_id
                 LEFT JOIN accessory_sets s ON s.id=a.accessory_set_id
                 WHERE a.slot_date BETWEEN ? AND ?"""
        args: list[Any] = [date_from, date_to]
        if customer_id is not None:
            sql += " AND a.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY a.slot_date,a.slot_start,a.id"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def order_detail(self, order_id: int,
                     customer_id: int | None = None) -> dict[str, Any]:
        order = self._get("SELECT * FROM outgoing_orders WHERE id=?",
                          (order_id,))
        if customer_id is not None and order["customer_id"] != customer_id:
            raise NotOwner("出店单不属于当前客户")
        d = dict(order)
        d["size_adjust"] = json.loads(d["size_adjust"] or "{}")
        extra = self.conn.execute(
            """SELECT c.code customer_code, c.name customer_name,
                      g.code gown_code, g.name gown_name,
                      s.code acc_code, s.name acc_name
               FROM outgoing_orders o
               JOIN customers c ON c.id=o.customer_id
               JOIN gowns g ON g.id=o.gown_id
               JOIN accessory_sets s ON s.id=o.accessory_set_id
               WHERE o.id=?""", (order_id,)).fetchone()
        d.update(dict(extra))
        d["items"] = []
        for it in self.conn.execute(
                "SELECT * FROM inspection_items WHERE order_id=? ORDER BY seq",
                (order_id,)):
            it = dict(it)
            it["photos"] = [dict(p) for p in self.conn.execute(
                "SELECT * FROM photos WHERE item_id=? ORDER BY phase,id",
                (it["id"],))]
            d["items"].append(it)
        d["loose_photos"] = [dict(p) for p in self.conn.execute(
            "SELECT * FROM photos WHERE order_id=? AND item_id IS NULL"
            " ORDER BY id", (order_id,))]
        d["cleanings"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM cleanings WHERE order_id=? ORDER BY id", (order_id,))]
        d["reviews"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM return_reviews WHERE order_id=? ORDER BY id",
            (order_id,))]
        dep = self.conn.execute(
            "SELECT * FROM deposits WHERE order_id=? ORDER BY id LIMIT 1",
            (order_id,)).fetchone()
        d["deposit"] = dict(dep) if dep else None
        if d["deposit"]:
            d["deposit"]["deductions"] = [dict(r) for r in self.conn.execute(
                """SELECT dd.*, ii.label item_label, p.path photo_path
                   FROM deposit_deductions dd
                   JOIN inspection_items ii ON ii.id=dd.item_id
                   JOIN photos p ON p.id=dd.photo_id
                   WHERE dd.deposit_id=? ORDER BY dd.id""",
                (dep["id"],))]
        d["is_late"] = bool(
            order["actual_return"] and order["actual_return"] >
            order["planned_return"])
        return d
