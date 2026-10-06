"""หน้าจอภาพห้องเทรด แสดงข้อมูลจริงจากโปรแกรม run_live.py

  python dashboard.py                     เปิดดูในเครื่องตัวเอง  http://localhost:8765
  python dashboard.py --remote --password รหัสสั่งการ --view-password รหัสดูอย่างเดียว
                                          เปิดให้เครื่องอื่นเข้าได้ รหัสแรกสั่งการได้ รหัสที่สองดูได้อย่างเดียว

แดชบอร์ดอ่านข้อมูลจาก data_live/state.json และส่งคำสั่งโดยเขียนลง data_live/commands.txt
จึงเปิด/ปิดแดชบอร์ดได้ตลอดโดยไม่กระทบการเทรด
"""
import argparse
import hmac
import json
import os
import re
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED = re.compile(r"^(status|lineup|halt|unhalt|teachers|study|class|rows|meeting|autosave (on|off|profit on|profit off|\d{2,3}(\.\d+)?)|"
                     r"(pause|resume|jail|release|close|save|promote|demote) \d{1,2}|"
                     r"teach \d{1,2} \d{1,2}|(tteach|tthink) (10|[0-9])|target \d{1,6}(\.\d+)?|minwr \d{2}(\.\d+)?)$")


def make_handler(data_dir, password, view_password=""):
    state_path = os.path.join(data_dir, "state.json")
    strat_path = os.path.join(data_dir, "strategies.json")
    cmd_path = os.path.join(data_dir, "commands.txt")
    page = os.path.join(HERE, "dashboard", "index.html")
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _role(self):
            """admin = ดูและสั่งการได้, view = ดูอย่างเดียว, None = ไม่มีสิทธิ์"""
            if not password:
                return "admin"
            q = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            tok = self.headers.get("X-Token", "") or q
            if hmac.compare_digest(tok, password):
                return "admin"
            if view_password and hmac.compare_digest(tok, view_password):
                return "view"
            return None

        def _auth(self):
            return self._role() is not None

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if not self._auth():
                return self._send(401, "ต้องใส่รหัส: เปิดด้วยลิงก์ http://ที่อยู่:พอร์ต/?token=รหัส", "text/plain; charset=utf-8")
            if path in ("/", "/index.html"):
                with open(page, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/state":
                st = None
                for _ in range(3):
                    try:
                        with open(state_path, encoding="utf-8") as f:   # อ่านแล้วปิดไฟล์ทันที ไม่ให้ขวางการบันทึก
                            raw = f.read()
                        st = json.loads(raw)
                        break
                    except FileNotFoundError:
                        break
                    except (json.JSONDecodeError, PermissionError):
                        time.sleep(0.1)
                if st is None:
                    return self._send(200, json.dumps({"waiting": True}))
                try:
                    with open(strat_path, encoding="utf-8") as f:
                        st["strategies"] = json.load(f)[-30:]
                except (FileNotFoundError, json.JSONDecodeError):
                    st["strategies"] = []
                st["readonly"] = self._role() == "view"
                return self._send(200, json.dumps(st, ensure_ascii=False))
            if path == "/api/signals.csv":
                p = os.path.join(data_dir, "signals.csv")
                if not os.path.exists(p):
                    return self._send(404, "ยังไม่มีจุดแนะนำที่รู้ผล", "text/plain; charset=utf-8")
                with open(p, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="signals.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send(404, "{}")

        def do_POST(self):
            if urlparse(self.path).path != "/api/command":
                return self._send(404, "{}")
            if self._role() != "admin":
                return self._send(403, json.dumps({"ok": False, "msg": "โหมดดูอย่างเดียว สั่งการไม่ได้"}, ensure_ascii=False))
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 1000)
                cmd = json.loads(self.rfile.read(n) or b"{}").get("cmd", "").strip().lower()
            except (ValueError, json.JSONDecodeError):
                cmd = ""
            if not ALLOWED.match(cmd):
                return self._send(400, json.dumps({"ok": False, "msg": f"คำสั่งไม่ถูกต้อง: {cmd}"}, ensure_ascii=False))
            with lock:
                with open(cmd_path, "a", encoding="utf-8") as f:
                    f.write(cmd + "\n")
            self._send(200, json.dumps({"ok": True, "msg": "ส่งคำสั่งแล้ว"}, ensure_ascii=False))

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_live")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--remote", action="store_true", help="เปิดให้เครื่องอื่นเข้าได้ (ต้องมี --password)")
    ap.add_argument("--password", default="", help="รหัสสำหรับดูและสั่งการ")
    ap.add_argument("--view-password", default="", help="รหัสสำหรับดูอย่างเดียว (สั่งการไม่ได้)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if args.remote and len(args.password) < 8:
        raise SystemExit("ถ้าเปิดให้เครื่องอื่นเข้าได้ ต้องตั้ง --password อย่างน้อย 8 ตัวอักษร เพราะหน้านี้สั่งการบอทได้")
    if args.view_password and (len(args.view_password) < 8 or args.view_password == args.password):
        raise SystemExit("--view-password ต้องยาวอย่างน้อย 8 ตัวอักษร และต้องไม่ซ้ำกับ --password")
    os.makedirs(args.data, exist_ok=True)
    host = "0.0.0.0" if args.remote else "127.0.0.1"
    srv = ThreadingHTTPServer((host, args.port), make_handler(args.data, args.password, args.view_password))
    url = f"http://localhost:{args.port}/" + (f"?token={args.password}" if args.password else "")
    print(f"แดชบอร์ดพร้อมแล้ว เปิดเบราว์เซอร์ที่ {url}")
    if args.remote:
        ip = "<IP ของเครื่องนี้>"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.connect(("8.8.8.8", 80))
                ip = sk.getsockname()[0]
        except OSError:
            pass
        print(f"เครื่องอื่นในวง LAN เดียวกัน (สั่งการได้):   http://{ip}:{args.port}/?token={args.password}")
        if args.view_password:
            print(f"เครื่องอื่นในวง LAN เดียวกัน (ดูอย่างเดียว): http://{ip}:{args.port}/?token={args.view_password}")
        print(f"ถ้าเครื่องอื่นเปิดไม่ได้ ให้เปิดพอร์ต {args.port} ใน Windows Firewall (ดู README ข้อ 5)")
    print("กด Ctrl+C เพื่อปิดแดชบอร์ด (การเทรดยังทำงานต่อ)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
