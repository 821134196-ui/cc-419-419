"""婚纱礼服试穿与返店清点系统 — HTTP 服务。

零依赖，使用 http.server。提供 JSON API、静态页面与照片文件服务。
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import core

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Handler(BaseHTTPRequestHandler):
    server_version = "Bridal/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ------------------------------------------------------------------
    # 响应工具
    # ------------------------------------------------------------------
    def _json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data=None, **kw):
        self._json({"ok": True, "data": data, **kw})

    def _err(self, msg: str, code: int = 400):
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise core.ServiceError("请求体不是有效 JSON")

    def _query(self) -> dict:
        qs = parse_qs(urlparse(self.path).query)
        return {k: v[0] for k, v in qs.items()}

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def do_GET(self):
        try:
            path = urlparse(self.path).path
            q = self._query()
            # 静态页面
            if path in ("/", "/index.html"):
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if path == "/app.js":
                return self._serve_static("app.js", "application/javascript; charset=utf-8")
            if path == "/style.css":
                return self._serve_static("style.css", "text/css; charset=utf-8")
            # 照片文件
            if path.startswith("/photos/"):
                return self._serve_photo(path[len("/photos/"):])
            # API
            if path == "/api/health":
                return self._ok({"status": "ok"})
            if path == "/api/gowns":
                return self._ok(core.list_gowns(q.get("status")))
            if path == "/api/gowns/%s" % self._id(path, r"^/api/gowns/(\d+)$"):
                return self._ok(core.get_gown(int(self._id(path, r"^/api/gowns/(\d+)$"))))
            if path == "/api/customers":
                return self._ok(core.list_customers())
            if path == "/api/accessory-sets":
                return self._ok(core.list_accessory_sets())
            if path == "/api/appointments":
                return self._ok(core.list_appointments(
                    date_from=q.get("from"), date_to=q.get("to"),
                    gown_id=int(q["gown_id"]) if q.get("gown_id") else None,
                    customer_id=int(q["customer_id"]) if q.get("customer_id") else None,
                    status=q.get("status"),
                ))
            if path == "/api/appointments/%s" % self._id(path, r"^/api/appointments/(\d+)$"):
                return self._ok(core.get_appointment(int(self._id(path, r"^/api/appointments/(\d+)$"))))
            if path == "/api/out-orders":
                return self._ok(core.list_out_orders(
                    status=q.get("status"),
                    customer_id=int(q["customer_id"]) if q.get("customer_id") else None,
                ))
            if path == "/api/out-orders/%s" % self._id(path, r"^/api/out-orders/(\d+)$"):
                return self._ok(core.get_out_order(int(self._id(path, r"^/api/out-orders/(\d+)$"))))
            if path == "/api/inspections":
                return self._ok(core.list_inspections(
                    customer_id=int(q["customer_id"]) if q.get("customer_id") else None,
                ))
            if path == "/api/inspections/%s" % self._id(path, r"^/api/inspections/(\d+)$"):
                return self._ok(core.get_inspection(int(self._id(path, r"^/api/inspections/(\d+)$"))))
            if path == "/api/cleaning":
                return self._ok(core.list_cleaning_records(
                    gown_id=int(q["gown_id"]) if q.get("gown_id") else None,
                    status=q.get("status"),
                ))
            if path == "/api/deposits":
                return self._ok(core.list_deposits(
                    customer_id=int(q["customer_id"]) if q.get("customer_id") else None,
                ))
            if path == "/api/deposits/%s" % self._id(path, r"^/api/deposits/(\d+)$"):
                return self._ok(core.get_deposit(int(self._id(path, r"^/api/deposits/(\d+)$"))))
            return self._err("Not Found", 404)
        except core.ServiceError as e:
            return self._err(e.message, e.code)
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._err("服务器内部错误: %s" % e, 500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            b = self._body()
            if path == "/api/customers":
                return self._ok(core.create_customer(
                    b["name"], b.get("phone", ""), b.get("note", ""), b.get("avatar", "")))
            if path == "/api/gowns":
                return self._ok(core.create_gown(
                    b["code"], b["name"], b.get("style", ""), b.get("color", ""),
                    b.get("size", ""), float(b.get("deposit_yuan", 0)),
                    b.get("photo", ""), b.get("note", "")))
            if path == "/api/accessory-sets":
                return self._ok(core.create_accessory_set(
                    b["code"], b["name"], b.get("items", []), b.get("note", "")))
            if path == "/api/appointments":
                return self._ok(core.create_appointment(
                    int(b["gown_id"]), int(b["customer_id"]),
                    b["start_time"], b["end_time"], b.get("note", "")))
            if path == "/api/appointments/%s/cancel" % self._id(path, r"^/api/appointments/(\d+)/cancel$"):
                return self._ok(core.cancel_appointment(
                    int(self._id(path, r"^/api/appointments/(\d+)/cancel$")),
                    late=bool(b.get("late", False))))
            if path == "/api/appointments/%s/checkin" % self._id(path, r"^/api/appointments/(\d+)/checkin$"):
                return self._ok(core.checkin_appointment(
                    int(self._id(path, r"^/api/appointments/(\d+)/checkin$"))))
            if path == "/api/appointments/%s/swap" % self._id(path, r"^/api/appointments/(\d+)/swap$"):
                return self._ok(core.swap_appointment_gown(
                    int(self._id(path, r"^/api/appointments/(\d+)/swap$")),
                    int(b["new_gown_id"])))
            if path == "/api/out-orders":
                return self._ok(core.create_out_order(
                    int(b["gown_id"]), int(b["customer_id"]),
                    b.get("accessory_set_id"), b.get("appointment_id"),
                    b.get("size_adjustments", ""), b.get("pre_stains", ""),
                    b.get("out_photos"), b.get("expected_return_time", ""), b.get("note", "")))
            if path == "/api/out-orders/%s/return" % self._id(path, r"^/api/out-orders/(\d+)/return$"):
                return self._ok(core.create_return_inspection(
                    int(self._id(path, r"^/api/out-orders/(\d+)/return$"))))
            if path == "/api/inspections/%s/items" % self._id(path, r"^/api/inspections/(\d+)/items$"):
                return self._ok(core.update_inspection_items(
                    int(self._id(path, r"^/api/inspections/(\d+)/items$")),
                    b.get("items", []), b.get("photos")))
            if path == "/api/inspections/%s/deductions" % self._id(path, r"^/api/inspections/(\d+)/deductions$"):
                return self._ok(core.add_inspection_deduction(
                    int(self._id(path, r"^/api/inspections/(\d+)/deductions$")),
                    b["item_key"], float(b["amount_yuan"]), b.get("reason", ""), b.get("photos")))
            if path == "/api/inspections/%s/confirm" % self._id(path, r"^/api/inspections/(\d+)/confirm$"):
                return self._ok(core.confirm_inspection(
                    int(self._id(path, r"^/api/inspections/(\d+)/confirm$"))))
            if path == "/api/inspections/%s/review" % self._id(path, r"^/api/inspections/(\d+)/review$"):
                return self._ok(core.add_inspection_review(
                    int(self._id(path, r"^/api/inspections/(\d+)/review$")), b.get("review", "")))
            if path == "/api/cleaning/%s" % self._id(path, r"^/api/cleaning/(\d+)$"):
                return self._ok(core.update_cleaning(
                    int(self._id(path, r"^/api/cleaning/(\d+)$")),
                    b["status"], b.get("note", "")))
            if path == "/api/photos":
                return self._ok(core.save_photo(b["data_url"], b.get("slot", "photo")))
            return self._err("Not Found", 404)
        except core.ServiceError as e:
            return self._err(e.message, e.code)
        except KeyError as e:
            return self._err("缺少参数: %s" % e, 400)
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._err("服务器内部错误: %s" % e, 500)

    def do_PATCH(self):
        try:
            path = urlparse(self.path).path
            b = self._body()
            if path == "/api/gowns/%s" % self._id(path, r"^/api/gowns/(\d+)$"):
                return self._ok(core.update_gown(
                    int(self._id(path, r"^/api/gowns/(\d+)$")), **b))
            return self._err("Not Found", 404)
        except core.ServiceError as e:
            return self._err(e.message, e.code)
        except Exception as e:
            return self._err("服务器内部错误: %s" % e, 500)

    # ------------------------------------------------------------------
    def _id(self, path: str, pattern: str) -> str:
        m = re.match(pattern, path)
        return m.group(1) if m else ""

    def _serve_static(self, name: str, ctype: str):
        fpath = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(fpath):
            return self._err("Not Found", 404)
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_photo(self, name: str):
        # 防目录穿越
        safe = os.path.basename(name)
        fpath = os.path.join(core.PHOTO_DIR, safe)
        if not os.path.isfile(fpath):
            return self._err("Not Found", 404)
        ext = os.path.splitext(safe)[1].lower()
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".svg": "image/svg+xml", ".webp": "image/webp"}.get(ext, "application/octet-stream")
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)


def main():
    core.init_db()
    host = os.environ.get("BRIDAL_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDAL_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"婚纱礼服试穿与返店清点系统已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
