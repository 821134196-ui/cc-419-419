# -*- coding: utf-8 -*-
"""服务端渲染的 HTML 页面。配色：黑白 + 玫瑰红 #B76E79 + 浅灰 #F2F0EF。"""
from __future__ import annotations

import html
import json
from typing import Any

ROSE = "#B76E79"

STATUS_CN = {
    "available": "可预约", "fitting": "试穿中", "out": "已出店",
    "cleaning": "清洁中", "retired": "已下架",
    "booked": "已预约", "arrived": "已到店", "late_cancelled": "迟到取消",
    "swapped": "已换款", "completed": "已完成", "no_show": "失约",
    "pending": "待出店", "active": "出店中", "returned": "已返店",
    "cancelled": "已取消",
    "reserved": "已预留", "incomplete": "缺件",
    "held": "持有中", "settled": "已结算",
    "washing": "清洁中", "passed": "合格", "failed": "不合格",
    "ok": "正常", "missing": "配件缺失", "damaged": "破损",
    "stained": "污渍", "late": "超时", "pending_item": "待检",
}
STATUS_CLASS = {
    "available": "ok", "booked": "rose", "arrived": "ink", "fitting": "ink",
    "out": "ink", "active": "ink", "cleaning": "warn", "incomplete": "danger",
    "late_cancelled": "danger", "swapped": "warn", "no_show": "danger",
    "returned": "ok", "completed": "ok", "missing": "danger",
    "damaged": "danger", "stained": "danger", "late": "warn",
    "failed": "danger", "passed": "ok", "washing": "warn",
    "held": "rose", "settled": "ok", "reserved": "warn", "retired": "muted",
    "cancelled": "muted", "pending": "warn",
}


def h(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def yuan(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"¥{cents / 100:,.0f}"


def badge(status: str) -> str:
    cls = STATUS_CLASS.get(status, "muted")
    return f'<span class="badge {cls}">{h(STATUS_CN.get(status, status))}</span>'


CSS = """
:root{--ink:#1a1a1a;--rose:#B76E79;--rose-d:#8E4A54;--gray:#F2F0EF;--line:#e3dfdd;}
*{box-sizing:border-box}
body{margin:0;font-family:"PingFang SC","Microsoft YaHei",Arial,sans-serif;
 color:var(--ink);background:#fff;font-size:14px;line-height:1.55}
a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--rose)}
a:hover{color:var(--rose-d)}
header{border-bottom:2px solid var(--ink);background:#fff;position:sticky;top:0;z-index:5}
.nav{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:4px;
 padding:10px 20px;flex-wrap:wrap}
.nav .brand{font-family:Georgia,serif;font-size:20px;letter-spacing:2px;
 margin-right:18px;border:none;color:var(--ink)}
.nav .brand b{color:var(--rose)}
.nav a.tab{border:1px solid transparent;padding:6px 14px;border-bottom:none}
.nav a.tab.on{border-color:var(--ink);background:var(--gray);font-weight:700}
.nav .sp{flex:1}
.cust{display:flex;align-items:center;gap:6px;font-size:12px;color:#555}
.wrap{max-width:1180px;margin:0 auto;padding:22px 20px 60px}
h1{font-family:Georgia,serif;font-size:24px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 12px;padding-left:10px;border-left:4px solid var(--rose)}
.sub{color:#777;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}
.card{border:1px solid var(--line);background:#fff;display:flex;flex-direction:column;
 transition:box-shadow .15s}
.card:hover{box-shadow:0 6px 18px rgba(183,110,121,.15)}
.card .photo{aspect-ratio:4/3;overflow:hidden;background:var(--gray);
 border-bottom:1px solid var(--line)}
.card .photo img{width:100%;height:100%;object-fit:cover;display:block}
.card .body{padding:12px 14px;flex:1}
.card .name{font-weight:700;font-size:15px}
.card .meta{color:#777;font-size:12px;margin-top:2px}
.card .foot{border-top:1px dashed var(--line);padding:10px 14px;background:#fafafa;
 min-height:74px;display:flex;flex-direction:column;gap:6px}
.sizes{display:flex;gap:5px;flex-wrap:wrap}
.chip{font-size:11px;border:1px solid var(--ink);padding:1px 7px;border-radius:2px}
.chip.rose{border-color:var(--rose);color:var(--rose-d)}
.bookline{font-size:12px;display:flex;justify-content:space-between;align-items:center;gap:6px}
.badge{display:inline-block;font-size:11px;padding:2px 9px;border-radius:2px;
 border:1px solid currentColor;white-space:nowrap}
.badge.ok{color:#2e7d4f}.badge.danger{color:#fff;background:var(--rose-d);border-color:var(--rose-d)}
.badge.warn{color:var(--rose-d);border-color:var(--rose)}.badge.ink{color:#fff;background:var(--ink)}
.badge.muted{color:#999;border-color:#ccc}
.badge.rose{color:var(--rose-d);border-color:var(--rose);background:#faf1f2}
table{width:100%;border-collapse:collapse;background:#fff}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--gray);font-weight:600;font-size:12px}
tr.danger td{background:#fdf3f4}
form.inline{display:inline}
input,select,textarea{font:inherit;border:1px solid #bbb;padding:5px 8px;background:#fff;
 border-radius:2px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--rose);outline-offset:-1px}
button,.btn{font:inherit;border:1px solid var(--ink);background:var(--ink);color:#fff;
 padding:6px 14px;cursor:pointer;border-radius:2px}
button:hover,.btn:hover{background:var(--rose-d);border-color:var(--rose-d)}
button.ghost,.btn.ghost{background:#fff;color:var(--ink)}
button.ghost:hover{background:var(--gray);color:var(--ink)}
button.danger{background:var(--rose-d);border-color:var(--rose-d)}
button.small{padding:3px 9px;font-size:12px}
.panel{border:1px solid var(--line);padding:16px 18px;background:#fff;margin-bottom:16px}
.panel.gray{background:var(--gray)}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
.row label{font-size:12px;color:#555}
.err{background:var(--rose-d);color:#fff;padding:10px 14px;margin-bottom:14px}
.okmsg{background:#eef6f0;color:#2e7d4f;border:1px solid #bcdcc8;padding:10px 14px;margin-bottom:14px}
.cal-day{margin-bottom:22px}
.cal-day h3{font-size:14px;margin:0 0 8px;background:var(--ink);color:#fff;
 display:inline-block;padding:3px 14px}
.appt{border:1px solid var(--line);padding:10px 14px;margin-bottom:8px;
 display:flex;gap:14px;align-items:center;flex-wrap:wrap;background:#fff}
.appt .time{font-weight:700;min-width:110px;font-family:Georgia,serif}
.appt .sp{flex:1}
/* 返店逐项打勾 */
.item-row{display:grid;grid-template-columns:220px 150px 1fr;gap:0;
 border:1px solid var(--line);border-bottom:none;background:#fff}
.item-row:last-child{border-bottom:1px solid var(--line)}
.item-row .cell{padding:10px 12px;border-right:1px solid var(--line)}
.item-row .cell:last-child{border-right:none}
.item-row.abn{background:#fdf3f4}
.item-head{display:grid;grid-template-columns:220px 150px 1fr;
 background:var(--gray);border:1px solid var(--line);border-bottom:2px solid var(--ink)}
.item-head div{padding:8px 12px;font-weight:700;font-size:12px}
.thumb{width:130px;height:98px;object-fit:cover;border:1px solid var(--line);
 background:var(--gray);display:block}
.thumb.tiny{width:64px;height:48px;float:left;margin:0 8px 4px 0}
.pair{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.pair .arrow{color:var(--rose);font-weight:700}
.deduct-box{border:1px dashed var(--rose-d);background:#fff;padding:8px 10px;margin-top:8px}
.deduct-box .amount{width:90px}
.check-square{width:16px;height:16px;border:2px solid var(--ink);display:inline-block;
 margin-right:6px;vertical-align:-3px;text-align:center;line-height:13px;color:var(--rose-d);
 font-weight:900;font-size:13px}
.check-square.on::before{content:"✓"}
.check-square.bad{border-color:var(--rose-d);color:var(--rose-d)}
.kv{display:grid;grid-template-columns:90px 1fr;gap:4px 12px;font-size:13px}
.kv dt{color:#777}.kv dd{margin:0}
.timeline{border-left:3px solid var(--rose);padding-left:14px;margin:8px 0}
.timeline .t{margin-bottom:8px;font-size:13px}
.pieces{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.pieces li{list-style:none;display:flex;gap:8px;align-items:center}
.pieces ul{padding:0;margin:0}
.review{background:var(--gray);padding:10px 14px;margin-top:8px;border-left:3px solid var(--ink)}
.muted{color:#999}.rose{color:var(--rose-d)}.b{font-weight:700}
"""

JS = """
function confirmGo(msg,f){return function(e){if(!confirm(msg)){e.preventDefault();return}
 if(f)f(e)}}
document.addEventListener('change',function(e){
 if(e.target.classList.contains('fileprev')){
   const box=e.target.closest('.cell,.deduct-box,div');
   let img=box.querySelector('.previmg');
   const file=e.target.files&&e.target.files[0];
   if(!file)return;
   if(!img){img=document.createElement('img');img.className='thumb previmg';
     img.style.marginTop='6px';box.appendChild(img);}
   img.src=URL.createObjectURL(file);
 }});
"""


def layout(title: str, active: str, body: str, cust: int | None = None,
           customers: list[dict] | None = None, err: str = "",
           ok: str = "") -> str:
    tabs = [("gowns", "礼服档案", "/gowns"), ("calendar", "试穿日历", "/calendar"),
            ("accessories", "搭配清单", "/accessories"),
            ("orders", "出店核验", "/orders"),
            ("returns", "返店检查", "/returns"),
            ("deposits", "押金记录", "/deposits")]
    nav = "".join(
        f'<a class="tab{" on" if k == active else ""}" href="{u}">{n}</a>'
        for k, n, u in tabs)
    opts = ['<option value="">店员视角（全部客户）</option>']
    for c in customers or []:
        sel = " selected" if cust == c["id"] else ""
        opts.append(f'<option value="{c["id"]}"{sel}>{h(c["code"])} · {h(c["name"])}</option>')
    flash = (f'<div class="err">{h(err)}</div>' if err else "") + \
            (f'<div class="okmsg">{h(ok)}</div>' if ok else "")
    return f"""<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(title)} · 婚纱礼服试穿与返店清点</title>
<style>{CSS}</style></head><body>
<header><div class="nav">
<a class="brand" href="/gowns">BRIDAL <b>·</b> 试穿清点</a>{nav}
<span class="sp"></span>
<form class="cust" method="get" action="/switch-customer">
<span>当前视角</span><select name="cust" onchange="this.form.submit()">
{''.join(opts)}</select></form>
</div></header>
<main class="wrap">{flash}{body}</main>
<script>{JS}</script></body></html>"""


# ----------------------------------------------------------------- 礼服档案
def gowns_page(gowns: list[dict], **kw) -> str:
    cards = []
    for g in gowns:
        sizes = "".join(
            f'<span class="chip{" rose" if i == 0 else ""}">{h(s["label"])}</span>'
            for i, s in enumerate(g["sizes"])) or '<span class="muted">均码</span>'
        nb = g["next_booking"]
        bookline = (f'最近预约 {h(nb["slot_date"][5:])} {h(nb["slot_start"])}'
                    if nb else '<span class="muted">暂无预约</span>')
        cards.append(f"""<div class="card">
<a class="photo" href="/calendar?gown={g['id']}"><img src="/photos/{h(g['cover_photo'])}"
 alt="{h(g['name'])}"></a>
<div class="body">
 <div class="name">{h(g['code'])} · {h(g['name'])}</div>
 <div class="meta">{h(g['style'])} · {h(g['color_note'])} ·
  租金 {yuan(g['rental_fee'])} / 押金 {yuan(g['deposit'])}</div>
</div>
<div class="foot">
 <div class="sizes">{sizes}</div>
 <div class="bookline">{bookline}{badge(g['status'])}</div>
</div></div>""")
    body = f"""<h1>礼服档案</h1>
<div class="sub">统一 4:3 封面比例；卡片底部固定尺码与预约状态。清洁完成前不可预约。</div>
<div class="grid">{''.join(cards)}</div>"""
    return layout("礼服档案", "gowns", body, **kw)


# ----------------------------------------------------------------- 日历
APPT_FORM = """
<div class="panel gray">
<b>新建试穿预约</b>（锁定具体礼服与时段）
<form method="post" action="/api/appointments" enctype="multipart/form-data">
<div class="row">
<label>客户<select name="customer_id" required>%CUST_OPTS%</select></label>
<label>礼服<select name="gown_id" required>%GOWN_OPTS%</select></label>
<label>尺码<input name="size_label" value="M" required style="width:64px"></label>
<label>配件套装<select name="accessory_set_id"><option value="">不搭配</option>%ACC_OPTS%</select></label>
</div><div class="row">
<label>日期<input type="date" name="slot_date" required></label>
<label>开始<input type="time" name="slot_start" value="10:00" required></label>
<label>结束<input type="time" name="slot_end" value="11:00" required></label>
<button type="submit">锁定档期</button>
</div></form></div>"""


def calendar_page(rows: list[dict], customers, gowns, accs,
                  preselect_gown: int | None = None, **kw) -> str:
    gown_opts = "".join(
        f'<option value="{g["id"]}"{" selected" if preselect_gown == g["id"] else ""}>'
        f'{h(g["code"])} {h(g["name"])}（{h(STATUS_CN[g["status"]])}）</option>'
        for g in gowns)
    cust_opts = "".join(
        f'<option value="{c["id"]}">{h(c["code"])} {h(c["name"])}</option>'
        for c in customers)
    acc_opts = "".join(
        f'<option value="{a["id"]}">{h(a["code"])} {h(a["name"])}</option>'
        for a in accs)
    form = (APPT_FORM.replace("%CUST_OPTS%", cust_opts)
            .replace("%GOWN_OPTS%", gown_opts)
            .replace("%ACC_OPTS%", acc_opts))
    days: dict[str, list[dict]] = {}
    for r in rows:
        days.setdefault(r["slot_date"], []).append(r)
    blocks = []
    for d in sorted(days):
        items = []
        for r in days[d]:
            acts = []
            if r["status"] == "booked":
                acts.append(
                    f'<form class="inline" method="post" action="/api/appointments/{r["id"]}/arrive">'
                    f'<input type="hidden" name="customer_id" value="{r["customer_id"]}">'
                    f'<button class="small">到店</button></form>')
                acts.append(
                    f'<form class="inline" method="post" action="/api/appointments/{r["id"]}/late-cancel">'
                    f'<input type="hidden" name="customer_id" value="{r["customer_id"]}">'
                    f'<input name="late_minutes" value="30" style="width:52px" title="迟到分钟">'
                    f'<button class="small ghost">迟到取消</button></form>')
                swap_gowns = "".join(
                    f'<option value="{g["id"]}">{h(g["code"])}</option>'
                    for g in gowns if g["id"] != r["gown_id"])
                acts.append(
                    f'<form class="inline" method="post" action="/api/appointments/{r["id"]}/swap">'
                    f'<input type="hidden" name="customer_id" value="{r["customer_id"]}">'
                    f'<select name="to_gown_id" title="换款礼服">{swap_gowns}</select>'
                    f'<input name="to_size" value="M" style="width:50px" title="新尺码">'
                    f'<button class="small ghost">临时换款</button></form>')
            if r["status"] in ("booked", "arrived"):
                acts.append(
                    f'<a class="btn small" href="/orders/new?appt_id={r["id"]}">开立出店单</a>')
            acc = (f'{h(r["acc_code"])} {h(r["acc_name"])}'
                   if r["acc_code"] else '<span class="muted">无配件</span>')
            items.append(f"""<div class="appt">
<span class="time">{h(r['slot_start'])}–{h(r['slot_end'])}</span>
<span>{h(r['customer_code'])} {h(r['customer_name'])}</span>
<span class="b">{h(r['gown_code'])} {h(r['gown_name'])}</span>
<span class="muted">{h(r['size_label'])} · {acc}</span>
{badge(r['status'])}
<span class="sp"></span>{' '.join(acts)}</div>""")
        blocks.append(f'<div class="cal-day"><h3>{h(d)}</h3>{"".join(items)}</div>')
    body = f"""<h1>试穿日历</h1>
<div class="sub">同一礼服同一时段不可重复锁定；清洁中 / 已出店礼服不可预约。</div>
{form}{''.join(blocks) or '<p class="muted">该时段暂无预约。</p>'}"""
    return layout("试穿日历", "calendar", body,
                  customers=customers, **{k: v for k, v in kw.items() if k != "customers"})


# ----------------------------------------------------------------- 配件
def accessories_page(accs: list[dict], **kw) -> str:
    cards = []
    for a in accs:
        lis = "".join(
            f'<li><span class="check-square on"></span>{h(p["code"])} · {h(p["name"])}</li>'
            for p in a["pieces"])
        restock = ""
        if a["status"] == "incomplete":
            restock = (f'<form method="post" action="/api/accessories/{a["id"]}/restock">'
                       f'<button class="small ghost" style="margin-top:8px">缺件已补齐，回库</button></form>')
        cards.append(f"""<div class="card">
<a class="photo" href="/photos/{h(a['cover_photo'])}"><img src="/photos/{h(a['cover_photo'])}"></a>
<div class="body"><div class="name">{h(a['code'])} · {h(a['name'])}</div>
<div class="pieces"><ul>{lis}</ul>{restock}</div></div>
<div class="foot"><div class="bookline">按编号绑定套装{badge(a['status'])}</div></div>
</div>""")
    body = f"""<h1>搭配清单</h1><div class="sub">配件以套装编号整体绑定；返店缺件则套装冻结，补齐后方可再次预约。</div>
<div class="grid">{''.join(cards)}</div>"""
    return layout("搭配清单", "accessories", body, **kw)


# ----------------------------------------------------------------- 出店单列表/新建
def orders_page(orders: list[dict], returns_mode: bool = False, **kw) -> str:
    active = "returns" if returns_mode else "orders"
    title = "返店检查" if returns_mode else "出店核验"
    if returns_mode:
        orders = [o for o in orders if o["status"] in ("active", "returned")]
    rows = "".join(
        f"""<tr><td><a href="/orders/{o['id']}">{h(o['code'])}</a></td>
<td>{h(o['customer_code'])} {h(o['customer_name'])}</td>
<td>{h(o['gown_code'])} {h(o['gown_name'])}</td><td>{h(o['acc_code'])}</td>
<td>{h(o['planned_return'][5:])}</td>
<td>{h((o['actual_return'] or '—')[5:])}</td><td>{badge(o['status'])}</td></tr>"""
        for o in orders)
    body = f"""<h1>{title}</h1>
<div class="sub">{'出店中/已返店订单在此逐项核对；已确认结果只能追加复核。' if returns_mode
                  else '出店前记录尺寸调整、污渍与细节照片；同一礼服不可同时存在两张有效出店单。'}</div>
<table><thead><tr><th>单号</th><th>客户</th><th>礼服</th><th>配件</th>
<th>约定返店</th><th>实际返店</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>"""
    return layout(title, active, body, **kw)


def new_order_page(appt: dict, accessories: list[dict], **kw) -> str:
    default_items = ["裙摆正中央|stain|出店检查无可见污渍",
                     "胸口钉珠|detail|珠饰数量完整",
                     "后背拉链|detail|开合顺畅",
                     "拖尾内衬|detail|无勾丝"]
    rows = "".join(
        f"""<tr><td><input name="label" value="{h(l)}" style="width:150px"></td>
<td><select name="category"><option value="stain"{" selected" if c == 'stain' else ""}>污渍</option>
<option value="damage">破损</option><option value="detail"{" selected" if c == 'detail' else ""}>细节</option></select></td>
<td><input name="outgoing_note" value="{h(n)}" style="width:260px"></td>
<td><input type="file" name="photo" class="fileprev" accept="image/*"></td></tr>"""
        for l, c, n in (s.split("|") for s in default_items))
    body = f"""<h1>开立出店单</h1>
<div class="sub">预约 {h(appt['code'])}：{h(appt['gown_code'])} {h(appt['gown_name'])}
 · {h(appt['customer_name'])} · 尺码 {h(appt['size_label'])}</div>
<form method="post" action="/api/orders" enctype="multipart/form-data">
<input type="hidden" name="appointment_id" value="{appt['id']}">
<input type="hidden" name="customer_id" value="{appt['customer_id']}">
<input type="hidden" name="gown_id" value="{appt['gown_id']}">
<div class="panel">
<div class="row"><label>配件套装（按编号绑定）<select name="accessory_set_id" required>
{''.join(f'<option value="{a["id"]}"{" selected" if appt["accessory_set_id"] == a["id"] else ""}>{h(a["code"])} {h(a["name"])}</option>' for a in accessories)}</select></label>
<label>约定返店<input type="datetime-local" name="planned_return" required></label></div>
<div class="row"><label>尺寸调整记录<input name="size_adjust" style="width:340px"
 placeholder="如：腰围收 2cm，前摆改短 1cm"></label>
<label>调整照片<input type="file" name="adjust_photo" class="fileprev" accept="image/*"></label></div>
</div>
<h2>出店核验明细</h2>
<p class="sub">配件套装的组成件会自动追加为检查项，返店时逐一清点。</p>
<table><thead><tr><th>检查部位</th><th>类别</th><th>出店状态</th><th>出店照片</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="row" style="margin-top:16px"><button>确认出店并收取押金</button>
<a href="/calendar" class="btn ghost">取消</a></div>
</form>"""
    return layout("出店核验", "orders", body, **kw)


# ----------------------------------------------------------------- 出店单详情
_RESULT_OPTIONS = {
    "accessory": [("ok", "齐全"), ("missing", "缺失")],
    "late": [("late", "确认超时")],
    "stain": [("ok", "正常"), ("stained", "污渍")],
    "damage": [("ok", "正常"), ("damaged", "破损")],
    "detail": [("ok", "正常"), ("stained", "污渍"), ("damaged", "破损")],
}


def _img(path: str, cls: str = "thumb") -> str:
    return f'<img class="{cls}" src="/photos/{h(path)}">'


def order_detail_page(o: dict, **kw) -> str:
    deductions_by_item: dict[int, list[dict]] = {}
    if o.get("deposit"):
        for dd in o["deposit"]["deductions"]:
            deductions_by_item.setdefault(dd["item_id"], []).append(dd)

    head = """<div class="item-head"><div>检查项</div><div>出店记录（核验照）</div>
<div>返店逐项打勾（异常照片 ⇄ 扣款金额并排）</div></div>"""
    rows_html = []
    for it in o["items"]:
        out = [p for p in it["photos"] if p["phase"] == "outgoing"]
        ret = [p for p in it["photos"] if p["phase"] == "return"]
        paired = it["photos"] and all(p["paired"] for p in it["photos"]) if it["photos"] else False
        out_html = "".join(
            f'<div style="margin-bottom:6px">{_img(p["path"])}'
            f'<div class="muted" style="font-size:11px">{h(p["note"] or "出店照")}</div></div>'
            for p in out) or '<span class="muted">无出店照</span>'

        left = f"""<div class="b">{it['seq']}. {h(it['label'])}</div>
<div style="margin:4px 0">{badge(it['category'] if it['category'] in STATUS_CN else 'pending')}
<span class="muted" style="font-size:11px">{h(it['outgoing_note'])}</span></div>"""
        mid = f'<div class="pair">{out_html}</div>'

        if o["status"] == "active":
            opts = _RESULT_OPTIONS.get(it["category"], _RESULT_OPTIONS["detail"])
            radios = "".join(
                f'<label style="margin-right:10px;white-space:nowrap">'
                f'<input type="radio" name="result" value="{v}" required>'
                f'<span class="check-square"></span>{n}</label>'
                for v, n in opts)
            right = f"""<form method="post" action="/api/orders/{o['id']}/items/{it['id']}"
 enctype="multipart/form-data" class="checkform">
<input type="hidden" name="customer_id" value="{o['customer_id']}">
<div class="row" style="margin:2px 0">{radios}</div>
<div class="row" style="margin:2px 0"><input name="note" placeholder="情况说明" style="width:230px">
<input type="file" name="photo" class="fileprev" accept="image/*"></div>
<button class="small">提交勾选</button></form>"""
            if it["return_result"] != "pending":
                ret_thumbs = "".join(_img(p["path"], "thumb tiny") for p in ret)
                right = (f'<div>{badge(it["return_result"])} '
                         f'<span class="muted" style="font-size:12px">{h(it["return_note"] or "")}</span>'
                         f'<div style="margin:6px 0">{ret_thumbs or ""}</div></div>' + right)
        else:
            ret_html = "".join(
                f'{_img(p["path"], "thumb tiny")}' for p in ret) or \
                '<span class="muted">无返店照</span>'
            right = (f'<div>{badge(it["return_result"])} '
                     f'<span class="muted" style="font-size:12px">{h(it["return_note"] or "")}</span>'
                     f'<div style="margin:6px 0">{ret_html}</div></div>')

        # 异常照片与扣款金额并排
        abn = it["return_result"] in ("missing", "damaged", "stained", "late")
        dd_list = deductions_by_item.get(it["id"], [])
        dd_html = "".join(
            f'<div class="deduct-box" style="display:flex;gap:10px;align-items:center">'
            f'{_img(dd["photo_path"], "thumb tiny")}'
            f'<div style="flex:1"><b class="rose">{yuan(dd["amount"])}</b>'
            f'<div class="muted" style="font-size:11px">{h(dd["reason"])}</div></div></div>'
            for dd in dd_list)
        if abn and ret and o["status"] == "active":
            photo_id = ret[-1]["id"]
            dd_form = f"""<div class="deduct-box" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
{_img(ret[-1]['path'], 'thumb tiny')}
<form method="post" action="/api/orders/{o['id']}/deduct"
 style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<input type="hidden" name="customer_id" value="{o['customer_id']}">
<input type="hidden" name="item_id" value="{it['id']}">
<input type="hidden" name="photo_id" value="{photo_id}">
<input class="amount" name="amount_yuan" type="number" min="1" step="1" placeholder="扣款元" required>
<input name="reason" placeholder="扣款事由（关联此项与照片）" style="width:220px" required>
<button class="small danger">登记扣款</button></form></div>"""
            right += dd_form
        right += dd_html

        cls = "item-row abn" if abn else "item-row"
        pair_mark = ' <span class="muted" style="font-size:11px">照片已配对 ✓</span>' \
            if paired and out and ret else ("" if not (out or ret) else
            ' <span class="muted" style="font-size:11px">待对侧照片配对</span>')
        rows_html.append(
            f'<div class="{cls}"><div class="cell">{left}{pair_mark}</div>'
            f'<div class="cell">{mid}</div><div class="cell">{right}</div></div>')

    # 尺寸调整
    sa = o.get("size_adjust") or {}
    sa_lines = "".join(
        f"<dt>{h(k)}</dt><dd>{h(v)}</dd>" for k, v in sa.items() if k != "photo" and v)
    sa_photo = _img(sa["photo"], "thumb tiny") if sa.get("photo") else ""

    # 返店操作
    ops = []
    if o["status"] == "active" and not o["actual_return"]:
        ops.append(f"""<form method="post" action="/api/orders/{o['id']}/return-start"
 class="inline"><input type="hidden" name="customer_id" value="{o['customer_id']}">
 <input type="datetime-local" name="actual_return" required>
 <button>登记实际返店时间</button></form>""")
    if o["status"] == "active" and o["actual_return"]:
        ops.append(f"""<form method="post" action="/api/orders/{o['id']}/confirm" class="inline">
<input type="hidden" name="customer_id" value="{o['customer_id']}">
<button>全部无异议，确认返店（冻结结果 → 进入清洁）</button></form>""")

    # 清洁
    clean_rows = "".join(
        f'<div class="t">第 {c["round_no"]} 轮：{badge(c["result"])} '
        f'{h(c["qc_note"] or "")} '
        f'{_img(_clean_photo(o, c), "thumb tiny") if _clean_photo(o, c) else ""}</div>'
        for c in o["cleanings"]) or '<p class="muted">尚未进入清洁。</p>'
    clean_ops = ""
    if o["status"] == "returned":
        clean_ops = f"""<form method="post" action="/api/orders/{o['id']}/cleaning"
 enctype="multipart/form-data" class="row">
<select name="result"><option value="passed">清洁合格（释放礼服）</option>
<option value="failed">清洁不合格（返工，礼服继续锁定）</option></select>
<input name="note" placeholder="质检说明" style="width:260px">
<input type="file" name="photo" class="fileprev" accept="image/*">
<button class="small">提交质检</button></form>"""

    # 押金与结算
    dep_html = ""
    if o.get("deposit"):
        d = o["deposit"]
        ded_total = sum(x["amount"] for x in d["deductions"])
        settle_btn = ""
        if d["status"] == "held":
            settle_btn = f"""<form method="post" action="/api/orders/{o['id']}/settle" class="inline">
<input type="hidden" name="customer_id" value="{o['customer_id']}">
<button>结算押金（扣 {yuan(ded_total)}，退 {yuan(d['amount']-ded_total)}）</button></form>"""
        dep_html = f"""<h2>押金</h2><div class="panel gray">
<div class="row"><b>{h(d['code'])}</b>{badge(d['status'])}
<span>收取 {yuan(d['amount'])}</span><span>扣款 {yuan(ded_total)}</span>
<span>退还 {yuan(d['refunded'])}</span>{settle_btn}</div></div>"""

    # 复核（只追加）
    review_html = "".join(
        f'<div class="review"><div class="muted" style="font-size:11px">{h(r["created_at"])}</div>'
        f'{h(r["body"])}</div>' for r in o["reviews"])
    review_form = ""
    if o["status"] == "returned":
        review_form = f"""<form method="post" action="/api/orders/{o['id']}/reviews" class="row">
<input type="hidden" name="customer_id" value="{o['customer_id']}">
<input name="body" placeholder="追加复核意见（不改变已确认结果）" style="flex:1;min-width:260px">
<button class="ghost small">追加复核</button></form>"""

    late_warn = '<span class="badge danger">超时返店</span>' if o["is_late"] else ""
    body = f"""<h1>出店单 {h(o['code'])}</h1>
<div class="sub"><div class="row">
{badge(o['status'])} {late_warn}
<span>{h(o.get('customer_code',''))} {h(o.get('customer_name',''))}</span>
<b>{h(o.get('gown_code',''))} {h(o.get('gown_name',''))}</b>
<span>{h(o.get('acc_code',''))} {h(o.get('acc_name',''))}</span>
<span>约定返店 {h(o['planned_return'])}</span>
<span>实际返店 {h(o['actual_return'] or '—')}</span></div></div>
<div class="panel"><div class="kv">{sa_lines}</div><div style="margin-top:8px">{sa_photo}</div></div>
<h2>返店逐项核对</h2>
{head}{''.join(rows_html)}
<div class="row" style="margin-top:14px">{''.join(ops)}</div>
<h2>清洁状态</h2><div class="panel gray"><div class="timeline">{clean_rows}</div>{clean_ops}</div>
{dep_html}
<h2>返店复核</h2>{review_html}{review_form}
<p><a href="/returns">← 返回返店检查列表</a></p>"""
    return layout(f"出店单 {o['code']}", "orders", body, **kw)


def _clean_photo(o: dict, c: dict) -> str | None:
    for p in o["loose_photos"]:
        if p["id"] == c["qc_photo_id"]:
            return p["path"]
    return None


# ----------------------------------------------------------------- 押金记录
def deposits_page(deps: list[dict], ledger: list[dict], **kw) -> str:
    cards = []
    for d in deps:
        dd = "".join(
            f"""<div class="deduct-box" style="display:flex;gap:10px;align-items:center">
{_img(x['photo_path'], 'thumb tiny')}
<div style="flex:1"><b class="rose">-{yuan(x['amount'])}</b>
<div>{h(x['item_label'])}</div>
<div class="muted" style="font-size:11px">{h(x['reason'])}</div></div></div>"""
            for x in d["deduction_rows"]) or '<div class="muted" style="font-size:12px">无扣款</div>'
        cards.append(f"""<div class="card" style="min-width:300px">
<div class="body"><div class="row" style="margin:0"><b>{h(d['code'])}</b>{badge(d['status'])}</div>
<div class="meta">{h(d['customer_code'])} {h(d['customer_name'])} · 出店单 {h(d['order_code'])}</div>
<div class="row" style="margin:6px 0"><span>收 {yuan(d['amount'])}</span>
<span class="rose">扣 {yuan(d['deducted'])}</span><span>退 {yuan(d['refunded'])}</span></div>
{dd}</div></div>""")
    led = "".join(
        f'<tr><td>{h(r["created_at"])}</td><td>{h(r["idem_key"])}</td>'
        f'<td>{h({"deposit_charge":"收押金","refund":"退款","deduct":"扣款"}.get(r["kind"], r["kind"]))}</td>'
        f'<td>#{r["customer_id"]}</td><td>{yuan(r["amount"])}</td></tr>'
        for r in ledger)
    body = f"""<h1>押金记录</h1>
<div class="sub">扣款必须关联返店检查项与异常照片；相同幂等键不重复扣款/结算。</div>
<div class="grid">{''.join(cards)}</div>
<h2>结算适配器流水（进程内模拟）</h2>
<table><thead><tr><th>时间</th><th>幂等键</th><th>类型</th><th>客户</th><th>金额</th>
</tr></thead><tbody>{led}</tbody></table>"""
    return layout("押金记录", "deposits", body, **kw)
