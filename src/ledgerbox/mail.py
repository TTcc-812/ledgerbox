from __future__ import annotations

import email
import hashlib
import imaplib
import re
import ssl
from dataclasses import dataclass
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


@dataclass
class MailAttachment:
    path: Path
    sha256: str
    message_id: str
    imap_uid: str
    sender: str
    subject: str
    received_at: str


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_message_id(msg: email.message.Message, uid: str) -> str:
    raw = _decode(msg.get("Message-ID")).strip()
    return raw or f"imap:{uid}"


def fetch_bills(
    cfg: dict,
    dest: Path,
    *,
    seen_messages: set[str] | None = None,
    seen_hashes: set[str] | None = None,
) -> tuple[list[MailAttachment], list[dict]]:
    imap_cfg = cfg.get("imap") or {}
    user = imap_cfg.get("username") or ""
    password = imap_cfg.get("password") or ""
    if not user or not password:
        raise SystemExit("请在 config.yaml 填写 imap.username 与 imap.password（授权码）")

    seen_messages = seen_messages or set()
    seen_hashes = seen_hashes or set()
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[MailAttachment] = []
    mails: list[dict] = []
    ctx = ssl.create_default_context()
    host = imap_cfg.get("host") or "imap.qq.com"
    port = int(imap_cfg.get("port") or 993)
    folder = imap_cfg.get("folder") or "INBOX"
    lookback_days = max(1, int(imap_cfg.get("lookback_days") or 14))

    with imaplib.IMAP4_SSL(host, port, ssl_context=ctx) as imap:
        imap.login(user, password)
        imap.select(folder, readonly=True)
        from datetime import datetime, timedelta

        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        typ, data = imap.uid("search", None, "SINCE", since)
        if typ != "OK":
            return saved, mails
        ids = data[0].split()
        for uid_bytes in reversed(ids):
            uid = uid_bytes.decode("ascii", errors="ignore")
            typ, payload = imap.uid("fetch", uid, "(RFC822)")
            if typ != "OK" or not payload or not payload[0]:
                continue
            raw = payload[0][1]
            msg = email.message_from_bytes(raw)
            message_id = _safe_message_id(msg, uid)
            subject = _decode(msg.get("Subject"))
            sender = _decode(msg.get("From"))
            received_at = _decode(msg.get("Date"))
            blob = f"{subject} {sender}".lower()
            relevant = any(k.lower() in blob for keys in SENDER_HINTS.values() for k in keys)
            if not relevant:
                continue
            meta = {
                "message_id": message_id,
                "imap_uid": uid,
                "sender": sender,
                "subject": subject,
                "received_at": received_at,
                "status": "duplicate" if message_id in seen_messages else "fetched",
            }
            mails.append(meta)
            if message_id in seen_messages:
                continue
            parts = _save_parts(msg, dest, seen_hashes=seen_hashes)
            for path, digest in parts:
                saved.append(MailAttachment(path, digest, message_id, uid, sender, subject, received_at))
                seen_hashes.add(digest)
    return saved, mails


def _save_parts(
    msg: email.message.Message,
    dest: Path,
    *,
    seen_hashes: set[str],
) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for part in msg.walk():
        filename = part.get_filename()
        name = _decode(filename) if filename else ""
        if name and name.lower().endswith((".zip", ".csv", ".xlsx")):
            payload = part.get_payload(decode=True) or b""
            if not payload or len(payload) > MAX_ATTACHMENT:
                continue
            digest = _sha256(payload)
            if digest in seen_hashes:
                continue
            safe = Path(name).name
            if ".." in safe:
                continue
            path = _unique_path(dest, safe, digest)
            path.write_bytes(payload)
            out.append((path, digest))
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            body = part.get_payload(decode=True) or b""
            text = body.decode(part.get_content_charset() or "utf-8", errors="replace")
            for url in re.findall(r"https://[^\s\"'<>]+", text):
                if not _host_ok(url):
                    continue
                if not any(x in url.lower() for x in ("bill", "download", "zip", "xlsx", "csv")):
                    continue
                result = _download(url, dest, seen_hashes)
                if result:
                    out.append(result)
                    seen_hashes.add(result[1])
    return out


def _unique_path(dest: Path, name: str, digest: str) -> Path:
    path = dest / name
    if not path.exists():
        return path
    return dest / f"{path.stem}-{digest[:8]}{path.suffix}"


def _download(url: str, dest: Path, seen_hashes: set[str]) -> tuple[Path, str] | None:
    req = urllib.request.Request(url, headers={"User-Agent": "LedgerBox/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            final = resp.geturl()
            if not _host_ok(final):
                return None
            data = resp.read(MAX_ATTACHMENT + 1)
            if not data or len(data) > MAX_ATTACHMENT:
                return None
            digest = _sha256(data)
            if digest in seen_hashes:
                return None
            name = Path(urlparse(final).path).name or "bill.bin"
            suffix = Path(name).suffix.lower()
            if suffix not in {".zip", ".csv", ".xlsx"}:
                return None
            path = _unique_path(dest, Path(name).name, digest)
            path.write_bytes(data)
            return path, digest
    except Exception:
        return None
