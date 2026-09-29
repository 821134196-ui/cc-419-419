/* 婚纱礼服试穿与返店清点系统 — 前端 */
(() => {
"use strict";

// ---------------------------------------------------------------- API
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "请求失败");
  return j.data;
};

// ---------------------------------------------------------------- 工具
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
const yuan = (cents) => "¥" + (Number(cents || 0) / 100).toFixed(2);
const fmtTime = (s) => s ? s.replace("T", " ").slice(0, 16) : "—";
const dateOnly = (s) => (s || "").slice(0, 10);
const pad2 = (n) => String(n).padStart(2, "0");
// 本地时区的当前时间（库内时间为本地无时区 ISO，不能用 toISOString 的 UTC）
const nowLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
};
const todayLocal = () => nowLocal().slice(0, 10);

const GOWN_STATUS = {
  available: "在店可约", reserved: "已预约锁定", out: "已出店", cleaning: "清洁中",
};
const CLEAN_STATUS = { clean: "清洁完成", pending: "待清洁", failed: "清洁不合格" };
const APPT_STATUS = {
  booked: "已预约", checked_in: "已签到", completed: "已完成",
  cancelled: "已取消", late_cancelled: "迟到取消", swapped: "已换款",
};
const ORDER_STATUS = { out: "出店中", returned: "已返店", closed: "已关闭" };
const RESULT_LABEL = { ok: "正常", missing: "缺失", damaged: "破损", stain: "污渍" };
const RESULT_COLOR = { ok: "ok", missing: "missing", damaged: "damaged", stain: "stain" };

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), 2600);
}

// ---------------------------------------------------------------- 模态框
function openModal(title, bodyNode, footNode, wide = false) {
  $("#modal-title").textContent = title;
  const b = $("#modal-body");
  b.innerHTML = "";
  b.appendChild(bodyNode);
  const f = $("#modal-foot");
  f.innerHTML = "";
  if (footNode) f.appendChild(footNode);
  f.style.display = footNode ? "flex" : "none";
  $("#modal").className = "modal" + (wide ? " wide" : "");
  $("#modal-mask").classList.add("show");
}
function closeModal() { $("#modal-mask").classList.remove("show"); }
$("#modal-x").onclick = closeModal;
$("#modal-mask").addEventListener("click", (e) => { if (e.target.id === "modal-mask") closeModal(); });

function fileToDataUrl(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

/** 照片上传小控件，收集 dataURL 列表。editableSlot=true 时每张照片可单独标注部位标签（用于出/返店按 slot 配对）。 */
function photoUploader(slot = "photo", editableSlot = false) {
  const wrap = el("div", "photo-strip");
  const photos = [];
  const addBtn = el("label", "photo-upload", "+<span>添加照片</span>");
  const input = el("input");
  input.type = "file";
  input.accept = "image/*";
  input.multiple = true;
  input.style.display = "none";
  input.onchange = async () => {
    for (const f of input.files) {
      const url = await fileToDataUrl(f);
      const p = { url, data_url: url, slot };
      photos.push(p);
      renderThumb(p, true);
    }
    input.value = "";
  };
  addBtn.appendChild(input);
  function renderThumb(p, removable) {
    const t = el("div", "photo-thumb");
    const img = el("img");
    img.src = p.url || p.data_url;
    t.appendChild(img);
    const cap = el("div", "cap");
    if (editableSlot) {
      const sin = el("input");
      sin.value = p.slot || slot;
      sin.style.cssText = "border:0;background:transparent;font-size:11px;padding:0;width:72px;color:inherit;";
      sin.placeholder = "部位标签";
      sin.onclick = (e) => e.stopPropagation();
      sin.oninput = () => { p.slot = sin.value || slot; };
      cap.appendChild(sin);
    } else {
      cap.appendChild(el("span", null, esc(p.slot || slot)));
    }
    if (removable) {
      const x = el("button", "x", "×");
      x.type = "button";
      x.onclick = () => {
        const i = photos.indexOf(p);
        if (i >= 0) photos.splice(i, 1);
        t.remove();
      };
      cap.appendChild(x);
    }
    t.appendChild(cap);
    wrap.insertBefore(t, addBtn);
  }
  wrap.appendChild(addBtn);
  return {
    node: wrap,
    get: () => photos.map((p) => ({ data_url: p.data_url, slot: p.slot || slot })),
    clear() { photos.length = 0; wrap.querySelectorAll(".photo-thumb").forEach((t) => t.remove()); },
    seed(existing) { (existing || []).forEach((p) => renderThumb(p, false)); },
  };
}

// ---------------------------------------------------------------- 缓存
const cache = { customers: [], gowns: [], sets: [] };
async function refreshCache() {
  [cache.customers, cache.gowns, cache.sets] = await Promise.all([
    api("/api/customers"), api("/api/gowns"), api("/api/accessory-sets"),
  ]);
}
const gownById = (id) => cache.gowns.find((g) => g.id === id);
const customerById = (id) => cache.customers.find((c) => c.id === id);
const setById = (id) => cache.sets.find((s) => s.id === id);

// ---------------------------------------------------------------- 视图路由
const VIEWS = {
  gowns: { title: "礼服档案", sub: "管理礼服照片、尺码与在店状态", render: viewGowns },
  calendar: { title: "试穿日历", sub: "预约锁定具体礼服与试穿时段", render: viewCalendar },
  accessories: { title: "搭配清单", sub: "配件套装按编号绑定，随礼服出店与清点", render: viewAccessories },
  outcheck: { title: "出店核验", sub: "出店前记录尺寸调整、污渍与细节照片", render: viewOutCheck },
  return: { title: "返店检查", sub: "逐项核对 · 异常照片与扣款并排 · 清洁合格后方可再约", render: viewReturn },
  deposits: { title: "押金记录", sub: "押金扣款关联检查项与照片，结算幂等", render: viewDeposits },
};
let currentView = "gowns";
async function go(view) {
  currentView = view;
  document.querySelectorAll("#nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  const v = VIEWS[view];
  $("#view-title").textContent = v.title;
  $("#view-sub").textContent = v.sub;
  $("#head-actions").innerHTML = "";
  const node = $("#view");
  node.innerHTML = `<div class="empty">加载中…</div>`;
  try {
    await refreshCache();
    await v.render(node);
  } catch (e) {
    node.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}
$("#nav").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b) go(b.dataset.view);
});

// ================================================================ 礼服档案
function gownStatusBadge(g) {
  const cls = g.status === "cleaning" && g.cleaning_status === "failed" ? "failed"
    : g.status === "cleaning" ? "cleaning" : g.status;
  const txt = g.status === "cleaning" && g.cleaning_status === "failed"
    ? "清洁不合格" : GOWN_STATUS[g.status];
  return `<span class="badge ${cls}">${txt}</span>`;
}

async function viewGowns(node) {
  const gowns = await api("/api/gowns");
  const counts = {
    all: gowns.length,
    available: gowns.filter((g) => g.status === "available").length,
    reserved: gowns.filter((g) => g.status === "reserved").length,
    out: gowns.filter((g) => g.status === "out").length,
    cleaning: gowns.filter((g) => g.status === "cleaning").length,
  };
  const bar = el("div", "toolbar");
  const stats = el("div", "stat-row");
  stats.innerHTML = [
    ["全部礼服", counts.all, ""],
    ["在店可约", counts.available, ""],
    ["预约锁定", counts.reserved, ""],
    ["已出店", counts.out, "rose"],
    ["清洁中", counts.cleaning, "rose"],
  ].map(([l, v, c]) => `<div class="stat"><div class="v ${c}">${v}</div><div class="l">${l}</div></div>`).join("");

  const filterSel = el("select");
  filterSel.innerHTML = `<option value="">全部状态</option>
    <option value="available">在店可约</option><option value="reserved">预约锁定</option>
    <option value="out">已出店</option><option value="cleaning">清洁中</option>`;
  filterSel.onchange = () => renderGrid(filterSel.value);
  const fWrap = el("div", "field");
  fWrap.appendChild(filterSel);
  const newBtn = el("button", "btn rose", "+ 新建礼服");
  newBtn.onclick = gownFormModal;
  bar.append(fWrap, newBtn);

  const grid = el("div", "gown-grid");
  function renderGrid(filter) {
    const list = filter ? gowns.filter((g) => g.status === filter) : gowns;
    grid.innerHTML = "";
    if (!list.length) { grid.appendChild(el("div", "empty", "暂无礼服")); return; }
    list.forEach((g) => {
      const card = el("div", "card gown-card");
      card.innerHTML = `
        <div class="gown-photo">
          <img src="${esc(g.photo || "")}" alt="" onerror="this.style.visibility='hidden'">
          <span class="ph-status">${gownStatusBadge(g)}</span>
          <span class="ph-code">${esc(g.code)}</span>
        </div>
        <div class="gown-body">
          <h3>${esc(g.name)}</h3>
          <div class="meta"><span>${esc(g.style || "—")}</span><span>${esc(g.color || "")}</span>
          <span>押金 ${yuan(g.deposit_amount)}</span></div>
        </div>
        <div class="gown-foot">
          <span class="size">${esc(g.size || "—")}</span>
          ${gownStatusBadge(g)}
        </div>`;
      card.onclick = () => gownDetailModal(g.id);
      grid.appendChild(card);
    });
  }
  renderGrid("");
  node.append(stats, bar, grid);
}

function gownFormModal() {
  const body = el("div");
  body.innerHTML = `
    <div class="row2">
      <div class="field"><label>礼服编号 *</label><input id="f-code" placeholder="如 W007"></div>
      <div class="field"><label>名称 *</label><input id="f-name" placeholder="如 法式拖尾婚纱"></div>
      <div class="field"><label>款式</label><input id="f-style" placeholder="鱼尾 / 蓬裙…"></div>
      <div class="field"><label>颜色</label><input id="f-color" placeholder="象牙白…"></div>
      <div class="field"><label>尺码</label><input id="f-size" placeholder="S / M / L"></div>
      <div class="field"><label>押金（元）</label><input id="f-dep" type="number" value="2000" min="0"></div>
    </div>
    <div class="field"><label>备注</label><textarea id="f-note" rows="2"></textarea></div>`;
  const uploader = photoUploader("gown_photo");
  body.appendChild(el("div", "field", "<label>礼服照片（统一 3:4）</label>")).appendChild(uploader.node);
  const save = el("button", "btn rose", "保存礼服");
  save.onclick = async () => {
    try {
      const photos = uploader.get();
      await api("/api/gowns", { method: "POST", body: {
        code: $("#f-code", body).value.trim(),
        name: $("#f-name", body).value.trim(),
        style: $("#f-style", body).value.trim(),
        color: $("#f-color", body).value.trim(),
        size: $("#f-size", body).value.trim(),
        deposit_yuan: Number($("#f-dep", body).value) || 0,
        note: $("#f-note", body).value.trim(),
        photo: photos[0] ? photos[0].data_url : "",
      }});
      toast("礼服已创建");
      closeModal();
      go("gowns");
    } catch (e) { toast(e.message, true); }
  };
  openModal("新建礼服", body, save);
}

async function gownDetailModal(gownId) {
  const g = await api(`/api/gowns/${gownId}`);
  const appts = (await api(`/api/appointments?gown_id=${gownId}`)).filter(
    (a) => ["booked", "checked_in"].includes(a.status));
  const cleaning = await api(`/api/cleaning?gown_id=${gownId}`);
  const body = el("div");
  body.innerHTML = `
    <div style="display:flex;gap:18px;">
      <img src="${esc(g.photo || "")}" style="width:150px;aspect-ratio:3/4;object-fit:cover;border-radius:8px;border:1px solid var(--gray-2);">
      <div style="flex:1;">
        <div class="kv"><span class="k">编号</span><span>${esc(g.code)} ${gownStatusBadge(g)}</span></div>
        <div class="kv"><span class="k">名称</span><span>${esc(g.name)}</span></div>
        <div class="kv"><span class="k">款式/颜色</span><span>${esc(g.style)} / ${esc(g.color)}</span></div>
        <div class="kv"><span class="k">尺码</span><b>${esc(g.size || "—")}</b></div>
        <div class="kv"><span class="k">押金</span><span>${yuan(g.deposit_amount)}</span></div>
        <div class="kv"><span class="k">清洁状态</span><span class="badge ${g.cleaning_status}">${CLEAN_STATUS[g.cleaning_status]}</span></div>
      </div>
    </div>`;
  // 有效预约
  body.appendChild(el("div", "section-title", "有效预约 / 占用"));
  if (!appts.length) body.appendChild(el("div", "muted", "暂无有效预约"));
  else {
    const tbl = el("table");
    tbl.innerHTML = `<thead><tr><th>单号</th><th>客户</th><th>时段</th><th>状态</th><th>操作</th></tr></thead>`;
    const tb = el("tbody");
    appts.forEach((a) => {
      const tr = el("tr");
      tr.innerHTML = `<td>${esc(a.code)}</td><td>${esc(a.customer_name)}</td>
        <td class="nowrap">${fmtTime(a.start_time)}<br><span class="muted">至 ${fmtTime(a.end_time)}</span></td>
        <td><span class="badge ${a.status}">${APPT_STATUS[a.status]}</span></td>`;
      const td = el("td");
      const swap = el("button", "btn ghost sm", "换款");
      swap.onclick = () => swapModal(a);
      const cancel = el("button", "btn danger sm", "迟到取消");
      cancel.style.marginLeft = "6px";
      cancel.onclick = async () => {
        if (!confirm("按迟到取消该预约？礼服将释放。")) return;
        try { await api(`/api/appointments/${a.id}/cancel`, { method: "POST", body: { late: true } });
          toast("已迟到取消"); closeModal(); go(currentView); } catch (e) { toast(e.message, true); }
      };
      td.append(swap, cancel);
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    body.appendChild(tbl);
  }
  // 清洁记录
  body.appendChild(el("div", "section-title", "清洁记录"));
  if (!cleaning.length) body.appendChild(el("div", "muted", "暂无清洁记录"));
  else {
    const tbl = el("table");
    tbl.innerHTML = `<thead><tr><th>时间</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>`;
    const tb = el("tbody");
    cleaning.forEach((r) => {
      const tr = el("tr");
      tr.innerHTML = `<td class="nowrap">${fmtTime(r.created_at)}</td>
        <td><span class="badge ${r.status}">${CLEAN_STATUS[r.status] || r.status}</span></td>
        <td>${esc(r.note || "")}</td>`;
      const td = el("td");
      if (r.status === "pending") {
        const pass = el("button", "btn sm", "合格");
        pass.onclick = async () => {
          try { await api(`/api/cleaning/${r.id}`, { method: "POST", body: { status: "passed", note: "清洁完成" } });
            toast("清洁合格，礼服恢复可约"); closeModal(); go(currentView); } catch (e) { toast(e.message, true); }
        };
        const fail = el("button", "btn danger sm", "不合格");
        fail.style.marginLeft = "6px";
        fail.onclick = async () => {
          try { await api(`/api/cleaning/${r.id}`, { method: "POST", body: { status: "failed", note: "需重新清洁" } });
            toast("已标记不合格，礼服继续清洁流程"); closeModal(); go(currentView); } catch (e) { toast(e.message, true); }
        };
        td.append(pass, fail);
      } else td.textContent = "—";
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    body.appendChild(tbl);
  }
  // 新建预约
  const foot = el("div");
  if (["available", "reserved"].includes(g.status) && g.cleaning_status === "clean") {
    const book = el("button", "btn rose", "+ 预约试穿");
    book.onclick = () => appointmentFormModal(g);
    foot.appendChild(book);
  } else {
    foot.appendChild(el("span", "muted", g.status === "out" ? "礼服已出店" :
      g.cleaning_status === "failed" ? "清洁不合格，需重新清洁后才能预约" : "清洁完成前不能预约"));
  }
  openModal(`礼服详情 · ${g.name}`, body, foot, true);
}

function appointmentFormModal(gown) {
  const body = el("div");
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  const base = now.toISOString().slice(0, 16);
  body.innerHTML = `
    <div class="kv" style="margin-bottom:14px;"><span class="k">礼服</span><span>${esc(gown.code)} ${esc(gown.name)}（${esc(gown.size)}）</span></div>
    <div class="field"><label>客户 *</label><select id="a-cus">${cache.customers.map((c) =>
      `<option value="${c.id}">${esc(c.name)} ${esc(c.phone || "")}</option>`).join("")}</select></div>
    <div class="row2">
      <div class="field"><label>开始 *</label><input id="a-start" type="datetime-local" value="${base}"></div>
      <div class="field"><label>结束 *</label><input id="a-end" type="datetime-local" value="${base}"></div>
    </div>
    <div class="field"><label>备注</label><textarea id="a-note" rows="2"></textarea></div>`;
  const ok = el("button", "btn rose", "锁定预约");
  ok.onclick = async () => {
    try {
      await api("/api/appointments", { method: "POST", body: {
        gown_id: gown.id,
        customer_id: Number($("#a-cus", body).value),
        start_time: $("#a-start", body).value + ":00",
        end_time: $("#a-end", body).value + ":00",
        note: $("#a-note", body).value.trim(),
      }});
      toast("预约已锁定"); closeModal(); go(currentView);
    } catch (e) { toast(e.message, true); }
  };
  openModal("预约试穿", body, ok);
}

async function swapModal(appt) {
  const body = el("div");
  body.innerHTML = `<p class="muted" style="margin-bottom:12px;">将预约 <b>${esc(appt.code)}</b> 临时换款，原礼服释放。</p>
    <div class="field"><label>换成礼服 *</label><select id="s-gown"></select></div>`;
  const sel = $("#s-gown", body);
  cache.gowns.filter((x) => x.id !== appt.gown_id).forEach((x) => {
    const bookable = x.status === "available" && x.cleaning_status === "clean";
    sel.appendChild(el("option", null,
      `${x.code} ${x.name} ${bookable ? "（可约）" : "（" + GOWN_STATUS[x.status] + "）"}`)).value = x.id;
    if (!bookable) sel.lastChild.disabled = true;
  });
  const ok = el("button", "btn rose", "确认换款");
  ok.onclick = async () => {
    try {
      await api(`/api/appointments/${appt.id}/swap`, { method: "POST", body: { new_gown_id: Number(sel.value) } });
      toast("换款成功"); closeModal(); go(currentView);
    } catch (e) { toast(e.message, true); }
  };
  openModal("临时换款", body, ok);
}

// ================================================================ 试穿日历
async function viewCalendar(node) {
  const now = new Date();
  let year = now.getFullYear(), month = now.getMonth();
  const appts = await api("/api/appointments");

  const cal = el("div", "card cal-wrap");
  const head = el("div", "cal-head");
  const title = el("h3");
  const prev = el("button", "btn ghost sm", "‹ 上月");
  const next = el("button", "btn ghost sm", "下月 ›");
  const newBtn = el("button", "btn rose sm", "+ 新建预约");
  newBtn.onclick = () => {
    const avail = cache.gowns.find((g) => g.status === "available" && g.cleaning_status === "clean");
    if (!avail) return toast("暂无在店可约礼服", true);
    appointmentFormModal(avail);
  };
  prev.onclick = () => { month--; if (month < 0) { month = 11; year--; } draw(); };
  next.onclick = () => { month++; if (month > 11) { month = 0; year++; } draw(); };
  head.append(prev, title, next, newBtn);

  const grid = el("div");
  cal.append(head, grid);
  node.appendChild(cal);

  function draw() {
    title.textContent = `${year} 年 ${month + 1} 月`;
    grid.innerHTML = "";
    const dow = el("div", "cal-grid");
    ["日", "一", "二", "三", "四", "五", "六"].forEach((d) => dow.appendChild(el("div", "cal-dow", d)));
    const cells = el("div", "cal-grid");
    const first = new Date(year, month, 1);
    const start = new Date(year, month, 1 - first.getDay());
    const today = todayLocal();
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const cell = el("div", "cal-cell" + (d.getMonth() !== month ? " other" : "") + (ds === today ? " today" : ""));
      cell.appendChild(el("div", "d", String(d.getDate())));
      appts.filter((a) => dateOnly(a.start_time) === ds).forEach((a) => {
        const ev = el("div", `cal-ev ${a.status}`,
          `${a.start_time.slice(11, 16)} ${esc(a.gown_code)} ${esc(a.customer_name)}`);
        ev.title = `${APPT_STATUS[a.status]} · ${esc(a.gown_name)}`;
        ev.onclick = () => apptDetailModal(a.id);
        cell.appendChild(ev);
      });
      cells.appendChild(cell);
    }
    grid.append(dow, cells);
  }
  draw();
}

async function apptDetailModal(id) {
  const a = await api(`/api/appointments/${id}`);
  const body = el("div");
  body.innerHTML = `
    <div class="kv"><span class="k">单号</span><span>${esc(a.code)}</span></div>
    <div class="kv"><span class="k">状态</span><span class="badge ${a.status}">${APPT_STATUS[a.status]}</span></div>
    <div class="kv"><span class="k">礼服</span><span>${esc(a.gown_code)} ${esc(a.gown_name)}（${esc(a.gown_size)}）</span></div>
    <div class="kv"><span class="k">客户</span><span>${esc(a.customer_name)}</span></div>
    <div class="kv"><span class="k">时段</span><span>${fmtTime(a.start_time)} ~ ${fmtTime(a.end_time)}</span></div>
    ${a.swap_from_gown_id ? `<div class="kv"><span class="k">换款</span><span class="rose-text">由礼服 #${a.swap_from_gown_id} 换入</span></div>` : ""}
    <div class="kv"><span class="k">备注</span><span>${esc(a.note || "—")}</span></div>`;
  const foot = el("div");
  if (a.status === "booked") {
    const ci = el("button", "btn sm", "签到");
    ci.onclick = async () => { try { await api(`/api/appointments/${id}/checkin`, { method: "POST", body: {} });
      toast("已签到"); closeModal(); go("calendar"); } catch (e) { toast(e.message, true); } };
    foot.appendChild(ci);
  }
  if (["booked", "checked_in"].includes(a.status)) {
    const swap = el("button", "btn ghost sm", "临时换款");
    swap.style.marginLeft = "8px";
    swap.onclick = () => swapModal(a);
    const out = el("button", "btn rose sm", "办理出店");
    out.style.marginLeft = "8px";
    out.onclick = () => { closeModal(); outOrderFormModal(a.gown_id, a.customer_id, a.id); };
    const cancel = el("button", "btn danger sm", "取消预约");
    cancel.style.marginLeft = "8px";
    cancel.onclick = async () => {
      if (!confirm("取消该预约？")) return;
      try { await api(`/api/appointments/${id}/cancel`, { method: "POST", body: {} });
        toast("已取消"); closeModal(); go("calendar"); } catch (e) { toast(e.message, true); }
    };
    foot.append(swap, out, cancel);
  }
  openModal("预约详情", body, foot);
}

// ================================================================ 搭配清单
async function viewAccessories(node) {
  const sets = await api("/api/accessory-sets");
  const bar = el("div", "toolbar");
  const info = el("div", "muted", `共 ${sets.length} 个配件套装`);
  const newBtn = el("button", "btn rose", "+ 新建配件套装");
  newBtn.onclick = setFormModal;
  bar.append(info, newBtn);
  const grid = el("div", "gown-grid");
  sets.forEach((s) => {
    const card = el("div", "card");
    card.style.padding = "16px";
    card.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <b>${esc(s.name)}</b><span class="ph-code" style="position:static;background:var(--ink);color:#fff;">${esc(s.code)}</span></div>`;
    const list = el("div", "pill-list");
    s.items.forEach((it) => list.appendChild(el("span", "accessory-chip",
      `<b>${esc(it.code)}</b> &nbsp;${esc(it.name)}`)));
    card.appendChild(list);
    card.appendChild(el("div", "muted", `${s.items.length} 件配件`));
    card.style.cursor = "pointer";
    card.onclick = () => setDetailModal(s);
    grid.appendChild(card);
  });
  if (!sets.length) grid.appendChild(el("div", "empty", "暂无配件套装"));
  node.append(bar, grid);
}

function setFormModal() {
  const body = el("div");
  body.innerHTML = `
    <div class="row2">
      <div class="field"><label>套装编号 *</label><input id="s-code" placeholder="AC04"></div>
      <div class="field"><label>套装名称 *</label><input id="s-name" placeholder="珍珠套装"></div>
    </div>`;
  const itemsBox = el("div");
  const rows = [];
  function addRow(code = "", name = "") {
    const r = el("div", "deduct-line");
    r.innerHTML = `<input placeholder="编号 AC04-01" value="${esc(code)}" style="width:150px">
      <input placeholder="配件名称" value="${esc(name)}">`;
    const del = el("button", "btn danger sm", "删");
    del.onclick = () => { r.remove(); rows.splice(rows.indexOf(r), 1); };
    r.appendChild(del);
    itemsBox.appendChild(r);
    rows.push(r);
  }
  addRow(); addRow();
  const add = el("button", "btn ghost sm", "+ 添加配件");
  add.onclick = () => addRow();
  body.append(itemsBox, add);
  const save = el("button", "btn rose", "保存套装");
  save.onclick = async () => {
    try {
      const items = rows.map((r) => ({
        code: r.querySelectorAll("input")[0].value.trim(),
        name: r.querySelectorAll("input")[1].value.trim(),
      })).filter((x) => x.code && x.name);
      await api("/api/accessory-sets", { method: "POST", body: {
        code: $("#s-code", body).value.trim(), name: $("#s-name", body).value.trim(), items,
      }});
      toast("套装已创建"); closeModal(); go("accessories");
    } catch (e) { toast(e.message, true); }
  };
  openModal("新建配件套装", body, save);
}

async function setDetailModal(s) {
  const orders = await api("/api/out-orders?status=out");
  const inUse = orders.find((o) => o.accessory_set_id === s.id);
  const body = el("div");
  body.innerHTML = `<div class="kv"><span class="k">套装</span><span>${esc(s.code)} ${esc(s.name)}</span></div>
    <div class="kv"><span class="k">状态</span><span>${inUse
      ? `<span class="badge out">随 ${esc(inUse.code)} 出店中</span>`
      : `<span class="badge available">在店可用</span>`}</span></div>`;
  const tbl = el("table");
  tbl.innerHTML = `<thead><tr><th>编号</th><th>名称</th></tr></thead>`;
  const tb = el("tbody");
  s.items.forEach((it) => tb.appendChild(el("tr", null,
    `<td><b>${esc(it.code)}</b></td><td>${esc(it.name)}</td>`)));
  tbl.appendChild(tb);
  body.appendChild(tbl);
  openModal("配件套装详情", body);
}

// ================================================================ 出店核验
async function viewOutCheck(node) {
  const orders = await api("/api/out-orders");
  const out = orders.filter((o) => o.status === "out");
  const stats = el("div", "stat-row");
  const overdue = out.filter((o) => o.expected_return_time && o.expected_return_time < nowLocal());
  stats.innerHTML = `<div class="stat"><div class="v rose">${out.length}</div><div class="l">出店中</div></div>
    <div class="stat"><div class="v rose">${overdue.length}</div><div class="l">超时未返店</div></div>
    <div class="stat"><div class="v">${orders.filter((o) => o.status === "returned").length}</div><div class="l">已返店</div></div>`;
  const bar = el("div", "toolbar");
  const newBtn = el("button", "btn rose", "+ 新建出店单");
  newBtn.onclick = () => outOrderFormModal();
  bar.appendChild(newBtn);

  const card = el("div", "card");
  if (!orders.length) card.appendChild(el("div", "empty", "暂无出店单"));
  else {
    const tbl = el("table");
    tbl.innerHTML = `<thead><tr><th>出店单号</th><th>礼服</th><th>客户</th><th>配件套装</th>
      <th>押金</th><th>出店时间</th><th>应返时间</th><th>状态</th><th></th></tr></thead>`;
    const tb = el("tbody");
    orders.forEach((o) => {
      const isOverdue = o.status === "out" && o.expected_return_time &&
        o.expected_return_time < nowLocal();
      const tr = el("tr");
      tr.innerHTML = `<td><b>${esc(o.code)}</b></td>
        <td>${esc(o.gown_code)}<br><span class="muted">${esc(o.gown_name)}</span></td>
        <td>${esc(o.customer_name)}</td>
        <td>${o.set_code ? esc(o.set_code) : '<span class="muted">无</span>'}</td>
        <td>${yuan(o.deposit_amount)}</td>
        <td class="nowrap">${fmtTime(o.out_time)}</td>
        <td class="nowrap">${fmtTime(o.expected_return_time)}${isOverdue ? '<br><span class="flag-overdue">超时返店</span>' : ""}</td>
        <td><span class="badge ${o.status}">${ORDER_STATUS[o.status]}</span></td>`;
      const td = el("td");
      if (o.status === "out") {
        const ret = el("button", "btn rose sm", "返店检查");
        ret.onclick = () => startReturn(o.id);
        td.appendChild(ret);
      } else {
        const view = el("button", "btn ghost sm", "查看检查");
        view.onclick = async () => {
          const list = await api(`/api/inspections?customer_id=${o.customer_id}`);
          const ins = list.find((x) => x.order_code === o.code);
          if (ins) inspectionModal(ins.id);
        };
        td.appendChild(view);
      }
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    card.appendChild(tbl);
  }
  node.append(stats, bar, card);
}

async function startReturn(orderId) {
  try {
    const ins = await api(`/api/out-orders/${orderId}/return`, { method: "POST", body: {} });
    toast("已创建返店检查单");
    inspectionModal(ins.id);
  } catch (e) { toast(e.message, true); }
}

function outOrderFormModal(prefGownId, prefCustomerId, prefApptId) {
  const body = el("div");
  // 已出店/清洁未完成的礼服不可选；已预约礼服可凭对应预约出店（后端校验冲突）
  const selectableGowns = cache.gowns.filter((g) => g.status !== "out");
  body.innerHTML = `
    <div class="row2">
      <div class="field"><label>礼服 *</label><select id="o-gown"></select></div>
      <div class="field"><label>客户 *</label><select id="o-cus">${cache.customers.map((c) =>
        `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
      <div class="field"><label>配件套装（按编号绑定）</label><select id="o-set"><option value="">不搭配配件</option></select></div>
      <div class="field"><label>关联预约</label><select id="o-appt"><option value="">无</option></select></div>
      <div class="field"><label>应返时间</label><input id="o-return" type="datetime-local"></div>
      <div class="field"><label>押金（元，自动取礼服押金）</label><input id="o-dep" disabled></div>
    </div>
    <div class="field"><label>尺寸调整记录</label><textarea id="o-size" rows="2" placeholder="如：腰围收 2cm"></textarea></div>
    <div class="field"><label>出店污渍 / 现状</label><textarea id="o-stain" rows="2" placeholder="出店前可见污渍说明"></textarea></div>`;
  const gownSel = $("#o-gown", body), setSel = $("#o-set", body),
        apptSel = $("#o-appt", body), depInp = $("#o-dep", body);
  selectableGowns.forEach((g) => {
    const clean = g.cleaning_status === "clean";
    const op = el("option", null,
      `${g.code} ${g.name}${g.status === "reserved" ? "（已预约）" : clean ? "（在店）" : "（清洁中）"}`);
    op.value = g.id;
    if (!clean) op.disabled = true;
    gownSel.appendChild(op);
  });
  cache.sets.forEach((s) => setSel.appendChild(el("option", null,
    `${s.code} ${s.name}（${s.items.length} 件）`)).value = s.id);
  function syncDep() { const g = gownById(Number(gownSel.value)); depInp.value = g ? (g.deposit_amount / 100).toFixed(2) : ""; }
  async function syncAppts() {
    const gid = Number(gownSel.value);
    const appts = (await api(`/api/appointments?gown_id=${gid}`)).filter((a) =>
      ["booked", "checked_in"].includes(a.status));
    apptSel.innerHTML = `<option value="">无</option>` + appts.map((a) =>
      `<option value="${a.id}">${esc(a.code)} · ${esc(a.customer_name)} · ${a.start_time.slice(11, 16)}</option>`).join("");
    if (prefApptId) apptSel.value = prefApptId;
  }
  gownSel.onchange = () => { syncDep(); syncAppts(); };
  if (prefGownId) gownSel.value = prefGownId;
  if (prefCustomerId) $("#o-cus", body).value = prefCustomerId;
  syncDep(); syncAppts();

  const up = photoUploader("front", true);
  const pField = el("div", "field", "<label>出店细节照片（每张可标注部位标签 front / hem / zipper…，返店按相同标签配对）</label>");
  pField.appendChild(up.node);
  body.appendChild(pField);

  const ok = el("button", "btn rose", "确认出店");
  ok.onclick = async () => {
    try {
      await api("/api/out-orders", { method: "POST", body: {
        gown_id: Number(gownSel.value),
        customer_id: Number($("#o-cus", body).value),
        accessory_set_id: setSel.value ? Number(setSel.value) : null,
        appointment_id: apptSel.value ? Number(apptSel.value) : null,
        size_adjustments: $("#o-size", body).value.trim(),
        pre_stains: $("#o-stain", body).value.trim(),
        out_photos: up.get(),
        expected_return_time: $("#o-return", body).value ? $("#o-return", body).value + ":00" : "",
      }});
      toast("出店单已创建，礼服锁定"); closeModal(); go("outcheck");
    } catch (e) { toast(e.message, true); }
  };
  openModal("新建出店单 · 出店核验", body, ok, true);
}

// ================================================================ 返店检查
async function viewReturn(node) {
  const [orders, inspections] = await Promise.all([
    api("/api/out-orders?status=out"), api("/api/inspections"),
  ]);
  const bar = el("div", "toolbar");
  bar.innerHTML = `<span class="muted">待返店 ${orders.length} 单 · 检查单 ${inspections.length} 张</span>`;

  const card = el("div", "card");
  if (!orders.length && !inspections.length) card.appendChild(el("div", "empty", "暂无返店检查"));
  else {
    const tbl = el("table");
    tbl.innerHTML = `<thead><tr><th>检查/出店单</th><th>礼服</th><th>客户</th><th>检查状态</th><th>异常项</th><th>扣款合计</th><th></th></tr></thead>`;
    const tb = el("tbody");
    // 出店中尚未建检查单
    orders.forEach((o) => {
      const tr = el("tr");
      tr.innerHTML = `<td class="muted">${esc(o.code)}<br><span class="muted">未建检查单</span></td>
        <td>${esc(o.gown_code)} ${esc(o.gown_name)}</td><td>${esc(o.customer_name)}</td>
        <td><span class="badge out">出店中</span></td><td>—</td><td>—</td>`;
      const td = el("td");
      const b = el("button", "btn rose sm", "开始返店检查");
      b.onclick = () => startReturn(o.id);
      td.appendChild(b); tr.appendChild(td); tb.appendChild(tr);
    });
    inspections.forEach((ins) => {
      const abnormal = ins.items.filter((i) => i.result && i.result !== "ok").length;
      const ded = (ins.deductions || []).reduce((s, d) => s + d.amount, 0);
      const tr = el("tr");
      tr.innerHTML = `<td><b>${esc(ins.code)}</b><br><span class="muted">${esc(ins.order_code)}</span></td>
        <td>${esc(ins.gown_code)} ${esc(ins.gown_name)}</td><td>${esc(ins.customer_name)}</td>
        <td><span class="badge ${ins.status}">${ins.status === "draft" ? "待确认" : "已确认"}</span></td>
        <td>${abnormal ? `<span class="rose-text">${abnormal} 项</span>` : "0"}</td>
        <td>${ded ? `<span class="rose-text">${yuan(ded)}</span>` : "—"}</td>`;
      const td = el("td");
      const b = el("button", "btn ghost sm", ins.status === "draft" ? "继续检查" : "查看 / 复核");
      b.onclick = () => inspectionModal(ins.id);
      td.appendChild(b); tr.appendChild(td); tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    card.appendChild(tbl);
  }
  node.append(bar, card);
}

async function inspectionModal(id) {
  const ins = await api(`/api/inspections/${id}`);
  const readonly = ins.status === "confirmed";
  const body = el("div");

  // 概要
  const summary = el("div", "dep-summary");
  summary.innerHTML = `<span>检查单 <b>${esc(ins.code)}</b></span>
    <span>出店单 <b>${esc(ins.order_code)}</b></span>
    <span>礼服 <b>${esc(ins.gown_code)} ${esc(ins.gown_name)}</b></span>
    <span>客户 <b>${esc(ins.customer_name)}</b></span>
    <span>状态 <span class="badge ${ins.status}">${readonly ? "已确认（仅可追加复核）" : "待确认"}</span></span>`;
  body.appendChild(summary);
  if (ins.size_adjustments || ins.pre_stains) {
    body.appendChild(el("div", "muted",
      `出店记录：尺寸调整「${esc(ins.size_adjustments || "无")}」 · 污渍「${esc(ins.pre_stains || "无")}」`));
  }

  // 逐项打勾
  body.appendChild(el("div", "section-title", "逐项核对（正常 / 缺失 / 破损 / 污渍）"));
  const list = el("div", "check-list");
  const state = {}; // key -> {result, note, photos[], deductions[]}
  ins.items.forEach((it) => {
    state[it.key] = {
      result: it.result || "ok", note: it.note || "",
      photos: [], deductions: [], uploader: null,
    };
    const item = el("div", "check-item");
    item.dataset.key = it.key;
    item.innerHTML = `<div class="ci-top">
        <span class="ci-label">${esc(it.label)}<span class="ci-kind">${it.kind === "accessory" ? "配件" : "礼服"}</span></span>
        <span class="ci-opts">
          ${["ok", "missing", "damaged", "stain"].map((r) =>
            `<button type="button" class="ci-opt ${RESULT_COLOR[r]}" data-r="${r}">${RESULT_LABEL[r]}</button>`).join("")}
        </span>
      </div>
      <div class="ci-note"><input placeholder="异常说明（如：底边 3cm 污渍）" value="${esc(it.note || "")}"></div>
      <div class="ci-bottom">
        <div class="ci-photos"><h4>异常照片（部位标签需与出店照片一致，如 hem）</h4><div class="photo-strip"></div></div>
        <div class="ci-deduct"><h4>押金扣款（关联本检查项与照片）</h4><div class="deduct-existing"></div>
          <div class="deduct-line"><input type="number" placeholder="扣款金额(元)" min="0" step="0.01">
          <input placeholder="扣款原因" style="flex:1;min-width:120px"><button type="button" class="btn rose sm">添加扣款</button></div>
        </div>
      </div>`;
    list.appendChild(item);

    const noteInp = $("input[placeholder^='异常说明']", item);
    const optBtns = item.querySelectorAll(".ci-opt");
    const photoStrip = $(".ci-photos .photo-strip", item);
    // 返店照片默认 slot 取检查项 key，与出店同部位照片配对
    const up = photoUploader(it.key);
    state[it.key].uploader = up;
    photoStrip.appendChild(up.node);
    const dedBox = $(".deduct-existing", item);
    const dedInputs = item.querySelectorAll(".deduct-line input");
    const addDedBtn = $(".deduct-line .btn", item);

    function paint() {
      const st = state[it.key];
      const abnormal = st.result !== "ok";
      item.classList.toggle("abnormal", abnormal);
      optBtns.forEach((b) => b.classList.toggle("sel", b.dataset.r === st.result));
    }
    optBtns.forEach((b) => b.onclick = () => {
      if (readonly) return;
      state[it.key].result = b.dataset.r; paint();
    });
    noteInp.oninput = () => (state[it.key].note = noteInp.value);

    addDedBtn.onclick = () => {
      if (readonly) return;
      const amt = Number(dedInputs[0].value), reason = dedInputs[1].value.trim();
      if (!(amt > 0)) return toast("扣款金额必须大于 0", true);
      if (!reason) return toast("请填写扣款原因", true);
      if (state[it.key].result === "ok")
        return toast("该检查项为「正常」，不可扣款；请先标记异常", true);
      // 当前异常照片快照作为扣款凭证（slot=ded_<检查项>）；照片本身仍随检查项提交用于配对
      const dedPhotos = up.get().map((p) => ({ data_url: p.data_url, slot: `ded_${it.key}` }));
      const rec = { amount: amt, reason, photos: dedPhotos, persisted: false };
      state[it.key].deductions.push(rec);
      const chip = el("div", "deduct-chip", `<span>${esc(reason)}</span><strong>${yuan(amt * 100)}</strong>`);
      const x = el("button", "x", "×");
      x.onclick = () => {
        const idx = state[it.key].deductions.indexOf(rec);
        if (idx >= 0) state[it.key].deductions.splice(idx, 1);
        chip.remove();
        recalc();
      };
      chip.appendChild(x);
      dedBox.appendChild(chip);
      dedInputs[0].value = ""; dedInputs[1].value = "";
      recalc();
    };
    // 已保存的扣款（草稿暂存/已确认）：标记 persisted，不重复提交
    (ins.deductions || []).filter((d) => d.item_key === it.key).forEach((d) => {
      state[it.key].deductions.push({ amount: d.amount / 100, reason: d.reason, persisted: true });
      const chip = el("div", "deduct-chip", `<span>${esc(d.reason)}</span><strong>${yuan(d.amount)}</strong>`);
      dedBox.appendChild(chip);
    });
    paint();
  });
  body.appendChild(list);

  // 已保存的照片配对（出店 vs 返店）
  if (ins.paired_photos && ins.paired_photos.length) {
    body.appendChild(el("div", "section-title", "照片配对（出店 → 返店）"));
    const pg = el("div", "pair-grid");
    ins.paired_photos.forEach((p) => {
      const rets = p.returns || [];
      const abnormal = p.slot && !["front", "crown"].includes(p.slot);
      const miss = (p.out && rets.length === 0) || (!p.out && rets.length > 0);
      const card = el("div", "pair-card" + (miss ? " miss" : ""));
      card.innerHTML = `<div class="pc-head"><span>${esc(p.slot)}</span>
        <span class="${abnormal ? "rose-text" : "muted"}">${abnormal ? "异常对比" : "常规"}</span></div>`;
      const imgs = el("div", "pc-imgs");
      const blank = `<img class="dash" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='200'><rect width='100%25' height='100%25' fill='%23f2f2f2'/></svg>">`;
      imgs.innerHTML = `<div class="pair-side"><div class="tag">出店</div>
          ${p.out ? `<img src="${esc(p.out.url)}">` : blank}</div>
        <div class="pair-side"><div class="tag">返店${rets.length ? " ×" + rets.length : ""}</div>
          ${rets.length ? rets.map((r) => `<img src="${esc(r.url)}" class="${abnormal ? "dash" : ""}">`).join("") : blank}</div>`;
      card.appendChild(imgs);
      pg.appendChild(card);
    });
    body.appendChild(pg);
  }

  // 扣款合计
  const totalBar = el("div", "dep-summary", "");
  function recalc() {
    let total = 0;
    Object.values(state).forEach((s) => s.deductions.forEach((d) => (total += d.amount * 100)));
    totalBar.innerHTML = `<span>本次扣款合计 <b class="rose-text" id="ded-total">${yuan(total)}</b></span>
      <span class="muted">确认后从押金按幂等键结算（重复确认不会重复扣款）</span>`;
  }
  recalc();
  body.appendChild(totalBar);

  // 复核记录
  if (ins.review) {
    body.appendChild(el("div", "section-title", "复核记录"));
    const rv = el("div", "card");
    rv.style.padding = "12px 16px";
    rv.style.whiteSpace = "pre-wrap";
    rv.textContent = ins.review;
    body.appendChild(rv);
  }

  const foot = el("div");
  if (!readonly) {
    const save = el("button", "btn ghost", "暂存检查结果");
    save.onclick = () => submitItems(ins, state, false);
    const confirm = el("button", "btn rose", "确认返店并结算押金");
    confirm.style.marginLeft = "8px";
    confirm.onclick = () => {
      if (!confirm("确认后返店结果不可修改（仅可追加复核），礼服进入清洁流程。继续？")) return;
      submitItems(ins, state, true);
    };
    foot.append(save, confirm);
  } else {
    const inp = el("input");
    inp.placeholder = "追加复核内容…";
    inp.style.marginRight = "10px";
    inp.style.width = "320px";
    const rv = el("button", "btn", "追加复核");
    rv.onclick = async () => {
      if (!inp.value.trim()) return toast("请填写复核内容", true);
      try { await api(`/api/inspections/${id}/review`, { method: "POST", body: { review: inp.value.trim() } });
        toast("复核已追加"); closeModal(); inspectionModal(id); } catch (e) { toast(e.message, true); }
    };
    foot.append(inp, rv);
  }
  openModal(`返店检查 · ${ins.gown_name}`, body, foot, true);

  async function submitItems(ins, state, doConfirm) {
    try {
      const items = Object.entries(state).map(([key, s]) => ({ key, result: s.result, note: s.note }));
      // 收集每个检查项上传框中尚未提交的异常照片（slot 默认为检查项 key）
      const photos = [];
      document.querySelectorAll(".check-item").forEach((node) => {
        const key = node.dataset.key;
        const st = state[key];
        const fresh = (st.uploader ? st.uploader.get() : []).filter((p) => !p._saved);
        photos.push(...fresh);
      });
      await api(`/api/inspections/${id}/items`, { method: "POST", body: { items, photos } });
      // 已入档的异常照片从上传框清空，避免暂存时重复保存
      document.querySelectorAll(".check-item").forEach((node) => state[node.dataset.key]?.uploader?.clear());
      // 逐笔提交新扣款（已持久化的不重复提交，保证幂等）
      for (const [key, s] of Object.entries(state)) {
        for (const d of s.deductions) {
          if (d.persisted) continue;
          await api(`/api/inspections/${id}/deductions`, { method: "POST", body: {
            item_key: key, amount_yuan: d.amount, reason: d.reason, photos: d.photos,
          }});
          d.persisted = true;
        }
      }
      if (doConfirm) {
        await api(`/api/inspections/${id}/confirm`, { method: "POST", body: {} });
        toast("返店已确认，押金完成结算，礼服进入清洁");
        closeModal(); go("return");
      } else {
        toast("检查结果已暂存");
        closeModal(); inspectionModal(id);
      }
    } catch (e) { toast(e.message, true); }
  }
}

// ================================================================ 押金记录
async function viewDeposits(node) {
  const deposits = await api("/api/deposits");
  const total = deposits.reduce((s, d) => s + d.amount, 0);
  const ded = deposits.reduce((s, d) => s + d.deduction_total, 0);
  const refund = deposits.reduce((s, d) => s + d.refund_amount, 0);
  const stats = el("div", "stat-row");
  stats.innerHTML = `<div class="stat"><div class="v">${yuan(total)}</div><div class="l">押金收入合计</div></div>
    <div class="stat"><div class="v rose">${yuan(ded)}</div><div class="l">扣款合计</div></div>
    <div class="stat"><div class="v">${yuan(refund)}</div><div class="l">退款合计</div></div>
    <div class="stat"><div class="v">${deposits.filter((d) => d.status === "paid").length}</div><div class="l">持有中</div></div>`;

  const bar = el("div", "toolbar");
  const cusSel = el("select");
  cusSel.innerHTML = `<option value="">全部客户（客户隔离视图）</option>` +
    cache.customers.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  cusSel.onchange = () => draw(cusSel.value);
  const f = el("div", "field"); f.appendChild(cusSel); bar.appendChild(f);

  const card = el("div", "card");
  node.append(stats, bar, card);

  async function draw(cid) {
    const list = await api("/api/deposits" + (cid ? `?customer_id=${cid}` : ""));
    card.innerHTML = "";
    if (!list.length) { card.appendChild(el("div", "empty", "暂无押金记录")); return; }
    const tbl = el("table");
    tbl.innerHTML = `<thead><tr><th>押金单号</th><th>出店单</th><th>客户</th><th>礼服</th>
      <th>押金</th><th>扣款</th><th>实退</th><th>状态</th><th>结算</th></tr></thead>`;
    const tb = el("tbody");
    list.forEach((d) => {
      const tr = el("tr");
      const replay = d.settle_result && d.settle_result.idempotent_replay;
      tr.innerHTML = `<td><b>${esc(d.code)}</b><br><span class="muted">幂等键 ${esc(d.idempotency_key)}</span></td>
        <td>${esc(d.order_code)}</td>
        <td>${esc(d.customer_name)}</td>
        <td>${esc(d.gown_code)} ${esc(d.gown_name)}</td>
        <td>${yuan(d.amount)}</td>
        <td>${d.deduction_total ? `<span class="rose-text">${yuan(d.deduction_total)}</span>` : "—"}</td>
        <td>${d.settled_at ? yuan(d.refund_amount) : "—"}</td>
        <td><span class="badge ${d.status}">${({ paid: "持有中", refunded: "已全退", deducted: "已扣款" })[d.status]}</span></td>
        <td>${d.settled_at ? `<span class="muted nowrap">${fmtTime(d.settled_at)}</span>` : "未结算"}
            ${replay ? '<br><span class="badge cleaning">幂等重放</span>' : ""}</td>`;
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    card.appendChild(tbl);
  }
  draw("");
}

// ---------------------------------------------------------------- 启动
go("gowns");
})();
