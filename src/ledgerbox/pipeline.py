from __future__ import annotations

from pathlib import Path

from .classify import classify
from .config import ROOT
from .mail import MailAttachment, fetch_bills
from .parsers import parse_file
from .report import render_markdown, summarize
from .store import (
    attachments_with_status,
    connect,
    load_all,
    record_attachment,
    record_mail,
    seen_attachment_hashes,
    seen_message_ids,
    set_attachment_status,
    upsert,
)
from .transfers import mark_transfers
from .unzip import UnsafeArchive, extract_archive

INBOX = ROOT / "inbox"
DATA = ROOT / "data"
DB = DATA / "ledger.db"
EXTRACTED = INBOX / "extracted"


def passwords(cfg: dict) -> dict[str, str]:
    return {str(k): str(v) for k, v in dict(cfg.get("zip_passwords") or {}).items() if v}


def platform_from_name(name: str) -> str:
    lower = name.lower()
    if "ali" in lower or "支付宝" in name:
        return "alipay"
    if "cmb" in lower or "招商" in name or "招行" in name:
        return "cmb"
    return "wechat"


def import_paths(paths: list[Path], cfg: dict, db_path: Path = DB) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    txns = []
    for path in paths:
        if path.suffix.lower() not in {".csv", ".xlsx"}:
            continue
        txns.extend(parse_file(path))
    if not txns:
        return 0

    rules = cfg.get("classify") if isinstance(cfg.get("classify"), dict) else None
    keywords = (cfg.get("transfers") or {}).get("keywords")
    window = int((cfg.get("transfers") or {}).get("window_hours") or 48)
    mark_transfers(txns, keywords=keywords, window_hours=window)
    classify(txns, rules=rules)

    con = connect(db_path)
    try:
        return upsert(con, txns)
    finally:
        con.close()


def record_fetch(con, attachments: list[MailAttachment], mails: list[dict]) -> None:
    by_message: dict[str, int] = {}
    for item in attachments:
        by_message[item.message_id] = by_message.get(item.message_id, 0) + 1
        record_attachment(
            con,
            sha256=item.sha256,
            message_id=item.message_id,
            filename=item.path.name,
            path=str(item.path),
            platform=platform_from_name(item.path.name),
            status="fetched",
        )

    for mail in mails:
        message_id = str(mail["message_id"])
        status = str(mail.get("status") or "fetched")
        if status == "duplicate":
            continue
        if by_message.get(message_id, 0) == 0:
            status = "processed"
        record_mail(
            con,
            message_id=message_id,
            imap_uid=str(mail.get("imap_uid") or ""),
            sender=str(mail.get("sender") or ""),
            subject=str(mail.get("subject") or ""),
            received_at=str(mail.get("received_at") or ""),
            status=status,
        )


def fetch_new(cfg: dict, con) -> list[MailAttachment]:
    INBOX.mkdir(parents=True, exist_ok=True)
    attachments, mails = fetch_bills(
        cfg,
        INBOX,
        seen_messages=seen_message_ids(con),
        seen_hashes=seen_attachment_hashes(con),
    )
    record_fetch(con, attachments, mails)
    return attachments


def process_attachment(
    con,
    row: dict,
    cfg: dict,
    *,
    password_override: str | None = None,
    db_path: Path = DB,
) -> int:
    path = Path(str(row["path"]))
    digest = str(row["sha256"])
    if not path.exists():
        set_attachment_status(con, digest, "error", error="附件文件不存在")
        return 0

    if path.suffix.lower() == ".zip":
        platform = str(row.get("platform") or platform_from_name(path.name))
        password = password_override or passwords(cfg).get(platform)
        if not password:
            set_attachment_status(con, digest, "waiting_password", error="等待解压密码", platform=platform)
            return 0
        try:
            paths = extract_archive(path, EXTRACTED / digest[:12], password)
        except UnsafeArchive as exc:
            set_attachment_status(con, digest, "error", error=str(exc), platform=platform)
            return 0
        except (RuntimeError, ValueError) as exc:
            set_attachment_status(con, digest, "waiting_password", error="解压失败，请确认密码", platform=platform)
            return 0
        imported = import_paths(paths, cfg, db_path=db_path)
        set_attachment_status(con, digest, "imported", error=None, platform=platform)
        return imported

    try:
        imported = import_paths([path], cfg, db_path=db_path)
    except Exception:
        set_attachment_status(con, digest, "error", error="解析失败")
        return 0
    set_attachment_status(con, digest, "imported" if imported else "empty", error=None)
    return imported


def refresh_mail_statuses(con) -> None:
    rows = con.execute(
        """
        SELECT m.message_id,
               SUM(CASE WHEN a.status IN ('fetched', 'waiting_password') THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN a.status = 'error' THEN 1 ELSE 0 END) AS errors,
               COUNT(a.sha256) AS total
        FROM mail_imports m
        LEFT JOIN attachments a ON a.message_id = m.message_id
        GROUP BY m.message_id
        """
    ).fetchall()
    for row in rows:
        if int(row["pending"] or 0) > 0:
            waiting = con.execute(
                "SELECT 1 FROM attachments WHERE message_id=? AND status='waiting_password' LIMIT 1",
                (row["message_id"],),
            ).fetchone()
            status = "waiting_password" if waiting else "fetched"
        elif int(row["errors"] or 0) > 0:
            status = "error"
        elif int(row["total"] or 0) > 0:
            status = "processed"
        else:
            continue
        con.execute(
            """
            UPDATE mail_imports
            SET status=?, updated_at=datetime('now'),
                processed_at=CASE WHEN ?='processed' THEN datetime('now') ELSE processed_at END
            WHERE message_id=?
            """,
            (status, status, row["message_id"]),
        )
    con.commit()


def write_report(con, month: str | None = None, data_dir: Path = DATA) -> Path:
    txns = load_all(con)
    summary = summarize(txns, month)
    text = render_markdown(summary)
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / f"report-{summary['month']}.md"
    out.write_text(text, encoding="utf-8")
    return out


def sync_once(cfg: dict, db_path: Path = DB) -> dict:
    con = connect(db_path)
    try:
        attachments = fetch_new(cfg, con)
        imported = 0
        for row in attachments_with_status(con, "fetched"):
            imported += process_attachment(con, row, cfg, db_path=db_path)
        refresh_mail_statuses(con)
        report = write_report(con)
        waiting = len(attachments_with_status(con, "waiting_password"))
        errors = len(attachments_with_status(con, "error"))
        return {
            "new_attachments": len(attachments),
            "imported": imported,
            "waiting_password": waiting,
            "errors": errors,
            "report": str(report),
        }
    finally:
        con.close()


def unlock_pending(cfg: dict, digest: str, password: str, db_path: Path = DB) -> dict:
    if not password:
        raise ValueError("密码不能为空")
    con = connect(db_path)
    try:
        matches = [
            row
            for row in attachments_with_status(con, "waiting_password")
            if str(row["sha256"]).startswith(digest)
        ]
        if not matches:
            raise LookupError("没有找到对应的待解压附件")
        if len(matches) > 1:
            raise ValueError("哈希前缀匹配到多个附件，请提供更长的哈希")
        row = matches[0]
        imported = process_attachment(
            con,
            row,
            cfg,
            password_override=password,
            db_path=db_path,
        )
        refresh_mail_statuses(con)
        current = con.execute(
            "SELECT status, error FROM attachments WHERE sha256=?",
            (row["sha256"],),
        ).fetchone()
        report = write_report(con)
        return {
            "sha256": row["sha256"],
            "status": current["status"] if current else "unknown",
            "error": current["error"] if current else None,
            "imported": imported,
            "report": str(report),
        }
    finally:
        con.close()
