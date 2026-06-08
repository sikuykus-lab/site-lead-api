#!/usr/bin/env python3
"""
POST /api/site-lead — JSON {name, phone, email, t0, hp?} → сообщение в Telegram-группу (CRM-бот).
Защита: rate limit по IP, honeypot-поля, минимальная «зрелость» формы по t0 (мс с клиента).
Читает BOT_TOKEN и GROUP_ID из /opt/telegram-crm-bot/.env
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ENV_PATH = Path(os.environ.get("CRM_ENV_PATH", "/opt/telegram-crm-bot/.env"))
LISTEN = os.environ.get("SITE_LEAD_LISTEN", "127.0.0.1:8791")

ALLOW_ORIGINS = frozenset(
    {
        "http://YOUR_SERVER_HOST",
        "http://example.com",
        "http://www.example.com",
        "http://www.example.com",
        "http://www.www.example.com",
        "https://example.com",
        "https://www.example.com",
        "https://www.example.com",
        "https://www.www.example.com",
    }
)

_bot_token = ""
_group_id = 0

_RL_LOCK = threading.Lock()
_RL_IP: dict[str, deque[float]] = defaultdict(deque)
_RL_MAX = int(os.environ.get("SITE_LEAD_RL_MAX", "10"))  # заявок с одного IP
_RL_WINDOW = float(os.environ.get("SITE_LEAD_RL_WINDOW_SEC", "900"))  # окно, сек

# Honeypot: любое непустое значение → отбой
_HONEYPOT_KEYS = ("hp", "website", "url", "company", "address", "fax", "subject2")
_MIN_FORM_AGE_MS = float(os.environ.get("SITE_LEAD_MIN_FORM_MS", "2000"))
_MAX_FORM_AGE_MS = float(os.environ.get("SITE_LEAD_MAX_FORM_MS", str(86400000 * 3)))  # до 3 суток


def _load_env() -> None:
    global _bot_token, _group_id
    _bot_token = os.environ.get("BOT_TOKEN", "").strip()
    _group_id = int(os.environ.get("GROUP_ID", "0") or "0")
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "BOT_TOKEN" and v:
                _bot_token = v
            elif k == "GROUP_ID" and v:
                _group_id = int(v)


def _client_ip(handler: BaseHTTPRequestHandler) -> str:
    xff = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if xff:
        return xff[:80]
    return str(handler.client_address[0])[:80]


def _rate_allow(ip: str) -> bool:
    now = time.monotonic()
    with _RL_LOCK:
        dq = _RL_IP[ip]
        while dq and dq[0] < now - _RL_WINDOW:
            dq.popleft()
        if len(dq) >= _RL_MAX:
            return False
        dq.append(now)
    return True


def _esc_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _send_telegram(text: str) -> tuple[int, str]:
    if not _bot_token or not _group_id:
        return 500, "misconfigured"
    data = urllib.parse.urlencode(
        {
            "chat_id": str(_group_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    url = f"https://api.telegram.org/bot{_bot_token}/sendMessage"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return (200 if '"ok":true' in raw else 502), raw[:500]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:500]
    except OSError as e:
        return 502, str(e)[:500]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _cors_origin(self) -> str | None:
        o = (self.headers.get("Origin") or "").strip()
        if o in ALLOW_ORIGINS:
            return o
        ref = (self.headers.get("Referer") or "").strip()
        if ref:
            base = urlparse(ref)
            candidate = f"{base.scheme}://{base.netloc}"
            if candidate in ALLOW_ORIGINS:
                return candidate
        return None

    def _send(self, code: int, body: bytes, origin: str | None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/") != "/api/site-lead":
            self.send_response(404)
            self.end_headers()
            return
        origin = self._cors_origin()
        if not origin:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/") != "/api/site-lead":
            self.send_response(404)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        origin = self._cors_origin()
        if not origin:
            self._send(403, b'{"ok":false,"error":"origin"}', None)
            return
        ip = _client_ip(self)
        if not _rate_allow(ip):
            self._send(
                429,
                json.dumps({"ok": False, "error": "rate_limit"}, ensure_ascii=False).encode("utf-8"),
                origin,
            )
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > 32_768:
            self._send(400, b'{"ok":false,"error":"body"}', origin)
            return
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send(400, b'{"ok":false,"error":"json"}', origin)
            return
        if not isinstance(data, dict):
            self._send(400, b'{"ok":false,"error":"shape"}', origin)
            return
        for k in _HONEYPOT_KEYS:
            v = data.get(k)
            if v is not None and str(v).strip():
                self._send(400, b'{"ok":false,"error":"spam"}', origin)
                return
        t0 = data.get("t0")
        try:
            t0f = float(t0)
        except (TypeError, ValueError):
            self._send(400, b'{"ok":false,"error":"timing"}', origin)
            return
        age_ms = time.time() * 1000.0 - t0f
        if age_ms < _MIN_FORM_AGE_MS or age_ms > _MAX_FORM_AGE_MS:
            self._send(400, b'{"ok":false,"error":"timing"}', origin)
            return

        name = str(data.get("name", "")).strip()[:200]
        phone = str(data.get("phone", "")).strip()[:80]
        email = str(data.get("email", "")).strip()[:200]
        if len(name) < 2 or not phone or "@" not in email:
            self._send(400, b'{"ok":false,"error":"fields"}', origin)
            return
        text = (
            "📝 <b>Заявка с сайта</b>\n"
            f"Имя: {_esc_html(name)}\n"
            f"Телефон: {_esc_html(phone)}\n"
            f"E-mail: {_esc_html(email)}"
        )
        code, _detail = _send_telegram(text)
        if code != 200:
            self._send(
                502,
                json.dumps({"ok": False, "error": "telegram"}, ensure_ascii=False).encode(
                    "utf-8"
                ),
                origin,
            )
            return
        self._send(200, b'{"ok":true}', origin)


def main() -> None:
    _load_env()
    host, _, port_s = LISTEN.partition(":")
    port = int(port_s or "8791")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"site_lead_server listening on {host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
