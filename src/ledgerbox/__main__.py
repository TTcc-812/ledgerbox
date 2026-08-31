from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from .classify import classify
from .config import ROOT, load_config
from .mail import MailAttachment, fetch_bills
from .parsers import parse_file
from .report import render_markdown, summarize
from .store import (
    attachments_with_status,
    connect,
    list_imports,
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


def _passwords(cfg: dict) -> dict[str, str]:
    return {str(k): str(v) for k, v in dict(cfg.get("zip_passwords") or {}).items() if v}


def _platform_from_name(name: str) -> str:
    lower = name.lower()
    if "ali" in lower or "支付宝" in name:
        return "alipay"
    if "cmb" in lower or "招商" in name or "招行" in name:
        return "cmb"
    return "wechat"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _import_paths(paths: list[Path], cfg: dict) -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    txns = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            continue
        if p.suffix.lower() not in {".csv", ".xlsx"}:
            continue
        txns.extend(parse_file(p))
    if not txns:
        return 0
    rules = cfg.get("classify") if isinstance(cfg.get("classify"), dict) else None
    keywords = (cfg.get("transfers") or {}).get("keywords")
    window = int((cfg.get("transfers") or {}).get("window_hours") or 48)
    mark_transfers(txns, keywords=keywords, window_hours=window)
    classify(txns, rules=rules)
    con = connect(DB)
    n = upsert(con, txns)
    con.close()
    return n


def _record_fetch(con, attachments: list[MailAttachment], mails: list[dict]) -> None:
    by_message: dict[str, int] = {}
    for item in attachments:
        by_message[item.message_id] = by_message.get(item.message_id, 0) + 1
        record_attachment(
            con,
            sha256=item.sha256,
            message_id=item.message_id,
            filename=item.path.name,
            path=str(item.path),
            platform=_platform_from_name(item.path.name),
            status="fetched",
        )
    for mail in mails:
        message_id = str(mail["message_id"])
        status = str(mail.get("status") or "fetched")
        if status != "duplicate" and by_message.get(message_id, 0) == 0:
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


def _fetch(cfg: dict, con) -> list[MailAttachment]:
    INBOX.mkdir(parents=True, exist_ok=True)
    attachments, mails = fetch_bills(
        cfg,
        INBOX,
        seen_messages=seen_message_ids(con),
        seen_hashes=seen_attachment_hashes(con),
    )
    _record_fetch(con, attachments, mails)
    return attachments


def _process_attachment(con, row: dict, cfg: dict, password_override: str | None = None) -> int:
    path = Path(str(row["path"]))
    digest = str(row["sha256"])
    if not path.exists():
        set_attachment_status(con, digest, "error", error="附件文件不存在")
        return 0

    if path.suffix.lower() == ".zip":
        platform = str(row.get("platform") or _platform_from_name(path.name))
        password = password_override or _passwords(cfg).get(platform)
        if not password:
            set_attachment_status(con, digest, "waiting_password", error="等待解压密码", platform=platform)
            return 0
        try:
            paths = extract_archive(path, EXTRACTED / digest[:12], password)
        except UnsafeArchive as exc:
            set_attachment_status(con, digest, "error", error=str(exc), platform=platform)
            return 0
        except (RuntimeError, ValueError) as exc:
            set_attachment_status(con, digest, "waiting_password", error=f"解压失败，请确认密码：{exc}", platform=platform)
            return 0
        n = _import_paths(paths, cfg)
        set_attachment_status(con, digest, "imported", error=None, platform=platform)
        return n

    try:
        n = _import_paths([path], cfg)
    except Exception as exc:
        set_attachment_status(con, digest, "error", error=f"解析失败：{exc}")
        return 0
    set_attachment_status(con, digest, "imported" if n else "empty", error=None)
    return n


def _refresh_mail_statuses(con) -> None:
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
            status = "waiting_password" if con.execute(
                "SELECT 1 FROM attachments WHERE message_id=? AND status='waiting_password' LIMIT 1",
                (row["message_id"],),
            ).fetchone() else "fetched"
        elif int(row["errors"] or 0) > 0:
            status = "error"
        elif int(row["total"] or 0) > 0:
            status = "processed"
        else:
            continue
        con.execute(
            "UPDATE mail_imports SET status=?, updated_at=datetime('now'), processed_at=CASE WHEN ?='processed' THEN datetime('now') ELSE processed_at END WHERE message_id=?",
            (status, status, row["message_id"]),
        )
    con.commit()


def _write_report(con, month: str | None = None) -> Path:
    txns = load_all(con)
    summary = summarize(txns, month)
    text = render_markdown(summary)
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"report-{summary['month']}.md"
    out.write_text(text, encoding="utf-8")
    return out


def cmd_fetch(cfg: dict) -> None:
    con = connect(DB)
    attachments = _fetch(cfg, con)
    con.close()
    print(f"新增拉取 {len(attachments)} 个附件到 inbox/")


def cmd_sync(cfg: dict) -> None:
    con = connect(DB)
    attachments = _fetch(cfg, con)
    imported = 0
    for row in attachments_with_status(con, "fetched"):
        imported += _process_attachment(con, row, cfg)
    _refresh_mail_statuses(con)
    report = _write_report(con)
    waiting = len(attachments_with_status(con, "waiting_password"))
    con.close()
    print(f"同步完成：新增附件 {len(attachments)}，写入/更新流水 {imported}，等待密码 {waiting}")
    print(f"月报：{report}")


def cmd_unlock(cfg: dict, digest: str, password: str) -> None:
    con = connect(DB)
    matches = [r for r in attachments_with_status(con, "waiting_password", "error") if str(r["sha256"]).startswith(digest)]
    if not matches:
        con.close()
        raise SystemExit("没有找到对应的待解压附件。可先运行 ledgerbox status。")
    if len(matches) > 1:
        con.close()
        raise SystemExit("哈希前缀匹配到多个附件，请提供更长的哈希。")
    n = _process_attachment(con, matches[0], cfg, password_override=password)
    _refresh_mail_statuses(con)
    report = _write_report(con)
    con.close()
    print(f"解锁完成，写入/更新流水 {n} 条；月报：{report}")


def cmd_status() -> None:
    con = connect(DB)
    waiting = attachments_with_status(con, "waiting_password", "error")
    imports = list_imports(con, limit=20)
    con.close()
    if waiting:
        print("待处理附件：")
        for row in waiting:
            print(f"- {str(row['sha256'])[:12]}  {row['status']}  {row['filename']}  {row.get('error') or ''}")
    else:
        print("没有等待密码或失败的附件。")
    if imports:
        print("\n最近邮件：")
        for row in imports[:10]:
            print(f"- {row['status']:16} {row['subject']} ({row['attachment_count']} attachments)")


def cmd_import(cfg: dict, extra: list[str]) -> None:
    paths: list[Path] = []
    if extra:
        paths = [Path(x) for x in extra]
    else:
        for folder in (INBOX, EXTRACTED):
            if folder.exists():
                paths.extend(folder.rglob("*"))
    paths = [p for p in paths if p.is_file()]
    if not paths:
        raise SystemExit("没有可导入的文件。把账单放到 inbox/ 或传入路径。")
    n = _import_paths(paths, cfg)
    print(f"写入/更新 {n} 条 → {DB}")


def cmd_report(month: str | None) -> None:
    if not DB.exists():
        raise SystemExit("还没有账本，先 import 或 sync。")
    con = connect(DB)
    out = _write_report(con, month)
    text = out.read_text(encoding="utf-8")
    con.close()
    print(text)
    print(f"已写入 {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledgerbox", description="微信/支付宝/招行账单归集")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="从邮箱拉取新附件，不导入")
    sub.add_parser("sync", help="拉取新邮件、解压、导入并生成月报")
    sub.add_parser("status", help="查看等待密码/失败附件与最近导入")
    p_unlock = sub.add_parser("unlock", help="为待解压账单提供密码并继续导入")
    p_unlock.add_argument("sha256", help="status 中显示的附件哈希前缀")
    p_unlock.add_argument("password", help="账单压缩包密码")
    p_imp = sub.add_parser("import", help="解析并入库")
    p_imp.add_argument("files", nargs="*")
    p_rep = sub.add_parser("report", help="生成月报")
    p_rep.add_argument("--month", help="YYYY-MM")
    args = parser.parse_args()
    cfg = load_config()
    if args.cmd == "fetch":
        cmd_fetch(cfg)
    elif args.cmd == "sync":
        cmd_sync(cfg)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "unlock":
        cmd_unlock(cfg, args.sha256, args.password)
    elif args.cmd == "import":
        cmd_import(cfg, args.files)
    elif args.cmd == "report":
        cmd_report(args.month)


if __name__ == "__main__":
    main()
