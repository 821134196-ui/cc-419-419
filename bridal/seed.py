"""演示数据生成器。

单条命令生成预约、出店、返店和扣款样例（客户与照片均为演示数据，本地生成 SVG）。

用法：
    python3 seed.py            # 清空并重新生成完整演示数据
    python3 seed.py --keep     # 仅在数据库为空时生成
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import datetime, timedelta

import core

# 黑白 / 玫瑰红 / 浅灰 配色
ROSE = "#c8102e"
INK = "#111111"
GRAY = "#f2f2f2"
GRAY2 = "#d8d8d8"


def svg_data_url(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def gown_svg(code: str, name: str, variant: int = 0) -> str:
    """统一 3:4 比例的礼服占位照片。"""
    bg = ["#fafafa", "#f4f4f4", "#f7f3f4"][variant % 3]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800">
  <rect width="600" height="800" fill="{bg}"/>
  <rect x="30" y="30" width="540" height="740" fill="none" stroke="{GRAY2}" stroke-width="2" stroke-dasharray="8 8"/>
  <path d="M300 150 C250 150 235 210 250 270 C210 320 190 430 180 560 L150 700 L450 700 L420 560 C410 430 390 320 350 270 C365 210 350 150 300 150 Z"
        fill="white" stroke="{INK}" stroke-width="3"/>
  <path d="M270 170 L300 230 L330 170" fill="none" stroke="{ROSE}" stroke-width="3"/>
  <circle cx="300" cy="300" r="6" fill="{ROSE}"/>
  <circle cx="300" cy="340" r="6" fill="{ROSE}"/>
  <circle cx="300" cy="380" r="6" fill="{ROSE}"/>
  <text x="300" y="745" font-family="Georgia, serif" font-size="34" fill="{INK}" text-anchor="middle" letter-spacing="4">{code}</text>
  <text x="300" y="105" font-family="Georgia, serif" font-size="28" fill="{ROSE}" text-anchor="middle">{name}</text>
</svg>'''


def avatar_svg(name: str) -> str:
    initial = name[0] if name else "?"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
  <rect width="200" height="200" fill="{GRAY}"/>
  <circle cx="100" cy="80" r="34" fill="{GRAY2}"/>
  <path d="M40 180 C40 130 160 130 160 180 Z" fill="{GRAY2}"/>
  <text x="100" y="92" font-family="Georgia, serif" font-size="36" fill="{INK}" text-anchor="middle">{initial}</text>
</svg>'''


def detail_svg(label: str, abnormal: bool = False) -> str:
    """出店/返店细节照片（3:2）。"""
    color = ROSE if abnormal else INK
    tag = "异常" if abnormal else "正常"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="750" height="500" viewBox="0 0 750 500">
  <rect width="750" height="500" fill="{GRAY}"/>
  <rect x="24" y="24" width="702" height="452" fill="white" stroke="{GRAY2}" stroke-width="2"/>
  <circle cx="375" cy="230" r="90" fill="none" stroke="{color}" stroke-width="4" stroke-dasharray="10 8"/>
  <text x="375" y="245" font-family="Georgia, serif" font-size="40" fill="{color}" text-anchor="middle">{label}</text>
  <text x="375" y="420" font-family="sans-serif" font-size="26" fill="{color}" text-anchor="middle">【{tag}】</text>
</svg>'''


def save(svg: str, slot: str) -> dict:
    return core.save_photo(svg_data_url(svg), slot)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def reset_all() -> None:
    core.init_db()
    conn = core.get_db()
    try:
        for t in ("inspections", "deposits", "cleaning_records", "out_orders",
                  "appointments", "accessory_items", "accessory_sets", "gowns", "customers"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
    # 清空演示照片
    for f in os.listdir(core.PHOTO_DIR):
        if f.endswith((".svg", ".png", ".jpg", ".webp")):
            try:
                os.remove(os.path.join(core.PHOTO_DIR, f))
            except OSError:
                pass
    core.SETTLEMENT._records.clear()


def is_empty() -> bool:
    conn = core.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM gowns").fetchone()[0] == 0
    finally:
        conn.close()


def run() -> None:
    core.init_db()
    keep = "--keep" in sys.argv
    if not keep:
        reset_all()
    elif not is_empty():
        print("数据库已有数据，跳过生成（使用 --reset 以外的默认调用会重建）。")
        return

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    summary: dict[str, int] = {}

    # ---------------------------------------------------------------- 客户
    customers = []
    demo_customers = [
        ("林晚", "13800001001", "VIP 客户，偏好鱼尾款"),
        ("苏晴", "13800001002", "户外草坪婚礼"),
        ("陈墨", "13800001003", "已完成租赁，押金已结算"),
        ("周棠", "13800001004", "出店中，预计超时返店"),
        ("顾盼", "13800001005", "清洁不合格，待重新清洁"),
    ]
    for name, phone, note in demo_customers:
        av = save(avatar_svg(name), "avatar")["url"]
        customers.append(core.create_customer(name, phone, note, av))
    summary["customers"] = len(customers)

    # ---------------------------------------------------------------- 礼服
    gown_defs = [
        ("W001", "星幕鱼尾婚纱", "鱼尾", "象牙白", "S", 3000, 0),
        ("W002", "云朵蓬纱", "蓬裙", "米白", "M", 2500, 1),
        ("W003", "缎面复古礼服", "A 字", "香槟", "M", 4000, 2),
        ("W004", "高定蕾丝拖尾", "拖尾", "象牙白", "L", 8000, 0),
        ("W005", "短款小礼服", "短款", "玫瑰红", "S", 1500, 1),
        ("W006", "敬酒晚礼服", "修身", "黑色", "M", 2000, 2),
    ]
    gowns = []
    for code, name, style, color, size, dep, variant in gown_defs:
        photo = save(gown_svg(code, name, variant), f"gown_{code}")["url"]
        gowns.append(core.create_gown(code, name, style, color, size, dep, photo, ""))
    summary["gowns"] = len(gowns)

    # ---------------------------------------------------------------- 配件套装（按编号绑定）
    def make_set(code, name, items):
        return core.create_accessory_set(code, name, items, "演示套装")

    set_crown = make_set("AC01", "皇冠头纱套装", [
        {"code": "AC01-01", "name": "水晶皇冠"},
        {"code": "AC01-02", "name": "长款头纱"},
        {"code": "AC01-03", "name": "耳饰一对"},
    ])
    set_pearl = make_set("AC02", "珍珠项链套装", [
        {"code": "AC02-01", "name": "珍珠项链"},
        {"code": "AC02-02", "name": "珍珠耳钉"},
        {"code": "AC02-03", "name": "手链"},
    ])
    set_veil = make_set("AC03", "简约头纱套装", [
        {"code": "AC03-01", "name": "短头纱"},
        {"code": "AC03-02", "name": "发梳"},
    ])
    summary["accessory_sets"] = 3

    g = {x["code"]: x for x in gowns}
    c = {x["name"]: x for x in customers}

    # ---------------- 场景 1：未来有效预约（林晚 - W001）
    a1 = core.create_appointment(
        g["W001"]["id"], c["林晚"]["id"],
        iso(now + timedelta(days=1, hours=2)),
        iso(now + timedelta(days=1, hours=3)),
        "首次试穿，关注版型",
    )

    # ---------------- 场景 2：今日已签到预约（苏晴 - W002）
    a2 = core.create_appointment(
        g["W002"]["id"], c["苏晴"]["id"],
        iso(now - timedelta(hours=1)),
        iso(now + timedelta(hours=1)),
        "搭配头纱",
    )
    core.checkin_appointment(a2["id"])

    # ---------------- 场景 3：迟到取消（顾盼 - W006 预约后迟到取消，礼服释放）
    a_late = core.create_appointment(
        g["W006"]["id"], c["顾盼"]["id"],
        iso(now - timedelta(days=2, hours=2)),
        iso(now - timedelta(days=2, hours=1)),
    )
    core.cancel_appointment(a_late["id"], late=True)

    # ---------------- 场景 4：临时换款（林晚 - W005 换到 W006）
    a_swap = core.create_appointment(
        g["W005"]["id"], c["林晚"]["id"],
        iso(now + timedelta(days=3, hours=4)),
        iso(now + timedelta(days=3, hours=5)),
        "原订短款，想试晚礼服",
    )
    core.swap_appointment_gown(a_swap["id"], g["W006"]["id"])
    summary["appointments"] = 4

    # ---------------- 场景 5：完整闭环 — 陈墨 W003（出店→返店→扣款→清洁完成）
    out_photos_3 = [
        save(detail_svg("裙摆正面", False), "front"),
        save(detail_svg("裙摆底边", False), "hem"),
        save(detail_svg("拉链细节", False), "zipper"),
    ]
    o3 = core.create_out_order(
        g["W003"]["id"], c["陈墨"]["id"], set_pearl["id"], None,
        size_adjustments="腰围收 2cm，裙摆改短 1cm",
        pre_stains="无可见污渍（出店已拍照）",
        out_photos=out_photos_3,
        expected_return_time=iso(now - timedelta(days=1, hours=2)),
    )
    ins3 = core.create_return_inspection(o3["id"])
    # 逐项打勾：以检查单自带清单为基线，标记裙摆污渍、手链缺失
    result3 = {
        "hem": ("stain", "裙摆底边发现明显污渍"),
        "stains": ("stain", "与出店照片对比为新增"),
        "acc_AC02-03": ("missing", "手链未归还"),
    }
    items3 = []
    for it in core.get_inspection(ins3["id"])["items"]:
        if it["key"] in result3:
            r, note = result3[it["key"]]
            items3.append({"key": it["key"], "result": r, "note": note})
        else:
            items3.append({"key": it["key"], "result": "ok", "note": ""})
    missing_key3 = "acc_AC02-03"
    # 返店异常照片：hem / stains 与出店同 slot 配对
    ret_photos_3 = [
        {"data_url": svg_data_url(detail_svg("裙摆底边", True)), "slot": "hem"},
        {"data_url": svg_data_url(detail_svg("污渍特写", True)), "slot": "stains"},
        {"data_url": svg_data_url(detail_svg("缺失配件", True)), "slot": "acc_3"},
    ]
    core.update_inspection_items(ins3["id"], items3, ret_photos_3)
    # 押金扣款关联检查项与照片
    core.add_inspection_deduction(
        ins3["id"], "hem", 300, "裙摆污渍专业清洁费",
        [{"data_url": svg_data_url(detail_svg("污渍扣款凭证", True)), "slot": "ded_hem"}],
    )
    core.add_inspection_deduction(
        ins3["id"], missing_key3, 800, "珍珠手链遗失赔偿",
        [{"data_url": svg_data_url(detail_svg("缺失扣款凭证", True)), "slot": "ded_acc3"}],
    )
    core.confirm_inspection(ins3["id"])
    # 追加复核（已确认只能追加）
    core.add_inspection_review(ins3["id"], "店长复核：扣款金额与检查项、照片一致，同意结算。")
    # 清洁合格 → 礼服重新可约
    rec3 = core.list_cleaning_records(gown_id=g["W003"]["id"], status="pending")[0]
    core.update_cleaning(rec3["id"], "passed", "清洁完成，复查无残留")

    # ---------------- 场景 6：出店中 + 超时返店（周棠 W004 + 皇冠套装）
    out_photos_4 = [
        save(detail_svg("拖尾整体", False), "front"),
        save(detail_svg("皇冠", False), "crown"),
    ]
    o4 = core.create_out_order(
        g["W004"]["id"], c["周棠"]["id"], set_crown["id"], None,
        size_adjustments="胸围微调",
        pre_stains="无",
        out_photos=out_photos_4,
        expected_return_time=iso(now - timedelta(hours=6)),  # 已超时
    )
    summary["out_orders_open"] = 1

    # ---------------- 场景 7：清洁不合格（顾盼 W005 已返店，清洁不合格不可约）
    out_photos_5 = [save(detail_svg("短款整体", False), "front")]
    o5 = core.create_out_order(
        g["W005"]["id"], c["顾盼"]["id"], set_veil["id"], None,
        size_adjustments="无", pre_stains="无", out_photos=out_photos_5,
        expected_return_time=iso(now - timedelta(hours=10)),
    )
    ins5 = core.create_return_inspection(o5["id"])
    items5 = [{"key": x["key"], "result": "ok", "note": ""} for x in
              core.get_inspection(ins5["id"])["items"]]
    # 短款礼服有破损
    items5 = [{**x, "result": "damaged", "note": "后背勾丝"} if x["key"] == "damage" else x for x in items5]
    core.update_inspection_items(ins5["id"], items5, [
        {"data_url": svg_data_url(detail_svg("后背勾丝", True)), "slot": "damage"},
    ])
    core.add_inspection_deduction(
        ins5["id"], "damage", 500, "面料勾丝修补费",
        [{"data_url": svg_data_url(detail_svg("破损扣款凭证", True)), "slot": "ded_damage"}],
    )
    core.confirm_inspection(ins5["id"])
    rec5 = core.list_cleaning_records(gown_id=g["W005"]["id"], status="pending")[0]
    core.update_cleaning(rec5["id"], "failed", "顽固污渍一次清洁未达标")
    # W005 现 cleaning_status=failed 且有一条 pending 清洁记录，不可预约

    summary["inspections"] = 2
    summary["deductions"] = 3
    summary["cleaning_failed"] = 1

    print("=" * 56)
    print("演示数据生成完成")
    print("=" * 56)
    for k, v in summary.items():
        print(f"  {k:20s}: {v}")
    print("-" * 56)
    print("典型样例：")
    print(f"  有效预约     林晚 / W001 单号 {a1['code']}")
    print(f"  临时换款     W005 → W006 单号 {a_swap['code']}")
    print(f"  迟到取消     W006 单号 {a_late['code']}")
    print(f"  出店中(超时) 周棠 / W004 出店单 {o4['code']}")
    print(f"  返店+扣款    陈墨 / W003 检查单 {ins3['code']}（清洁完成可再约）")
    print(f"  清洁不合格   顾盼 / W005（不可预约）")
    print("=" * 56)


if __name__ == "__main__":
    run()
