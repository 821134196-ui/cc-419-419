# -*- coding: utf-8 -*-
"""一条命令生成完整业务样例：

  python3 -m app.demo [--reset]

样例脉络（均为演示数据）：
  林晚 C001：今日试穿 BW-001+AC-01 → 出店（尺寸调整+出店细节照）
        → 超时 80 分钟返店：酒渍/勾丝/皇冠缺失 → 清洁首轮不合格、复检合格
        → 押金四项扣款后退还余额；清洁合格后重新预约下周档期
  苏绮 C002：昨日 BW-002 迟到 35 分钟取消；今日预约 BW-003 临时换款 BW-004
  周棠 C003：今日 BW-003+AC-02 出店中，返店检查进行到一半（WIP）；
        后天另有 BW-002 预约
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import photos as P
from .config import DB_PATH, PHOTO_DIR
from .db import connect
from .seed import seed
from .services import BridalService, Conflict

YEN = 100


def _photo(order_code: str, name: str, label: str, note: str,
           mark: str = "") -> str:
    p = P.write_svg(
        PHOTO_DIR / "orders" / order_code / name,
        P.detail_svg(label, note, mark))
    return Path(p).relative_to(PHOTO_DIR).as_posix()


def _return_photo_id(svc: BridalService, item_id: int) -> int:
    return svc.conn.execute(
        "SELECT id FROM photos WHERE item_id=? AND phase='return'"
        " ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()["id"]


def _item_id(svc: BridalService, order_id: int, label: str) -> int:
    return svc.conn.execute(
        "SELECT id FROM inspection_items WHERE order_id=? AND label=?",
        (order_id, label)).fetchone()["id"]


def build(reset: bool = False) -> None:
    seed(reset=reset)
    conn = connect(DB_PATH)
    if conn.execute("SELECT COUNT(*) c FROM outgoing_orders").fetchone()["c"]:
        conn.close()
        print("demo: 样例已存在，跳过（--reset 可重建）")
        return
    svc = BridalService(conn)
    today = datetime.now().date()
    d0 = today.isoformat()
    d_1 = (today - timedelta(days=1)).isoformat()
    d1 = (today + timedelta(days=1)).isoformat()
    d2 = (today + timedelta(days=2)).isoformat()
    d7 = (today + timedelta(days=7)).isoformat()

    try:
        # ============ 苏绮：迟到取消 ============
        a_late = svc.create_appointment(
            2, 2, "M", d_1, "14:00", "15:00",
            code="APT-LATE-01")
        svc.mark_arrived(a_late["id"], 2)
        svc.late_cancel(a_late["id"], 2, 35, "路上堵车，超过等候时限")
        print("demo: 迟到取消 APT-LATE-01（BW-002，迟到 35 分钟）")

        # ============ 苏绮：临时换款 BW-003 -> BW-004 ============
        a_swap = svc.create_appointment(
            2, 3, "S", d1, "10:00", "11:00",
            code="APT-SWAP-01")
        svc.swap_appointment(a_swap["id"], 2, to_gown_id=5,
                             to_size="M", to_accessory_set_id=3,
                             reason="到店后更喜欢珍珠款")
        print("demo: 临时换款 APT-SWAP-01（BW-003 → BW-004 + AC-03）")

        # ============ 周棠：后天 BW-002 预约（日历展示） ============
        svc.create_appointment(3, 2, "S", d2, "15:00", "16:00",
                               code="APT-FUTURE-01")

        # ============ 林晚：完整出店/返店/扣款链路 ============
        a1 = svc.create_appointment(
            1, 1, "M", d0, "10:00", "11:30", accessory_set_id=1,
            code="APT-MAIN-01")
        svc.mark_arrived(a1["id"], 1)
        order_code = "OUT-MAIN-01"
        out_photos_dir = PHOTO_DIR / "orders" / order_code
        items = [
            {"label": "裙摆正中央", "category": "stain",
             "outgoing_note": "出店检查无可见污渍"},
            {"label": "胸口钉珠", "category": "detail",
             "outgoing_note": "珠饰 48 颗完整"},
            {"label": "后背拉链", "category": "detail",
             "outgoing_note": "开合顺畅，无卡齿"},
            {"label": "拖尾内衬", "category": "detail",
             "outgoing_note": "无勾丝、无起球"},
        ]
        outgoing_photos = {
            1: {"path": _photo(order_code, "out-hem.svg",
                               "裙摆正中央 · 出店", "无污渍"),
                "category": "stain"},
            2: {"path": _photo(order_code, "out-beads.svg",
                               "胸口钉珠 · 出店", "48 颗完整"),
                "category": "detail"},
            4: {"path": _photo(order_code, "out-lining.svg",
                               "拖尾内衬 · 出店", "无勾丝"),
                "category": "detail"},
        }
        adjust_photo = _photo(order_code, "out-adjust.svg",
                              "尺寸调整 · 腰围收 2cm", "别针定位后修改")
        order = svc.create_outgoing_order(
            1, a1["id"], gown_id=1, accessory_set_id=1,
            size_adjust={"waist": "腰围收 2cm", "hem": "前摆改短 1cm",
                         "photo": adjust_photo},
            planned_return=f"{d1} 18:00",
            items=items, outgoing_photos=outgoing_photos,
            code=order_code)
        oid = order["id"]
        print(f"demo: 出店单 {order_code}（BW-001 + AC-01，押金 3000 元）")

        # 超时 80 分钟返店
        svc.start_return(oid, 1, f"{d1} 19:20")

        def check(label, result, note, mark, fname):
            iid = _item_id(svc, oid, label)
            path = _photo(order_code, fname, f"{label} · 返店", note, mark)
            svc.set_item_result(oid, 1, iid, result, note, photo_path=path)
            return iid

        i_hem = check("裙摆正中央", "stained", "玫瑰红酒渍约 3cm",
                      "酒渍 3cm", "ret-hem.svg")
        i_beads = _item_id(svc, oid, "胸口钉珠")
        svc.set_item_result(oid, 1, i_beads, "ok", "钉珠无缺失")
        i_zip = _item_id(svc, oid, "后背拉链")
        svc.set_item_result(oid, 1, i_zip, "ok", "拉链正常")
        i_lining = check("拖尾内衬", "damaged", "鞋跟勾丝约 5cm",
                         "勾丝 5cm", "ret-lining.svg")
        i_veil = _item_id(svc, oid, "配件 · V-01 长款拖地头纱")
        svc.set_item_result(oid, 1, i_veil, "ok", "头纱无勾纱")
        i_crown = check("配件 · C-01 水晶皇冠", "missing",
                        "返店箱内未见皇冠", "缺失", "ret-crown.svg")
        i_ear = _item_id(svc, oid, "配件 · E-01 珍珠耳饰")
        svc.set_item_result(oid, 1, i_ear, "ok", "耳饰成对归还")
        i_late = check(svc.LATE_ITEM_LABEL, "late",
                       "实际 19:20 返店，超时 80 分钟", "超时 80 分钟",
                       "ret-late.svg")
        svc.confirm_return(oid, 1)
        print("demo: 返店确认：酒渍/勾丝/皇冠缺失/超时，AC-01 标记缺件")

        # 清洁：首轮不合格 -> 复检合格
        svc.cleaning_qc(oid, "failed", "酒渍处理后仍有浅色印子，返工复洗",
                        photo_path=_photo(order_code, "clean-fail.svg",
                                          "清洁质检 · 不合格",
                                          "残留浅印", "残留"))
        svc.cleaning_qc(oid, "passed", "复洗后污渍去除，蒸汽定型完成",
                        photo_path=_photo(order_code, "clean-pass.svg",
                                          "清洁质检 · 合格", "可再上架"))
        print("demo: 清洁首轮不合格，复检合格后 BW-001 释放")

        # 押金扣款（逐项关联检查项与返店照片）
        deductions = [
            (i_hem, 300 * YEN, "裙摆玫瑰红酒渍清洗费"),
            (i_lining, 400 * YEN, "内衬勾丝织补费"),
            (i_crown, 500 * YEN, "水晶皇冠遗失赔偿"),
            (i_late, 100 * YEN, "超时返店 80 分钟占用费"),
        ]
        for iid, amt, reason in deductions:
            svc.deduct_deposit(oid, 1, iid, _return_photo_id(svc, iid),
                               amt, reason)
        dep = svc.settle_deposit(oid, 1)
        print(f"demo: 押金扣款合计 1300 元，退还 {dep['refunded']/YEN:.0f} 元")

        # 追加复核（已确认结果不可改，只追加）
        svc.add_review(oid, 1, "店长复核：污渍与勾丝照片与出店照配对无误，"
                               "皇冠按采购价 500 元核定，扣款成立。")

        # 清洁合格后重新预约
        svc.create_appointment(1, 1, "M", d7, "14:00", "15:00",
                               code="APT-REBOOK-01")
        print("demo: BW-001 清洁合格后已被重新预约（APT-REBOOK-01）")

        # 清洁期间不可预约的演示（BW-001 已释放，改用静态校验难构造，
        # 此处仅说明规则，由测试覆盖）

        # ============ 周棠：出店中、返店检查进行到一半（WIP） ============
        a2 = svc.create_appointment(
            3, 3, "S", d0, "15:00", "16:00", accessory_set_id=2,
            code="APT-WIP-01")
        svc.mark_arrived(a2["id"], 3)
        wip_code = "OUT-WIP-01"
        wip_items = [
            {"label": "鱼尾侧缝", "category": "detail",
             "outgoing_note": "无跳线"},
            {"label": "整体面料", "category": "stain",
             "outgoing_note": "出店干净"},
        ]
        wip_photos = {
            1: {"path": _photo(wip_code, "out-seam.svg",
                               "鱼尾侧缝 · 出店", "无跳线"),
                "category": "detail"},
        }
        wip = svc.create_outgoing_order(
            3, a2["id"], gown_id=3, accessory_set_id=2,
            size_adjust={"waist": "侧缝暂放 1cm", "photo": ""},
            planned_return=f"{d1} 12:00",
            items=wip_items, outgoing_photos=wip_photos,
            code=wip_code)
        svc.start_return(wip["id"], 3, f"{d1} 11:40")
        wid = wip["id"]
        w_seam = _item_id(svc, wid, "鱼尾侧缝")
        svc.set_item_result(wid, 3, w_seam, "ok", "侧缝无异常")
        print(f"demo: {wip_code} 返店检查进行中（1 项已勾，余项待检）")

        conn.close()
        print("demo: 全部样例生成完成。")
    except Conflict as e:
        conn.close()
        print(f"demo: 业务冲突，请 --reset 重建：{e}")
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    build(reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
