from __future__ import annotations

import email
import imaplib
import re
import ssl
from email.header import decode_header
from pathlib import Path
from urllib.parse import urlparse

import urllib.request

MAX_ATTACHMENT = 20 * 1024 * 1024
ALLOWED_HOSTS = (
    "download.bill.weixin.qq.com",
    "tenpay.wechatpay.cn",
    "weixin.qq.com",
    "alipay.com",
    "mail.alipay.com",
    "cmbchina.com",
    "cmbimg.com",
)
SENDER_HINTS = {
    "wechat": ("wechatpay@tencent.com", "微信支付"),
    "alipay": ("service@mail.alipay.com", "支付宝"),
    "cmb": ("cmbchina.com", "招商银行", "招行"),
}


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def fetch_bills(cfg: dict, dest: Path) -> list[Path]:
    imap_cfg = cfg.get("imap") or {}
    user = imap_cfg.get("username") or ""
    password = imap_cfg.get("password") or ""
    if not user or not password:
        raise SystemExit("请在 config.yaml 填写 imap.username 与 imap.password（授权码）")

    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    ctx = ssl.create_default_context()
    host = imap_cfg.get("host") or "imap.qq.com"
    port = int(imap_cfg.get("port") or 993)
    folder = imap_cfg.get("folder") or "INBOX"

    with imaplib.IMAP4_SSL(host, port, ssl_context=ctx) as imap:
        imap.login(user, password)
        imap.select(folder, readonly=True)
        typ, data = imap.search(None, "ALL")
        if typ != "OK":
            return saved
        ids = data[0].split()[-40:]  # last 40 messages
        for msg_id in reversed(ids):
            typ, payload = imap.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not payload or not payload[0]:
                continue
            raw = payload[0][1]
            msg = email.message_from_bytes(raw)
            subject = _decode(msg.get("Subject"))
            sender = _decode(msg.get("From"))
            blob = f"{subject} {sender}".lower()
            if not any(
                k.lower() in blob
                for keys in SENDER_HINTS.values()
                for k in keys
            ):
                continue
            saved.extend(_save_parts(msg, dest))
    return saved


def _save_parts(msg: email.message.Message, dest: Path) -> list[Path]:
    out: list[Path] = []
    for part in msg.walk():
        filename = part.get_filename()
        name = _decode(filename) if filename else ""
        if name and name.lower().endswith((".zip", ".csv", ".xlsx", ".xls")):
            payload = part.get_payload(decode=True) or b""
            if len(payload) > MAX_ATTACHMENT:
                continue
            safe = Path(name).name
            if ".." in safe:
                continue
            path = dest / safe
            path.write_bytes(payload)
            out.append(path)
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            body = part.get_payload(decode=True) or b""
            text = body.decode(part.get_content_charset() or "utf-8", errors="replace")
            for url in re.findall(r"https://[^\s\"'<>]+", text):
                if not _host_ok(url):
                    continue
                if not any(x in url.lower() for x in ("bill", "download", "zip", "xlsx", "csv")):
                    continue
                path = _download(url, dest)
                if path:
                    out.append(path)
    return out


def _download(url: str, dest: Path) -> Path | None:
    req = urllib.request.Request(url, headers={"User-Agent": "LedgerBox/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            final = resp.geturl()
            if not _host_ok(final):
                return None
            data = resp.read(MAX_ATTACHMENT + 1)
            if len(data) > MAX_ATTACHMENT:
                return None
            name = Path(urlparse(final).path).name or "bill.bin"
            path = dest / Path(name).name
            path.write_bytes(data)
            return path
    except Exception:
        return None
