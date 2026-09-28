# -*- coding: utf-8 -*-
"""SQLite 持久层：建表、连接与少量行映射工具。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;

-- 客户（演示数据）
CREATE TABLE IF NOT EXISTS customers (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    phone        TEXT NOT NULL,
    demo_photo   TEXT,                  -- 本地照片相对路径（演示头像）
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 礼服档案
CREATE TABLE IF NOT EXISTS gowns (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,  -- 档案编号，如 BW-001
    name         TEXT NOT NULL,
    style        TEXT NOT NULL,         -- 款式：拖尾/A字/鱼尾/秀禾…
    color_note   TEXT NOT NULL DEFAULT '象牙白',
    deposit      INTEGER NOT NULL,      -- 押金（分）
    rental_fee   INTEGER NOT NULL,      -- 租金（分）
    cover_photo  TEXT NOT NULL,         -- 统一比例的封面照片（本地路径）
    detail_photo TEXT,                  -- 档案细节照
    -- 礼服主状态机：available 可预约 / fitting 试穿占用中 / out 已出店 /
    -- cleaning 清洁中（完成前不可再次预约）/ retired
    status       TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available','fitting','out','cleaning','retired')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 礼服尺码（一件礼服可登记多个尺码行，卡片底部展示）
CREATE TABLE IF NOT EXISTS gown_sizes (
    id           INTEGER PRIMARY KEY,
    gown_id      INTEGER NOT NULL REFERENCES gowns(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,         -- 如 S / M / L / 定制
    bust_cm      INTEGER,
    waist_cm     INTEGER,
    hip_cm       INTEGER,
    UNIQUE(gown_id, label)
);

-- 配件套装（按编号绑定，如 AC-01：头纱+皇冠+耳饰）
CREATE TABLE IF NOT EXISTS accessory_sets (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    pieces       TEXT NOT NULL,         -- JSON: [{"code":"V-01","name":"头纱"},...]
    cover_photo  TEXT,
    status       TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available','reserved','out','incomplete')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 试穿预约：锁定具体礼服 + 试穿时段
CREATE TABLE IF NOT EXISTS appointments (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,   -- APT-####
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    gown_id         INTEGER NOT NULL REFERENCES gowns(id),
    size_label      TEXT NOT NULL,
    accessory_set_id INTEGER REFERENCES accessory_sets(id),  -- 搭配的套装（可换款时变更）
    slot_date       TEXT NOT NULL,          -- YYYY-MM-DD
    slot_start      TEXT NOT NULL,          -- HH:MM
    slot_end        TEXT NOT NULL,
    -- booked 已预约 / arrived 已到店 / late_cancelled 迟到取消 /
    -- swapped 临时换款（原预约关闭）/ completed 试穿完成 / no_show
    status          TEXT NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked','arrived','late_cancelled',
                          'swapped','completed','no_show')),
    late_minutes    INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_appt_gown_slot
    ON appointments(gown_id, slot_date, slot_start);
CREATE INDEX IF NOT EXISTS idx_appt_customer ON appointments(customer_id);

-- 预约变更（换款留痕：从哪件换到哪件、迟到取消原因）
CREATE TABLE IF NOT EXISTS appointment_changes (
    id              INTEGER PRIMARY KEY,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,          -- swap / late_cancel / no_show
    from_gown_id    INTEGER REFERENCES gowns(id),
    to_gown_id      INTEGER REFERENCES gowns(id),
    reason          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 出店单：一次出店 = 礼服 + 配件套装 + 尺寸调整 + 出店照片
CREATE TABLE IF NOT EXISTS outgoing_orders (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,   -- OUT-####
    appointment_id  INTEGER REFERENCES appointments(id),
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    gown_id         INTEGER NOT NULL REFERENCES gowns(id),
    accessory_set_id INTEGER NOT NULL REFERENCES accessory_sets(id),
    size_adjust     TEXT,                   -- 尺寸调整记录 JSON（收腰/放摆/肩带…）
    planned_return  TEXT NOT NULL,          -- 约定返店时间
    actual_return   TEXT,                   -- 实际返店时间（超时判定）
    -- pending 待出店 / active 出店中 / returned 已返店 / cancelled
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','active','returned','cancelled')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 出店前记录（污渍/瑕疵/细节），返店时逐项核对
CREATE TABLE IF NOT EXISTS inspection_items (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES outgoing_orders(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,       -- 展示顺序
    label           TEXT NOT NULL,          -- 如「裙摆正中央」
    category        TEXT NOT NULL,          -- stain 污渍 / damage 破损 / detail 细节
    outgoing_note   TEXT,                   -- 出店时状态描述
    -- 返店勾选：pending 待检 / ok 正常 / missing 配件缺失 /
    -- damaged 破损 / stained 污渍 / late 超时（记在订单层，此项保留兼容）
    return_result   TEXT NOT NULL DEFAULT 'pending'
        CHECK (return_result IN ('pending','ok','missing','damaged','stained','late')),
    return_note     TEXT,
    checked_at      TEXT,
    UNIQUE(order_id, seq)
);

-- 照片（出店照与返店照按 inspection_item / 类别两两配对）
CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES outgoing_orders(id) ON DELETE CASCADE,
    item_id         INTEGER REFERENCES inspection_items(id) ON DELETE CASCADE,
    phase           TEXT NOT NULL CHECK (phase IN ('outgoing','return','clean')),
    category        TEXT NOT NULL,          -- stain/damage/detail/adjust/clean_qc...
    path            TEXT NOT NULL,          -- 本地目录相对路径
    note            TEXT,
    paired          INTEGER NOT NULL DEFAULT 0,  -- 是否已与对侧照片配对
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_photos_item ON photos(item_id, phase);

-- 清洁记录
CREATE TABLE IF NOT EXISTS cleanings (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES outgoing_orders(id) ON DELETE CASCADE,
    gown_id         INTEGER NOT NULL REFERENCES gowns(id),
    -- washing 清洁中 / passed 合格（释放礼服）/ failed 不合格（须返工，礼服仍锁定）
    result          TEXT NOT NULL DEFAULT 'washing'
        CHECK (result IN ('washing','passed','failed')),
    qc_note         TEXT,
    qc_photo_id     INTEGER REFERENCES photos(id),
    round_no        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 押金账户（每客户每出店单一笔）
CREATE TABLE IF NOT EXISTS deposits (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,   -- DP-####
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    order_id        INTEGER NOT NULL REFERENCES outgoing_orders(id),
    amount          INTEGER NOT NULL,        -- 收取押金（分）
    refunded        INTEGER NOT NULL DEFAULT 0,
    -- held 持有中 / settled 已结算（结果确认后只可追加复核）
    status          TEXT NOT NULL DEFAULT 'held'
        CHECK (status IN ('held','settled')),
    idem_key        TEXT NOT NULL UNIQUE,    -- 收款幂等键
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 押金扣款：必须关联检查项 + 照片
CREATE TABLE IF NOT EXISTS deposit_deductions (
    id              INTEGER PRIMARY KEY,
    deposit_id      INTEGER NOT NULL REFERENCES deposits(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES inspection_items(id),
    photo_id        INTEGER NOT NULL REFERENCES photos(id),  -- 异常照片凭据
    amount          INTEGER NOT NULL CHECK (amount > 0),
    reason          TEXT NOT NULL,
    idem_key        TEXT NOT NULL UNIQUE,    -- 扣款幂等键
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 返店结果复核（已确认结果只能追加复核，不可改原结果）
CREATE TABLE IF NOT EXISTS return_reviews (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES outgoing_orders(id) ON DELETE CASCADE,
    body            TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 进程内模拟结算适配器流水（同样落库，方便押金记录页展示）
CREATE TABLE IF NOT EXISTS payment_ledger (
    id              INTEGER PRIMARY KEY,
    idem_key        TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL,          -- deposit_charge 收押金 / refund 退款 / deduct 扣款
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    order_id        INTEGER REFERENCES outgoing_orders(id),
    amount          INTEGER NOT NULL,        -- 分；退款为负向由 kind 表达，金额恒正
    status          TEXT NOT NULL DEFAULT 'ok',
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
