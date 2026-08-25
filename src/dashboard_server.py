from __future__ import annotations
import json
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .db import Database
from .dashboard import build_dashboard


def serve_dashboard(db_path: str = "output/job_agent.sqlite3", port: int = 8765, open_browser: bool = True):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str):
            self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self._send(404, b"Not found", "text/plain; charset=utf-8"); return
            db = Database(db_path)
            try:
                path = build_dashboard(db)
                body = Path(path).read_bytes()
            finally:
                db.close()
            self._send(200, body, "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/api/feedback":
                self._send(404, b"Not found", "text/plain; charset=utf-8"); return
            try:
                n = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(n) or b"{}")
                fp = str(data.get("fingerprint", "")); decision = str(data.get("decision", "")); reason = str(data.get("reason", ""))
                db = Database(db_path)
                try:
                    db.record_feedback(fp, decision, reason)
                finally:
                    db.close()
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            except Exception as exc:
                self._send(400, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")

        def log_message(self, fmt, *args):
            return

    url = f"http://127.0.0.1:{int(port)}/"
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    print(f"Interactive dashboard: {url}")
    print("Stop with Ctrl+C / VS Code Stop.")
    if open_browser:
        try: webbrowser.open(url)
        except Exception: pass
    try: server.serve_forever()
    except KeyboardInterrupt: print("Dashboard server stopped.")
    finally: server.server_close()
