# -*- coding: utf-8 -*-
"""零依赖 HTTP 服务：页面 + 表单动作 + 本地照片。

启动：python3 -m app.server [--port 8000] [--host 127.0.0.1]
"""
from __future__ import annotations

import argparse
import cgi
import sys
import threading
import uuid
from datetime import date, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import templates as T
from .config import DB_PATH, PHOTO_DIR, ensure_dirs
from .db import connect, init_db
from .services import (BridalService, Conflict, DomainError, NotOwner,
                       NotFound)

_lock = threading.Lock()  # 串行化演示环境的写操作，配合 BEGIN IMMEDIATE 双保险


def _norm_dt(v: str) -> str:
    return (v or "").replace("T", " ").strip()


class App:
    def __init__(self):
        ensure_dirs()
        init_db(connect(DB_PATH))

    def service(self) -> BridalService:
        return BridalService(connect(DB_PATH))

    # ------------------------------------------------------------ helpers
    def _ctx(self, svc: BridalService, cookie: str) -> dict:
        c = SimpleCookie()
        c.load(cookie or "")
        cust = None
        if "cust" in c and c["cust"].value:
            cust = int(c["cust"].value)
        return {"cust": cust, "customers": svc.list_customers()}

    def _save_upload(self, fs: cgi.FieldStorage | None,
                     order_code: str) -> str | None:
        if fs is None or not getattr(fs, "filename", ""):
            return None
        name = Path(fs.filename).name.replace(" ", "_")
        dest_dir = PHOTO_DIR / "orders" / order_code / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{uuid.uuid4().hex[:8]}-{name}"
        with open(dest, "wb") as f:
            f.write(fs.file.read())
        return dest.relative_to(PHOTO_DIR).as_posix()

    def _save_order_photo(self, fs, order_id: int, svc: BridalService,
                          fallback_code: str = "TMP") -> str | None:
        code = fallback_code
        if order_id:
            code = svc.conn.execute(
                "SELECT code FROM outgoing_orders WHERE id=?",
                (order_id,)).fetchone()["code"]
        return self._save_upload(fs, code)


app = App()


# ----------------------------------------------------------------- handler
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "BridalRental/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- response
    def _send(self, status: int, body: str | bytes,
              content_type: str = "text/html; charset=utf-8",
              extra_headers: list[tuple[str, str]] | None = None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra_headers or []:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, set_cookie: str | None = None):
        extra = [("Location", location)]
        if set_cookie:
            extra.append(("Set-Cookie", set_cookie))
        self._send(303, b"", "text/plain", extra)

    def _error(self, ctx: dict, msg: str, back: str = "/gowns"):
        body = f'<h1>操作未完成</h1><div class="err">{T.h(msg)}</div>' \
               f'<p><a href="{back}">← 返回</a></p>'
        self._send(409, T.layout("操作未完成", "", body, **ctx))

    def _form(self) -> cgi.FieldStorage:
        return cgi.FieldStorage(
            fp=self.rfile, headers=self.headers,
            environ={"REQUEST_METHOD": "POST",
                     "CONTENT_TYPE": self.headers.get("Content-Type", "")})

    def _eff_customer(self, form: cgi.FieldStorage, ctx: dict) -> int:
        """客户隔离：若已切换为客户视角，只能操作自己的资源。"""
        if ctx["cust"] is not None:
            return ctx["cust"]
        v = form.getfirst("customer_id", "").strip()
        return int(v) if v else 0

    # ---- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        svc = app.service()
        ctx = app._ctx(svc, self.headers.get("Cookie", ""))
        try:
            if path in ("/", "/gowns"):
                self._send(200, T.gowns_page(svc.list_gowns(), **ctx))
            elif path == "/calendar":
                today = date.today()
                rows = svc.calendar(
                    (today - timedelta(days=7)).isoformat(),
                    (today + timedelta(days=21)).isoformat(),
                    customer_id=ctx["cust"])
                pg = T.calendar_page(
                    rows, svc.list_customers(), svc.list_gowns(),
                    svc.list_accessories(),
                    preselect_gown=int(qs["gown"][0]) if "gown" in qs else None,
                    **{k: v for k, v in ctx.items() if k != "customers"})
                self._send(200, pg)
            elif path == "/accessories":
                self._send(200, T.accessories_page(svc.list_accessories(), **ctx))
            elif path == "/orders":
                self._send(200, T.orders_page(
                    svc.list_orders(ctx["cust"]), **ctx))
            elif path == "/returns":
                self._send(200, T.orders_page(
                    svc.list_orders(ctx["cust"]), returns_mode=True, **ctx))
            elif path == "/orders/new":
                appt = svc.conn.execute(
                    """SELECT a.*, g.code gown_code, g.name gown_name,
                              c.name customer_name
                       FROM appointments a JOIN gowns g ON g.id=a.gown_id
                       JOIN customers c ON c.id=a.customer_id
                       WHERE a.id=?""",
                    (int(qs["appt_id"][0]),)).fetchone()
                if appt is None:
                    self._error(ctx, "预约不存在", "/calendar"); return
                self._send(200, T.new_order_page(
                    dict(appt), svc.list_accessories(), **ctx))
            elif path.startswith("/orders/"):
                oid = int(path.rsplit("/", 1)[-1])
                self._send(200, T.order_detail_page(
                    svc.order_detail(oid, customer_id=ctx["cust"]), **ctx))
            elif path == "/deposits":
                self._send(200, T.deposits_page(
                    svc.list_deposits(ctx["cust"]),
                    [dict(r) for r in svc.conn.execute(
                        "SELECT * FROM payment_ledger ORDER BY id DESC LIMIT 50")],
                    **ctx))
            elif path == "/switch-customer":
                v = qs.get("cust", [""])[0]
                cookie = f"cust={v}; Path=/; Max-Age=86400" if v else \
                         "cust=; Path=/; Max-Age=0"
                self._redirect("/gowns", cookie)
            elif path.startswith("/photos/"):
                self._serve_photo(path[len("/photos/"):])
            else:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
        except NotOwner as e:
            self._error(ctx, f"客户隔离拦截：{e}", "/gowns")
        except (NotFound, KeyError, ValueError) as e:
            self._error(ctx, f"资源不存在或参数错误：{e}")
        except DomainError as e:
            self._error(ctx, str(e))
        finally:
            svc.conn.close()

    def _serve_photo(self, rel: str):
        target = (PHOTO_DIR / rel).resolve()
        if not str(target).startswith(str(PHOTO_DIR.resolve())) or \
                not target.is_file():
            self._send(404, "photo not found", "text/plain"); return
        ctype = {".svg": "image/svg+xml", ".png": "image/png",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif"}.get(
                     target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # ---- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        form = self._form()
        svc = app.service()
        ctx = app._ctx(svc, self.headers.get("Cookie", ""))
        back = self.headers.get("Referer", "/gowns")
        try:
            with _lock:
                self._route_post(svc, form, path, ctx)
            self._redirect(back)
        except NotOwner as e:
            self._error(ctx, f"客户隔离拦截：{e}", back)
        except Conflict as e:
            self._error(ctx, f"业务冲突：{e}", back)
        except DomainError as e:
            self._error(ctx, str(e), back)
        except (NotFound, KeyError, ValueError) as e:
            self._error(ctx, f"参数错误或资源不存在：{e}", back)
        finally:
            svc.conn.close()

    def _route_post(self, svc: BridalService, form: cgi.FieldStorage,
                    path: str, ctx: dict) -> None:
        f = form.getfirst
        # ---------- 预约
        if path == "/api/appointments":
            cid = int(f("customer_id"))
            if ctx["cust"] is not None:
                cid = ctx["cust"]
            acc = f("accessory_set_id", "").strip()
            svc.create_appointment(
                cid, int(f("gown_id")), f("size_label"),
                f("slot_date"), f("slot_start"), f("slot_end"),
                accessory_set_id=int(acc) if acc else None)
            return
        if path.startswith("/api/appointments/"):
            segs = path.strip("/").split("/")
            aid = int(segs[2]); action = segs[3]
            cid = self._eff_customer(form, ctx)
            if action == "arrive":
                svc.mark_arrived(aid, cid)
            elif action == "late-cancel":
                svc.late_cancel(aid, cid, int(f("late_minutes", "30")),
                                f("reason", "超过等候时限"))
            elif action == "swap":
                acc = f("to_accessory_set_id", "").strip()
                svc.swap_appointment(
                    aid, cid, int(f("to_gown_id")), f("to_size", "M"),
                    to_accessory_set_id=int(acc) if acc else None,
                    reason=f("reason", "临时换款"))
            else:
                raise DomainError("未知预约操作")
            return
        if path.startswith("/api/accessories/"):
            segs = path.strip("/").split("/")
            if segs[3] == "restock":
                svc.restock_accessory(int(segs[2]))
            return
        # ---------- 出店单
        if path == "/api/orders":
            self._create_order(svc, form, ctx)
            return
        if path.startswith("/api/orders/"):
            segs = path.strip("/").split("/")
            oid = int(segs[2]); action = segs[3]
            cid = self._eff_customer(form, ctx)
            if action == "items":
                item_id = int(segs[4])
                photo = app._save_order_photo(form["photo"] if "photo" in form else None,
                                               oid, svc)
                svc.set_item_result(oid, cid, item_id, f("result"),
                                    f("note", ""), photo_path=photo)
            elif action == "return-start":
                svc.start_return(oid, cid, _norm_dt(f("actual_return")))
            elif action == "confirm":
                svc.confirm_return(oid, cid)
            elif action == "cleaning":
                photo = app._save_order_photo(
                    form["photo"] if "photo" in form else None, oid, svc)
                svc.cleaning_qc(oid, f("result"), f("note", ""),
                                photo_path=photo)
            elif action == "deduct":
                svc.deduct_deposit(oid, cid, int(f("item_id")),
                                   int(f("photo_id")),
                                   int(round(float(f("amount_yuan")) * 100)),
                                   f("reason"))
            elif action == "settle":
                svc.settle_deposit(oid, cid)
            elif action == "reviews":
                svc.add_review(oid, cid, f("body"))
            else:
                raise DomainError("未知订单操作")
            return
        raise DomainError(f"未知路径 {path}")

    def _create_order(self, svc: BridalService, form: cgi.FieldStorage,
                      ctx: dict) -> None:
        f = form.getfirst
        cid = self._eff_customer(form, ctx)
        appt_id = int(f("appointment_id"))
        gown_id = int(f("gown_id"))
        acc_id = int(f("accessory_set_id"))
        labels = form.getlist("label")
        cats = form.getlist("category")
        notes = form.getlist("outgoing_note")
        items = [{"label": l, "category": c, "outgoing_note": n}
                 for l, c, n in zip(labels, cats, notes) if l.strip()]
        # 明细出店照片（表格中的同名文件域，按行顺序对应检查项 seq）；
        # 先落盘到统一上传目录，再一次性原子建单，避免半成品订单。
        file_items = [x for x in (form.list or [])
                      if x.name == "photo" and getattr(x, "filename", "")]
        outgoing_photos: dict[int, dict[str, str]] = {}
        for seq, fs in enumerate(file_items, start=1):
            if seq > len(items):
                break
            rel = app._save_upload(fs, "outgoing")
            if rel:
                outgoing_photos[seq] = {
                    "path": rel, "category": items[seq - 1]["category"],
                    "note": items[seq - 1]["outgoing_note"]}
        adjust_fs = next((x for x in (form.list or [])
                          if x.name == "adjust_photo"
                          and getattr(x, "filename", "")), None)
        adjust_path = app._save_upload(adjust_fs, "outgoing")
        svc.create_outgoing_order(
            cid, appt_id, gown_id, acc_id,
            size_adjust={"record": f("size_adjust", ""),
                         "photo": adjust_path or ""},
            planned_return=_norm_dt(f("planned_return")),
            items=items, outgoing_photos=outgoing_photos)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"婚纱礼服试穿与返店清点系统：http://{args.host}:{args.port}/gowns")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
