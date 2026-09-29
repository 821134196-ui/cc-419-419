"""婚纱礼服试穿与返店清点系统 — 核心数据层与业务规则。

零依赖，仅使用 Python 标准库。SQLite 保存预约与押金，本地目录保存照片，
结算使用进程内模拟适配器。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BRIDAL_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "bridal.db")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")

# 金额以「分」为单位整数存储
def yuan_to_cents(yuan: float) -> int:
    return int(round(yuan * 100))

def cents_to_yuan(cents: int) -> float:
    return cents / 100.0

# ---------------------------------------------------------------------------
# 领域常量
# ---------------------------------------------------------------------------
class GownStatus:
    AVAILABLE = "available"      # 在店可约
    RESERVED = "reserved"        # 预约锁定
    OUT = "out"                  # 已出店
    CLEANING = "cleaning"        # 清洁中

class CleaningStatus:
    CLEAN = "clean"              # 清洁完成
    PENDING = "pending"          # 待清洁
    FAILED = "failed"            # 清洁不合格

class AppointmentStatus:
    BOOKED = "booked"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    LATE_CANCELLED = "late_cancelled"   # 迟到取消
    SWAPPED = "swapped"                 # 临时换款

class OrderStatus:
    OUT = "out"
    RETURNED = "returned"
    CLOSED = "closed"

class InspectionStatus:
    DRAFT = "draft"
    CONFIRMED = "confirmed"

class CleaningRecordStatus:
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"

class DepositStatus:
    PAID = "paid"
    REFUNDED = "refunded"
    DEDUCTED = "deducted"

# 返店检查清单项（礼服通用基线）
GOWN_CHECKLIST = [
    {"key": "appearance", "label": "外观整体", "kind": "gown"},
    {"key": "lining", "label": "内衬", "kind": "gown"},
    {"key": "zipper", "label": "拉链/扣袢", "kind": "gown"},
    {"key": "beading", "label": "钉珠/蕾丝", "kind": "gown"},
    {"key": "hem", "label": "裙摆", "kind": "gown"},
    {"key": "stains", "label": "污渍", "kind": "gown"},
    {"key": "damage", "label": "破损", "kind": "gown"},
]

# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------
class ServiceError(Exception):
    """业务错误，message 为中文提示。"""
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code

# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
_lock = threading.RLock()

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    avatar TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    style TEXT,
    color TEXT,
    size TEXT,
    deposit_amount INTEGER NOT NULL DEFAULT 0,
    photo TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    cleaning_status TEXT NOT NULL DEFAULT 'clean',
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accessory_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accessory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id INTEGER NOT NULL REFERENCES accessory_sets(id),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(set_id, code)
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    gown_id INTEGER NOT NULL REFERENCES gowns(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked',
    swap_from_gown_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appt_gown ON appointments(gown_id, status);

CREATE TABLE IF NOT EXISTS out_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    gown_id INTEGER NOT NULL REFERENCES gowns(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    appointment_id INTEGER REFERENCES appointments(id),
    accessory_set_id INTEGER REFERENCES accessory_sets(id),
    status TEXT NOT NULL DEFAULT 'out',
    deposit_amount INTEGER NOT NULL DEFAULT 0,
    deposit_status TEXT NOT NULL DEFAULT 'paid',
    size_adjustments TEXT,
    pre_stains TEXT,
    out_photos TEXT,
    out_time TEXT NOT NULL,
    expected_return_time TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_gown ON out_orders(gown_id, status);

CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    out_order_id INTEGER UNIQUE NOT NULL REFERENCES out_orders(id),
    status TEXT NOT NULL DEFAULT 'draft',
    items TEXT,
    deductions TEXT,
    paired_photos TEXT,
    review TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cleaning_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gown_id INTEGER NOT NULL REFERENCES gowns(id),
    out_order_id INTEGER REFERENCES out_orders(id),
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    out_order_id INTEGER UNIQUE NOT NULL REFERENCES out_orders(id),
    amount INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'paid',
    idempotency_key TEXT UNIQUE NOT NULL,
    deduction_total INTEGER NOT NULL DEFAULT 0,
    refund_amount INTEGER NOT NULL DEFAULT 0,
    settle_result TEXT,
    settled_at TEXT,
    created_at TEXT NOT NULL
);
"""

def init_db() -> None:
    os.makedirs(PHOTO_DIR, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def gen_code(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

# ---------------------------------------------------------------------------
# 照片
# ---------------------------------------------------------------------------
def save_photo(data_url: str, slot: str) -> dict:
    """保存 base64 dataURL 照片到本地目录，返回 {file, slot, url}。"""
    if not data_url or not data_url.startswith("data:"):
        raise ServiceError("照片格式不正确，需为 dataURL")
    header, _, b64 = data_url.partition(",")
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    elif "svg" in header:
        ext = "svg"
    elif "webp" in header:
        ext = "webp"
    raw = base64_b64decode(b64)
    fname = f"{slot}_{uuid.uuid4().hex[:8]}.{ext}"
    with open(os.path.join(PHOTO_DIR, fname), "wb") as f:
        f.write(raw)
    return {"file": fname, "slot": slot, "url": f"/photos/{fname}"}

def base64_b64decode(s: str) -> bytes:
    import base64
    return base64.b64decode(s)

# ---------------------------------------------------------------------------
# 结算适配器（进程内模拟）
# ---------------------------------------------------------------------------
class SettlementAdapter:
    """进程内模拟结算适配器，支持幂等扣款。

    以 idempotency_key 去重：同一笔押金退款/扣款只结算一次，
    重复调用返回首次结果。
    """
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}

    def settle(self, idempotency_key: str, amount: int, reason: str) -> dict:
        if idempotency_key in self._records:
            rec = self._records[idempotency_key]
            return {**rec, "idempotent_replay": True}
        rec = {
            "idempotency_key": idempotency_key,
            "amount": amount,
            "reason": reason,
            "settled_at": now_iso(),
            "channel": "inprocess-mock",
            "settlement_no": gen_code("STL"),
            "idempotent_replay": False,
        }
        self._records[idempotency_key] = rec
        return rec

SETTLEMENT = SettlementAdapter()

# ---------------------------------------------------------------------------
# 客户
# ---------------------------------------------------------------------------
def create_customer(name: str, phone: str = "", note: str = "", avatar: str = "") -> dict:
    with _lock:
        conn = get_db()
        try:
            code = gen_code("CUS")
            conn.execute(
                "INSERT INTO customers (code, name, phone, avatar, note, created_at) VALUES (?,?,?,?,?,?)",
                (code, name, phone, avatar, note, now_iso()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM customers WHERE code=?", (code,)).fetchone()
            return dict(row)
        finally:
            conn.close()

def list_customers() -> list[dict]:
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id").fetchall()]
    finally:
        conn.close()

def get_customer(customer_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# 礼服
# ---------------------------------------------------------------------------
def create_gown(code: str, name: str, style: str = "", color: str = "", size: str = "",
                deposit_yuan: float = 0, photo: str = "", note: str = "") -> dict:
    with _lock:
        conn = get_db()
        try:
            if conn.execute("SELECT 1 FROM gowns WHERE code=?", (code,)).fetchone():
                raise ServiceError(f"礼服编号 {code} 已存在")
            conn.execute(
                """INSERT INTO gowns (code, name, style, color, size, deposit_amount, photo, status, cleaning_status, note, created_at)
                   VALUES (?,?,?,?,?,?,?, 'available', 'clean', ?, ?)""",
                (code, name, style, color, size, yuan_to_cents(deposit_yuan), photo, note, now_iso()),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM gowns WHERE code=?", (code,)).fetchone())
        finally:
            conn.close()

def list_gowns(status: Optional[str] = None) -> list[dict]:
    conn = get_db()
    try:
        if status:
            rows = conn.execute("SELECT * FROM gowns WHERE status=? ORDER BY id", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM gowns ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_gown(gown_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM gowns WHERE id=?", (gown_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def update_gown(gown_id: int, **fields) -> dict:
    allowed = {"name", "style", "color", "size", "deposit_amount", "photo", "note"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        raise ServiceError("没有可更新字段")
    with _lock:
        conn = get_db()
        try:
            gown = get_gown(gown_id)
            if not gown:
                raise ServiceError("礼服不存在", 404)
            if "deposit_yuan" in fields:
                sets["deposit_amount"] = yuan_to_cents(fields["deposit_yuan"])
            cols = ", ".join(f"{k}=?" for k in sets)
            conn.execute(f"UPDATE gowns SET {cols} WHERE id=?", (*sets.values(), gown_id))
            conn.commit()
            return dict(conn.execute("SELECT * FROM gowns WHERE id=?", (gown_id,)).fetchone())
        finally:
            conn.close()

def _active_conflict(conn: sqlite3.Connection, gown_id: int,
                     exclude_appt: Optional[int] = None, exclude_order: Optional[int] = None) -> Optional[str]:
    """检查礼服是否存在有效预约或出店单。返回冲突描述，无冲突返回 None。"""
    q = "SELECT code, status FROM appointments WHERE gown_id=? AND status IN ('booked','checked_in')"
    args: list = [gown_id]
    if exclude_appt:
        q += " AND id!=?"
        args.append(exclude_appt)
    r = conn.execute(q, args).fetchone()
    if r:
        return f"礼服存在有效预约 {r['code']}（{r['status']}）"
    q = "SELECT code FROM out_orders WHERE gown_id=? AND status='out'"
    args = [gown_id]
    if exclude_order:
        q += " AND id!=?"
        args.append(exclude_order)
    r = conn.execute(q, args).fetchone()
    if r:
        return f"礼服已出店（出店单 {r['code']}）"
    return None

def _ensure_bookable(conn: sqlite3.Connection, gown: dict) -> None:
    if gown["cleaning_status"] == CleaningStatus.PENDING:
        raise ServiceError("礼服清洁完成前不能预约")
    if gown["cleaning_status"] == CleaningStatus.FAILED:
        raise ServiceError("礼服清洁不合格，需重新清洁后才能预约")
    if gown["status"] == GownStatus.OUT:
        raise ServiceError("礼服已出店，不可预约")
    if gown["status"] == GownStatus.CLEANING:
        raise ServiceError("礼服清洁中，不可预约")

# ---------------------------------------------------------------------------
# 搭配配件
# ---------------------------------------------------------------------------
def create_accessory_set(code: str, name: str, items: list[dict], note: str = "") -> dict:
    """items: [{code, name}, ...] 按编号绑定。"""
    with _lock:
        conn = get_db()
        try:
            if conn.execute("SELECT 1 FROM accessory_sets WHERE code=?", (code,)).fetchone():
                raise ServiceError(f"配件套装编号 {code} 已存在")
            cur = conn.execute(
                "INSERT INTO accessory_sets (code, name, note, created_at) VALUES (?,?,?,?)",
                (code, name, note, now_iso()),
            )
            set_id = cur.lastrowid
            seen = set()
            for it in items:
                ic = it["code"].strip()
                if ic in seen:
                    raise ServiceError(f"配件编号重复：{ic}")
                seen.add(ic)
                conn.execute(
                    "INSERT INTO accessory_items (set_id, code, name) VALUES (?,?,?)",
                    (set_id, ic, it["name"].strip()),
                )
            conn.commit()
            return get_accessory_set(set_id)
        finally:
            conn.close()

def get_accessory_set(set_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        s = conn.execute("SELECT * FROM accessory_sets WHERE id=?", (set_id,)).fetchone()
        if not s:
            return None
        items = conn.execute("SELECT * FROM accessory_items WHERE set_id=? ORDER BY id", (set_id,)).fetchall()
        d = dict(s)
        d["items"] = [dict(i) for i in items]
        return d
    finally:
        conn.close()

def list_accessory_sets() -> list[dict]:
    conn = get_db()
    try:
        sets = [dict(r) for r in conn.execute("SELECT * FROM accessory_sets ORDER BY id").fetchall()]
        for s in sets:
            items = conn.execute("SELECT * FROM accessory_items WHERE set_id=? ORDER BY id", (s["id"],)).fetchall()
            s["items"] = [dict(i) for i in items]
        return sets
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# 试穿预约
# ---------------------------------------------------------------------------
def create_appointment(gown_id: int, customer_id: int, start_time: str, end_time: str,
                       note: str = "") -> dict:
    """预约锁定具体礼服和试穿时段。同一礼服同一时段不可重复预约。"""
    with _lock:
        conn = get_db()
        try:
            gown = conn.execute("SELECT * FROM gowns WHERE id=?", (gown_id,)).fetchone()
            if not gown:
                raise ServiceError("礼服不存在", 404)
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
            if not customer:
                raise ServiceError("客户不存在", 404)
            _ensure_bookable(conn, dict(gown))
            if start_time >= end_time:
                raise ServiceError("预约时段无效")
            # 时段竞争：同一礼服存在时段重叠的有效预约即拒绝；不重叠的不同时段可各自锁定
            overlap = conn.execute(
                """SELECT code FROM appointments
                   WHERE gown_id=? AND status IN ('booked','checked_in')
                     AND start_time < ? AND end_time > ?""",
                (gown_id, end_time, start_time),
            ).fetchone()
            if overlap:
                raise ServiceError(f"该礼服此时段已被预约（{overlap['code']}），同一礼服不能同时存在两个有效预约")
            code = gen_code("APT")
            conn.execute(
                """INSERT INTO appointments (code, gown_id, customer_id, start_time, end_time, status, note, created_at)
                   VALUES (?,?,?,?,?, 'booked', ?, ?)""",
                (code, gown_id, customer_id, start_time, end_time, note, now_iso()),
            )
            conn.execute("UPDATE gowns SET status='reserved' WHERE id=?", (gown_id,))
            conn.commit()
            return get_appointment(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        finally:
            conn.close()

def get_appointment(appt_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute(
            """SELECT a.*, g.code AS gown_code, g.name AS gown_name, g.photo AS gown_photo,
                      g.size AS gown_size, c.name AS customer_name, c.avatar AS customer_avatar
               FROM appointments a
               JOIN gowns g ON g.id=a.gown_id
               JOIN customers c ON c.id=a.customer_id
               WHERE a.id=?""",
            (appt_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def list_appointments(date_from: Optional[str] = None, date_to: Optional[str] = None,
                      gown_id: Optional[int] = None, customer_id: Optional[int] = None,
                      status: Optional[str] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """SELECT a.*, g.code AS gown_code, g.name AS gown_name, g.photo AS gown_photo,
                        g.size AS gown_size, c.name AS customer_name, c.avatar AS customer_avatar
                 FROM appointments a
                 JOIN gowns g ON g.id=a.gown_id
                 JOIN customers c ON c.id=a.customer_id
                 WHERE 1=1"""
        args: list = []
        if date_from:
            sql += " AND a.end_time >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND a.start_time <= ?"
            args.append(date_to)
        if gown_id:
            sql += " AND a.gown_id=?"
            args.append(gown_id)
        if customer_id:
            sql += " AND a.customer_id=?"
            args.append(customer_id)
        if status:
            sql += " AND a.status=?"
            args.append(status)
        sql += " ORDER BY a.start_time"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()

def cancel_appointment(appt_id: int, late: bool = False) -> dict:
    """取消预约。迟到取消（超过预约开始时间）标记 late_cancelled。"""
    with _lock:
        conn = get_db()
        try:
            a = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
            if not a:
                raise ServiceError("预约不存在", 404)
            if a["status"] not in ("booked", "checked_in"):
                raise ServiceError(f"预约状态为 {a['status']}，不可取消")
            new_status = "late_cancelled" if late else "cancelled"
            conn.execute("UPDATE appointments SET status=? WHERE id=?", (new_status, appt_id))
            # 释放礼服（若无其他有效预约/出店单）
            other = conn.execute(
                """SELECT 1 FROM appointments WHERE gown_id=? AND status IN ('booked','checked_in') AND id!=?
                   UNION ALL
                   SELECT 1 FROM out_orders WHERE gown_id=? AND status='out' LIMIT 1""",
                (a["gown_id"], appt_id, a["gown_id"]),
            ).fetchone()
            if not other:
                conn.execute("UPDATE gowns SET status='available' WHERE id=?", (a["gown_id"],))
            conn.commit()
            return get_appointment(appt_id)
        finally:
            conn.close()

def checkin_appointment(appt_id: int) -> dict:
    with _lock:
        conn = get_db()
        try:
            a = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
            if not a:
                raise ServiceError("预约不存在", 404)
            if a["status"] != "booked":
                raise ServiceError(f"预约状态为 {a['status']}，不可签到")
            conn.execute("UPDATE appointments SET status='checked_in' WHERE id=?", (appt_id,))
            conn.commit()
            return get_appointment(appt_id)
        finally:
            conn.close()

def swap_appointment_gown(appt_id: int, new_gown_id: int) -> dict:
    """临时换款：将预约的礼服换成另一件可约礼服。"""
    with _lock:
        conn = get_db()
        try:
            a = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
            if not a:
                raise ServiceError("预约不存在", 404)
            if a["status"] not in ("booked", "checked_in"):
                raise ServiceError(f"预约状态为 {a['status']}，不可换款")
            if new_gown_id == a["gown_id"]:
                raise ServiceError("新礼服与原礼服相同")
            new_gown = conn.execute("SELECT * FROM gowns WHERE id=?", (new_gown_id,)).fetchone()
            if not new_gown:
                raise ServiceError("新礼服不存在", 404)
            _ensure_bookable(conn, dict(new_gown))
            overlap = conn.execute(
                """SELECT code FROM appointments
                   WHERE gown_id=? AND status IN ('booked','checked_in') AND id!=?
                     AND start_time < ? AND end_time > ?""",
                (new_gown_id, appt_id, a["end_time"], a["start_time"]),
            ).fetchone()
            if overlap:
                raise ServiceError(f"该礼服此时段已被预约（{overlap['code']}），同一礼服不能同时存在两个有效预约")
            # 释放旧礼服
            old_gown_id = a["gown_id"]
            conn.execute(
                "UPDATE appointments SET gown_id=?, swap_from_gown_id=?, status='swapped' WHERE id=?",
                (new_gown_id, old_gown_id, appt_id),
            )
            # 旧礼服若无其他占用则释放
            other = conn.execute(
                """SELECT 1 FROM appointments WHERE gown_id=? AND status IN ('booked','checked_in') AND id!=?
                   UNION ALL
                   SELECT 1 FROM out_orders WHERE gown_id=? AND status='out' LIMIT 1""",
                (old_gown_id, appt_id, old_gown_id),
            ).fetchone()
            if not other:
                conn.execute("UPDATE gowns SET status='available' WHERE id=?", (old_gown_id,))
            conn.execute("UPDATE gowns SET status='reserved' WHERE id=?", (new_gown_id,))
            conn.commit()
            return get_appointment(appt_id)
        finally:
            conn.close()

# ---------------------------------------------------------------------------
# 出店单
# ---------------------------------------------------------------------------
def create_out_order(gown_id: int, customer_id: int, accessory_set_id: Optional[int] = None,
                     appointment_id: Optional[int] = None, size_adjustments: str = "",
                     pre_stains: str = "", out_photos: Optional[list[dict]] = None,
                     expected_return_time: str = "", note: str = "") -> dict:
    """出店前记录尺寸调整、污渍和细节照片。礼服与配件套装同时锁定。"""
    with _lock:
        conn = get_db()
        try:
            gown = conn.execute("SELECT * FROM gowns WHERE id=?", (gown_id,)).fetchone()
            if not gown:
                raise ServiceError("礼服不存在", 404)
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
            if not customer:
                raise ServiceError("客户不存在", 404)
            if gown["status"] == "out":
                raise ServiceError("该礼服已出店，不能重复出店")
            if gown["cleaning_status"] != "clean":
                raise ServiceError("礼服未清洁完成，不能出店")
            conflict = _active_conflict(conn, gown_id, exclude_appt=appointment_id)
            if conflict:
                raise ServiceError(conflict)
            # 配件套装：存在且未被其他有效出店单占用
            if accessory_set_id:
                s = conn.execute("SELECT * FROM accessory_sets WHERE id=?", (accessory_set_id,)).fetchone()
                if not s:
                    raise ServiceError("配件套装不存在", 404)
                used = conn.execute(
                    "SELECT code FROM out_orders WHERE accessory_set_id=? AND status='out' LIMIT 1",
                    (accessory_set_id,),
                ).fetchone()
                if used:
                    raise ServiceError(f"该配件套装已随出店单 {used['code']} 出店")
            if appointment_id:
                a = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
                if not a:
                    raise ServiceError("预约不存在", 404)
                if a["gown_id"] != gown_id:
                    raise ServiceError("预约礼服与出店礼服不一致")
                if a["customer_id"] != customer_id:
                    raise ServiceError("预约客户与出店客户不一致")
            code = gen_code("OUT")
            cur = conn.execute(
                """INSERT INTO out_orders
                   (code, gown_id, customer_id, appointment_id, accessory_set_id, status,
                    deposit_amount, deposit_status, size_adjustments, pre_stains, out_photos,
                    out_time, expected_return_time, created_at)
                   VALUES (?,?,?,?,?, 'out', ?, 'paid', ?, ?, ?, ?, ?, ?)""",
                (code, gown_id, customer_id, appointment_id, accessory_set_id,
                 gown["deposit_amount"], size_adjustments, pre_stains,
                 json.dumps(out_photos or [], ensure_ascii=False),
                 now_iso(), expected_return_time, now_iso()),
            )
            order_id = cur.lastrowid
            conn.execute("UPDATE gowns SET status='out' WHERE id=?", (gown_id,))
            if appointment_id:
                conn.execute("UPDATE appointments SET status='completed' WHERE id=?", (appointment_id,))
            # 押金记录
            dcode = gen_code("DEP")
            conn.execute(
                """INSERT INTO deposits (code, out_order_id, amount, status, idempotency_key, deduction_total, refund_amount, created_at)
                   VALUES (?,?,?, 'paid', ?, 0, 0, ?)""",
                (dcode, order_id, gown["deposit_amount"], f"deposit:{order_id}", now_iso()),
            )
            conn.commit()
            return get_out_order(order_id)
        finally:
            conn.close()

def get_out_order(order_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute(
            """SELECT o.*, g.code AS gown_code, g.name AS gown_name, g.photo AS gown_photo,
                      g.size AS gown_size, c.name AS customer_name, c.avatar AS customer_avatar,
                      s.code AS set_code, s.name AS set_name
               FROM out_orders o
               JOIN gowns g ON g.id=o.gown_id
               JOIN customers c ON c.id=o.customer_id
               LEFT JOIN accessory_sets s ON s.id=o.accessory_set_id
               WHERE o.id=?""",
            (order_id,),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["out_photos"] = json.loads(d["out_photos"] or "[]")
        items = conn.execute(
            "SELECT * FROM accessory_items WHERE set_id=? ORDER BY id", (d["accessory_set_id"],)
        ).fetchall() if d["accessory_set_id"] else []
        d["accessory_items"] = [dict(i) for i in items]
        return d
    finally:
        conn.close()

def list_out_orders(status: Optional[str] = None, customer_id: Optional[int] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """SELECT o.*, g.code AS gown_code, g.name AS gown_name, g.photo AS gown_photo,
                        g.size AS gown_size, c.name AS customer_name, s.code AS set_code, s.name AS set_name
                 FROM out_orders o
                 JOIN gowns g ON g.id=o.gown_id
                 JOIN customers c ON c.id=o.customer_id
                 LEFT JOIN accessory_sets s ON s.id=o.accessory_set_id
                 WHERE 1=1"""
        args: list = []
        if status:
            sql += " AND o.status=?"
            args.append(status)
        if customer_id:
            sql += " AND o.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY o.id DESC"
        out = []
        for r in conn.execute(sql, args).fetchall():
            d = dict(r)
            d["out_photos"] = json.loads(d["out_photos"] or "[]")
            out.append(d)
        return out
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# 返店检查
# ---------------------------------------------------------------------------
def _build_checklist(order: dict) -> list[dict]:
    """根据礼服基线 + 配件清单构建返店检查项。"""
    items = [dict(x) for x in GOWN_CHECKLIST]
    for acc in order.get("accessory_items", []):
        items.append({
            "key": f"acc_{acc['code']}",
            "label": f"配件 {acc['code']} {acc['name']}",
            "kind": "accessory",
            "ref_id": acc["id"],
            "ref_code": acc["code"],
        })
    return items

def create_return_inspection(order_id: int) -> dict:
    """创建返店检查单（草稿），逐项打勾。"""
    with _lock:
        conn = get_db()
        try:
            order = conn.execute("SELECT * FROM out_orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                raise ServiceError("出店单不存在", 404)
            if order["status"] != "out":
                raise ServiceError(f"出店单状态为 {order['status']}，不可返店检查")
            existing = conn.execute("SELECT 1 FROM inspections WHERE out_order_id=?", (order_id,)).fetchone()
            if existing:
                raise ServiceError("该出店单已有返店检查")
            order_d = get_out_order(order_id)
            checklist = _build_checklist(order_d)
            code = gen_code("INS")
            conn.execute(
                """INSERT INTO inspections (code, out_order_id, status, items, deductions, paired_photos, review, created_at)
                   VALUES (?,?, 'draft', ?, '[]', '[]', '', ?)""",
                (code, order_id, json.dumps(checklist, ensure_ascii=False), now_iso()),
            )
            conn.commit()
            return get_inspection(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        finally:
            conn.close()

def get_inspection(inspection_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute(
            """SELECT i.*, o.code AS order_code, o.gown_id, o.customer_id, o.out_photos AS order_out_photos,
                      o.size_adjustments AS size_adjustments, o.pre_stains AS pre_stains,
                      o.expected_return_time AS expected_return_time, o.out_time AS out_time,
                      g.code AS gown_code, g.name AS gown_name, g.photo AS gown_photo, g.size AS gown_size,
                      c.name AS customer_name
               FROM inspections i
               JOIN out_orders o ON o.id=i.out_order_id
               JOIN gowns g ON g.id=o.gown_id
               JOIN customers c ON c.id=o.customer_id
               WHERE i.id=?""",
            (inspection_id,),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["items"] = json.loads(d["items"] or "[]")
        d["deductions"] = json.loads(d["deductions"] or "[]")
        d["paired_photos"] = json.loads(d["paired_photos"] or "[]")
        d["order_out_photos"] = json.loads(d["order_out_photos"] or "[]")
        return d
    finally:
        conn.close()

def list_inspections(customer_id: Optional[int] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """SELECT i.*, o.code AS order_code, o.gown_id, o.customer_id,
                        g.code AS gown_code, g.name AS gown_name, c.name AS customer_name
                 FROM inspections i
                 JOIN out_orders o ON o.id=i.out_order_id
                 JOIN gowns g ON g.id=o.gown_id
                 JOIN customers c ON c.id=o.customer_id
                 WHERE 1=1"""
        args: list = []
        if customer_id:
            sql += " AND o.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY i.id DESC"
        out = []
        for r in conn.execute(sql, args).fetchall():
            d = dict(r)
            d["items"] = json.loads(d["items"] or "[]")
            d["deductions"] = json.loads(d["deductions"] or "[]")
            out.append(d)
        return out
    finally:
        conn.close()

def update_inspection_items(inspection_id: int, items: list[dict], photos: Optional[list[dict]] = None) -> dict:
    """提交返店检查结果（逐项打勾）。每项: {key, result: ok/missing/damaged/stain, note}。
    photos: [{slot, data_url}] 异常照片，与出店照片按 slot 配对。"""
    with _lock:
        conn = get_db()
        try:
            insp = conn.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
            if not insp:
                raise ServiceError("返店检查单不存在", 404)
            if insp["status"] != "draft":
                raise ServiceError("返店结果已确认，不能修改检查项（只能追加复核）")
            existing = json.loads(insp["items"] or "[]")
            by_key = {it["key"]: it for it in existing}
            for sub in items:
                k = sub.get("key")
                if k not in by_key:
                    raise ServiceError(f"检查项 {k} 不存在")
                result = sub.get("result", "ok")
                if result not in ("ok", "missing", "damaged", "stain"):
                    raise ServiceError(f"检查项结果无效：{result}")
                by_key[k]["result"] = result
                by_key[k]["note"] = sub.get("note", "")
            # 异常照片存档（草稿可多次提交，返店照片累积保留）
            saved = []
            for p in photos or []:
                saved.append(save_photo(p["data_url"], p.get("slot", "return")))
            # 照片配对：按 slot 关联出店照片与返店照片；保留此前已存的返店照片
            order = conn.execute("SELECT * FROM out_orders WHERE id=?", (insp["out_order_id"],)).fetchone()
            out_photos = json.loads(order["out_photos"] or "[]")
            prev_pairs = json.loads(insp["paired_photos"] or "[]")
            prev_return = [p["return"] for p in prev_pairs if p.get("return")]
            paired = _pair_photos(out_photos, prev_return + saved)
            conn.execute(
                "UPDATE inspections SET items=?, paired_photos=? WHERE id=?",
                (json.dumps(existing, ensure_ascii=False), json.dumps(paired, ensure_ascii=False), inspection_id),
            )
            conn.commit()
            return get_inspection(inspection_id)
        finally:
            conn.close()

def _pair_photos(out_photos: list[dict], return_photos: list[dict]) -> list[dict]:
    """按 slot 配对出店/返店照片。同 slot 视为同一检查点的前后对比。

    返回 [{slot, out: photo|None, returns: [photo...]}]。
    """
    pairs: dict[str, dict] = {}
    for p in out_photos:
        slot = p.get("slot", "out")
        pairs.setdefault(slot, {"slot": slot, "out": None, "returns": []})["out"] = p
    for p in return_photos:
        slot = p.get("slot", "return")
        pairs.setdefault(slot, {"slot": slot, "out": None, "returns": []})["returns"].append(p)
    return list(pairs.values())

def add_inspection_deduction(inspection_id: int, item_key: str, amount_yuan: float,
                             reason: str, photos: Optional[list[dict]] = None) -> dict:
    """为异常检查项添加押金扣款。扣款关联检查项和照片。"""
    with _lock:
        conn = get_db()
        try:
            insp = conn.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
            if not insp:
                raise ServiceError("返店检查单不存在", 404)
            if insp["status"] != "draft":
                raise ServiceError("返店结果已确认，不能新增扣款（只能追加复核）")
            items = json.loads(insp["items"] or "[]")
            target = next((it for it in items if it["key"] == item_key), None)
            if not target:
                raise ServiceError(f"检查项 {item_key} 不存在，扣款必须关联检查项")
            if target.get("result", "ok") == "ok":
                raise ServiceError(f"检查项 {item_key} 结果为正常，不能对正常项扣款")
            if not photos:
                raise ServiceError("押金扣款必须上传关联照片作为凭证")
            amount = yuan_to_cents(amount_yuan)
            if amount <= 0:
                raise ServiceError("扣款金额必须大于 0")
            saved = []
            for p in photos or []:
                saved.append(save_photo(p["data_url"], p.get("slot", f"ded_{item_key}")))
            deductions = json.loads(insp["deductions"] or "[]")
            deductions.append({
                "item_key": item_key,
                "amount": amount,
                "reason": reason,
                "photos": saved,
                "created_at": now_iso(),
            })
            conn.execute("UPDATE inspections SET deductions=? WHERE id=?",
                         (json.dumps(deductions, ensure_ascii=False), inspection_id))
            conn.commit()
            return get_inspection(inspection_id)
        finally:
            conn.close()

def confirm_inspection(inspection_id: int) -> dict:
    """确认返店结果：结算押金（多退少补，幂等），礼服进入清洁流程。

    已确认的返店结果只能追加复核，不可修改。
    """
    with _lock:
        conn = get_db()
        try:
            insp = conn.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
            if not insp:
                raise ServiceError("返店检查单不存在", 404)
            if insp["status"] != "draft":
                raise ServiceError("返店结果已确认，不能重复确认")
            order = conn.execute("SELECT * FROM out_orders WHERE id=?", (insp["out_order_id"],)).fetchone()
            deductions = json.loads(insp["deductions"] or "[]")
            items = json.loads(insp["items"] or "[]")
            # 配件缺失/破损必须有对应检查项结果
            for d in deductions:
                it = next((x for x in items if x["key"] == d["item_key"]), None)
                if not it:
                    raise ServiceError(f"扣款 {d['item_key']} 未关联检查项")
            total_ded = sum(d["amount"] for d in deductions)
            deposit = conn.execute("SELECT * FROM deposits WHERE out_order_id=?", (order["id"],)).fetchone()
            if not deposit:
                raise ServiceError("押金记录不存在", 404)
            # 结算（幂等）：退款 = 押金 - 扣款
            refund = max(0, deposit["amount"] - total_ded)
            settle = SETTLEMENT.settle(
                deposit["idempotency_key"],
                refund,
                f"返店结算 {order['code']}：扣款 {total_ded} 分，退款 {refund} 分",
            )
            new_dep_status = "deducted" if total_ded > 0 else "refunded"
            conn.execute(
                """UPDATE deposits SET status=?, deduction_total=?, refund_amount=?, settle_result=?, settled_at=?
                   WHERE id=?""",
                (new_dep_status, total_ded, refund, json.dumps(settle, ensure_ascii=False), now_iso(), deposit["id"]),
            )
            conn.execute(
                "UPDATE inspections SET status='confirmed', confirmed_at=? WHERE id=?",
                (now_iso(), inspection_id),
            )
            conn.execute("UPDATE out_orders SET status='returned' WHERE id=?", (order["id"],))
            # 礼服进入清洁流程
            conn.execute(
                "UPDATE gowns SET status='cleaning', cleaning_status='pending' WHERE id=?",
                (order["gown_id"],),
            )
            conn.execute(
                """INSERT INTO cleaning_records (gown_id, out_order_id, status, note, created_at, updated_at)
                   VALUES (?,?, 'pending', '返店后待清洁', ?, ?)""",
                (order["gown_id"], order["id"], now_iso(), now_iso()),
            )
            conn.commit()
            return get_inspection(inspection_id)
        finally:
            conn.close()

def add_inspection_review(inspection_id: int, review: str) -> dict:
    """已确认返店结果追加复核。"""
    with _lock:
        conn = get_db()
        try:
            insp = conn.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
            if not insp:
                raise ServiceError("返店检查单不存在", 404)
            if insp["status"] != "confirmed":
                raise ServiceError("返店结果未确认，不能追加复核")
            if not review.strip():
                raise ServiceError("复核内容不能为空")
            old = insp["review"] or ""
            new_review = (old + "\n" if old else "") + f"[{now_iso()}] {review.strip()}"
            conn.execute("UPDATE inspections SET review=? WHERE id=?", (new_review, inspection_id))
            conn.commit()
            return get_inspection(inspection_id)
        finally:
            conn.close()

# ---------------------------------------------------------------------------
# 清洁
# ---------------------------------------------------------------------------
def list_cleaning_records(gown_id: Optional[int] = None, status: Optional[str] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """SELECT cr.*, g.code AS gown_code, g.name AS gown_name
                 FROM cleaning_records cr JOIN gowns g ON g.id=cr.gown_id WHERE 1=1"""
        args: list = []
        if gown_id:
            sql += " AND cr.gown_id=?"
            args.append(gown_id)
        if status:
            sql += " AND cr.status=?"
            args.append(status)
        sql += " ORDER BY cr.id DESC"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()

def update_cleaning(record_id: int, status: str, note: str = "") -> dict:
    """清洁完成/不合格。不合格需重新清洁，且礼服不能再次预约。"""
    if status not in ("passed", "failed"):
        raise ServiceError("清洁状态无效")
    with _lock:
        conn = get_db()
        try:
            rec = conn.execute("SELECT * FROM cleaning_records WHERE id=?", (record_id,)).fetchone()
            if not rec:
                raise ServiceError("清洁记录不存在", 404)
            if rec["status"] != "pending":
                raise ServiceError("该清洁记录已处理")
            conn.execute("UPDATE cleaning_records SET status=?, note=?, updated_at=? WHERE id=?",
                         (status, note, now_iso(), record_id))
            if status == "passed":
                conn.execute(
                    "UPDATE gowns SET status='available', cleaning_status='clean' WHERE id=?",
                    (rec["gown_id"],),
                )
            else:
                # 清洁不合格：礼服留在清洁流程，须重新清洁，期间不可预约
                conn.execute(
                    "UPDATE gowns SET status='cleaning', cleaning_status='failed' WHERE id=?",
                    (rec["gown_id"],),
                )
                # 不合格则新建一条待清洁记录
                conn.execute(
                    """INSERT INTO cleaning_records (gown_id, out_order_id, status, note, created_at, updated_at)
                       VALUES (?, ?, 'pending', '清洁不合格，重新清洁', ?, ?)""",
                    (rec["gown_id"], rec["out_order_id"], now_iso(), now_iso()),
                )
            conn.commit()
            return dict(conn.execute("SELECT * FROM cleaning_records WHERE id=?", (record_id,)).fetchone())
        finally:
            conn.close()

# ---------------------------------------------------------------------------
# 押金
# ---------------------------------------------------------------------------
def list_deposits(customer_id: Optional[int] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """SELECT d.*, o.code AS order_code, o.customer_id, c.name AS customer_name,
                        g.code AS gown_code, g.name AS gown_name
                 FROM deposits d
                 JOIN out_orders o ON o.id=d.out_order_id
                 JOIN customers c ON c.id=o.customer_id
                 JOIN gowns g ON g.id=o.gown_id
                 WHERE 1=1"""
        args: list = []
        if customer_id:
            sql += " AND o.customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY d.id DESC"
        out = []
        for r in conn.execute(sql, args).fetchall():
            d = dict(r)
            d["settle_result"] = json.loads(d["settle_result"] or "null")
            out.append(d)
        return out
    finally:
        conn.close()

def get_deposit(deposit_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        r = conn.execute(
            """SELECT d.*, o.code AS order_code, o.customer_id, c.name AS customer_name
               FROM deposits d JOIN out_orders o ON o.id=d.out_order_id
               JOIN customers c ON c.id=o.customer_id WHERE d.id=?""",
            (deposit_id,),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["settle_result"] = json.loads(d["settle_result"] or "null")
        return d
    finally:
        conn.close()
