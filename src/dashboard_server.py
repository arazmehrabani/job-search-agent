from __future__ import annotations

import json
import re
import secrets
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .db import Database
from .dashboard import build_dashboard

_ALLOWED_DECISIONS = {"APPLY", "SAVE", "SKIP", "APPLIED", "INTERVIEW", "REJECTED", "OFFER", "CLEAR"}
_FP_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
_MAX_BODY = 8192
_MAX_REASON = 1000


def validate_feedback_payload(data) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    fp = data.get("fingerprint")
    decision = data.get("decision")
    reason = data.get("reason", "")
    if not isinstance(fp, str) or not _FP_RE.fullmatch(fp):
        raise ValueError("Invalid job fingerprint")
    if not isinstance(decision, str) or decision.strip().upper() not in _ALLOWED_DECISIONS:
        raise ValueError("Unsupported feedback decision")
    if not isinstance(reason, str):
        raise ValueError("Feedback reason must be a string")
    reason = reason.strip()
    if len(reason) > _MAX_REASON:
        raise ValueError(f"Feedback reason must be <= {_MAX_REASON} characters")
    return fp, decision.strip().upper(), reason


def serve_dashboard(db_path: str = "output/job_agent.sqlite3", port: int = 8765, open_browser: bool = True):
    feedback_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json_error(self, code: int, message: str):
            self._send(code, json.dumps({"ok": False, "error": message}).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            db = Database(db_path)
            try:
                path = build_dashboard(db, feedback_token=feedback_token)
                body = Path(path).read_bytes()
            finally:
                db.close()
            self._send(200, body, "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/api/feedback":
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            if not secrets.compare_digest(self.headers.get("X-Job-Agent-Token", ""), feedback_token):
                self._json_error(403, "Invalid feedback session token")
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._json_error(415, "Content-Type must be application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json_error(400, "Invalid Content-Length")
                return
            if length <= 0 or length > _MAX_BODY:
                self._json_error(413, f"Feedback body must be 1-{_MAX_BODY} bytes")
                return
            try:
                data = json.loads(self.rfile.read(length))
            except Exception:
                self._json_error(400, "Invalid JSON")
                return
            try:
                fp, decision, reason = validate_feedback_payload(data)
            except ValueError as exc:
                self._json_error(400, str(exc))
                return

            db = Database(db_path)
            try:
                if not db.job_exists(fp):
                    self._json_error(404, "Job not found")
                    return
                db.record_feedback(fp, decision.strip().upper(), reason)
            except Exception as exc:
                self._json_error(400, str(exc)[:500])
                return
            finally:
                db.close()
            self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json; charset=utf-8")

        def log_message(self, fmt, *args):
            return

    url = f"http://127.0.0.1:{int(port)}/"
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    print(f"Interactive dashboard: {url}")
    print("Feedback endpoint is session-token protected and bound to localhost only.")
    print("Stop with Ctrl+C / VS Code Stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard server stopped.")
    finally:
        server.server_close()
