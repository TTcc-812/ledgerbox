from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parsers import Txn

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  time TEXT NOT NULL,
  platform TEXT NOT NULL,
  direction TEXT NOT NULL,
  amount REAL NOT NULL,
  counterparty TEXT,
  description TEXT,
  method TEXT,
  status TEXT,
  category TEXT,
  raw_type TEXT
);

CREATE TABLE IF NOT EXISTS mail_imports (
  message_id TEXT PRIMARY KEY,
  imap_uid TEXT,
  sender TEXT,
  subject TEXT,
  received_at TEXT,
  status TEXT NOT NULL DEFAULT 'fetched',
  error TEXT,
  processed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
  sha256 TEXT PRIMARY KEY,
  message_id TEXT,
  filename TEXT NOT NULL,
  path TEXT NOT NULL,
  platform TEXT,
  status TEXT NOT NULL DEFAULT 'fetched',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attachments_status ON attachments(status);
CREATE INDEX IF NOT EXISTS idx_mail_imports_status ON mail_imports(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def upsert(con: sqlite3.Connection, txns: list[Txn]) -> int:
    n = 0
    for t in txns:
        con.execute(
            """
            INSERT INTO transactions
              (id, time, platform, direction, amount, counterparty, description, method, status, category, raw_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              direction=excluded.direction,
              category=excluded.category,
              amount=excluded.amount,
              counterparty=excluded.counterparty,
              description=excluded.description,
              method=excluded.method,
              status=excluded.status,
              raw_type=excluded.raw_type
            """,
            (
                t.id,
                t.time,
                t.platform,
                t.direction,
                t.amount,
                t.counterparty,
                t.description,
                t.method,
                t.status,
                t.category,
                t.raw_type,
            ),
        )
        n += 1
    con.commit()
    return n


def load_all(con: sqlite3.Connection) -> list[Txn]:
    rows = con.execute("SELECT * FROM transactions ORDER BY time DESC").fetchall()
    return [
        Txn(
            id=r["id"],
            time=r["time"],
            platform=r["platform"],
            direction=r["direction"],
            amount=float(r["amount"]),
            counterparty=r["counterparty"] or "",
            description=r["description"] or "",
            method=r["method"] or "",
            status=r["status"] or "",
            category=r["category"] or "",
            raw_type=r["raw_type"] or "",
        )
        for r in rows
    ]


def seen_message_ids(con: sqlite3.Connection) -> set[str]:
    return {str(r[0]) for r in con.execute("SELECT message_id FROM mail_imports")}


def seen_attachment_hashes(con: sqlite3.Connection) -> set[str]:
    return {str(r[0]) for r in con.execute("SELECT sha256 FROM attachments")}


def record_mail(
    con: sqlite3.Connection,
    *,
    message_id: str,
    imap_uid: str,
    sender: str,
    subject: str,
    received_at: str,
    status: str,
    error: str | None = None,
) -> None:
    now = _now()
    con.execute(
        """
        INSERT INTO mail_imports
          (message_id, imap_uid, sender, subject, received_at, status, error, processed_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
          status=excluded.status,
          error=excluded.error,
          processed_at=excluded.processed_at,
          updated_at=excluded.updated_at
        """,
        (
            message_id,
            imap_uid,
            sender,
            subject,
            received_at,
            status,
            error,
            now if status in {"processed", "duplicate", "ignored", "error"} else None,
            now,
            now,
        ),
    )
    con.commit()


def record_attachment(
    con: sqlite3.Connection,
    *,
    sha256: str,
    message_id: str,
    filename: str,
    path: str,
    platform: str | None,
    status: str = "fetched",
    error: str | None = None,
) -> None:
    now = _now()
    con.execute(
        """
        INSERT INTO attachments
          (sha256, message_id, filename, path, platform, status, error, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sha256) DO UPDATE SET
          status=excluded.status,
          error=excluded.error,
          platform=COALESCE(excluded.platform, attachments.platform),
          updated_at=excluded.updated_at
        """,
        (sha256, message_id, filename, path, platform, status, error, now, now),
    )
    con.commit()


def set_attachment_status(
    con: sqlite3.Connection,
    sha256: str,
    status: str,
    *,
    error: str | None = None,
    path: str | None = None,
    platform: str | None = None,
) -> None:
    now = _now()
    con.execute(
        """
        UPDATE attachments
        SET status=?, error=?, path=COALESCE(?, path), platform=COALESCE(?, platform), updated_at=?
        WHERE sha256=?
        """,
        (status, error, path, platform, now, sha256),
    )
    con.commit()


def attachments_with_status(con: sqlite3.Connection, *statuses: str) -> list[dict]:
    if not statuses:
        return []
    marks = ",".join("?" for _ in statuses)
    rows = con.execute(
        f"SELECT * FROM attachments WHERE status IN ({marks}) ORDER BY created_at",
        statuses,
    ).fetchall()
    return [dict(r) for r in rows]


def list_imports(con: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = con.execute(
        """
        SELECT m.message_id, m.sender, m.subject, m.received_at, m.status, m.error,
               COUNT(a.sha256) AS attachment_count
        FROM mail_imports m
        LEFT JOIN attachments a ON a.message_id = m.message_id
        GROUP BY m.message_id
        ORDER BY COALESCE(m.received_at, m.created_at) DESC
        LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    ).fetchall()
    return [dict(r) for r in rows]
