from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .pipeline import sync_once, unlock_pending
from .report import summarize
from .store import attachments_with_status, connect, list_imports, load_all
from .web import DASHBOARD_HTML

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 16 * 1024


def _jsonable_summary(db_path: Path, month: str | None) -> dict[str, Any]:
    con = connect(db_path)
    try:
        txns = load_all(con)
    finally:
        con.close()
    summary = summarize(txns, month)
    months = sorted({(t.time or "")[:7] for t in txns if len(t.time or "") >= 7}, reverse=True)
    return {
        "month": summary["month"],
        "months": months,
        "count": summary["count"],
        "expense": summary["expense"],
        "income": summary["income"],
        "net": summary["net"],
        "transfer": summary["transfer"],
        "by_category": summary["by_category"],
        "by_day": summary["by_day"],
    }


def _transactions(db_path: Path, month: str | None, limit: int, offset: int) -> dict[str, Any]:
    con = connect(db_path)
    try:
        where = ""
        params: list[Any] = []
        if month:
            where = "WHERE substr(time, 1, 7) = ?"
            params.append(month)
        total = int(con.execute(f"SELECT COUNT(*) FROM transactions {where}", params).fetchone()[0])
        rows = con.execute(
            f"""
            SELECT id, time, platform, direction, amount, counterparty, description,
                   method, status, category, raw_type
            FROM transactions
            {where}
            ORDER BY time DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}
    finally:
        con.close()


def _imports(db_path: Path, limit: int) -> list[dict[str, Any]]:
    con = connect(db_path)
    try:
        rows = list_imports(con, limit=limit)
    finally:
        con.close()
    return [
        {
            "message_id": r["message_id"],
            "subject": r["subject"],
            "received_at": r["received_at"],
            "status": r["status"],
            "error": r["error"],
            "attachment_count": r["attachment_count"],
        }
        for r in rows
    ]


def _pending(db_path: Path) -> list[dict[str, Any]]:
    con = connect(db_path)
    try:
        rows = attachments_with_status(con, "waiting_password", "error")
    finally:
        con.close()
    return [
        {
            "sha256": r["sha256"],
            "filename": r["filename"],
            "platform": r["platform"],
            "status": r["status"],
            "error": r["error"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


class LedgerApiServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], db_path: Path, token: str, cfg: dict):
        super().__init__(address, LedgerApiHandler)
        self.db_path = db_path
        self.api_token = token
        self.cfg = cfg
        self.action_lock = threading.Lock()


class LedgerApiHandler(BaseHTTPRequestHandler):
    server: LedgerApiServer
    server_version = "LedgerBoxAPI/0.3"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[api] {self.address_string()} - {fmt % args}")

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = self.server.api_token
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return False
        return hmac.compare_digest(auth[len(prefix) :], expected)

    @staticmethod
    def _int_arg(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int((query.get(name) or [str(default)])[0])
        except ValueError:
            value = default
        return max(minimum, min(value, maximum))

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ValueError("invalid_content_length") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("request_too_large")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json_object_required")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_html(DASHBOARD_HTML)
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "ledgerbox"})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        query = parse_qs(parsed.query)
        month = (query.get("month") or [None])[0]
        try:
            if parsed.path == "/api/summary":
                self._send_json(200, {"ok": True, "data": _jsonable_summary(self.server.db_path, month)})
                return
            if parsed.path == "/api/transactions":
                limit = self._int_arg(query, "limit", 200, 1, 500)
                offset = self._int_arg(query, "offset", 0, 0, 1_000_000)
                self._send_json(200, {"ok": True, "data": _transactions(self.server.db_path, month, limit, offset)})
                return
            if parsed.path == "/api/imports":
                limit = self._int_arg(query, "limit", 50, 1, 200)
                self._send_json(200, {"ok": True, "data": _imports(self.server.db_path, limit)})
                return
            if parsed.path == "/api/pending":
                self._send_json(200, {"ok": True, "data": _pending(self.server.db_path)})
                return
        except Exception as exc:
            print(f"[api] request failed for {parsed.path}: {type(exc).__name__}: {exc}")
            self._send_json(500, {"ok": False, "error": "internal_error"})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        if not self.server.action_lock.acquire(blocking=False):
            self._send_json(409, {"ok": False, "error": "another_action_is_running"})
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/sync":
                result = sync_once(self.server.cfg, db_path=self.server.db_path)
                result.pop("report", None)
                self._send_json(200, {"ok": True, "data": result})
                return
            if parsed.path == "/api/unlock":
                digest = str(payload.get("sha256") or "").strip()
                password = str(payload.get("password") or "")
                if len(digest) < 8:
                    self._send_json(400, {"ok": False, "error": "sha256_prefix_too_short"})
                    return
                result = unlock_pending(self.server.cfg, digest, password, db_path=self.server.db_path)
                result.pop("report", None)
                self._send_json(200, {"ok": True, "data": result})
                return
        except LookupError as exc:
            self._send_json(404, {"ok": False, "error": str(exc)})
            return
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            print(f"[api] action failed for {parsed.path}: {type(exc).__name__}: {exc}")
            self._send_json(500, {"ok": False, "error": "internal_error"})
            return
        finally:
            self.server.action_lock.release()
        self._send_json(404, {"ok": False, "error": "not_found"})


def serve_api(cfg: dict, db_path: Path, host: str | None = None, port: int | None = None) -> None:
    api_cfg = cfg.get("api") if isinstance(cfg.get("api"), dict) else {}
    bind_host = host or str(api_cfg.get("host") or "127.0.0.1")
    bind_port = port or int(api_cfg.get("port") or 8765)
    token = str(api_cfg.get("token") or "")
    if bind_host not in LOOPBACK_HOSTS and not token:
        raise SystemExit("Dashboard/API 监听非本机地址时必须配置 api.token，避免公开暴露个人账本。")
    server = LedgerApiServer((bind_host, bind_port), db_path, token, cfg)
    print(f"LedgerBox Dashboard: http://{bind_host}:{bind_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
