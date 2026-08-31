from __future__ import annotations

import sqlite3
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
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
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
              amount=excluded.amount
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
