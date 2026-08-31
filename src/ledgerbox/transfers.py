from __future__ import annotations

import re
from datetime import datetime, timedelta

from .parsers import Txn

PLATFORM_PAYEE = re.compile(r"支付宝|微信支付|微信零钱|零钱通|余额宝|财付通")
TRANSFER_TYPE = re.compile(r"转账|充值|提现|转入|转出")


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None


def is_transfer_shaped(txn: Txn) -> bool:
    payee = f"{txn.counterparty} {txn.description}"
    typed = bool(TRANSFER_TYPE.search(f"{txn.raw_type} {txn.description}"))
    return bool(PLATFORM_PAYEE.search(payee) and typed)


def mark_transfers(txns: list[Txn], keywords: list[str] | None = None, window_hours: int = 48) -> list[Txn]:
    del keywords  # pairing only; keywords kept for call-site compatibility
    window = timedelta(hours=window_hours)
    used: set[str] = set()
    pool = [t for t in txns if t.direction in ("支出", "收入") and is_transfer_shaped(t)]
    for a in pool:
        if a.id in used:
            continue
        da = _parse_dt(a.time)
        if not da:
            continue
        for b in pool:
            if a.id == b.id or b.id in used:
                continue
            if a.platform == b.platform or a.direction == b.direction:
                continue
            if abs(a.amount - b.amount) > 0.009:
                continue
            db = _parse_dt(b.time)
            if not db or abs(da - db) > window:
                continue
            a.direction = "内部转移"
            b.direction = "内部转移"
            a.category = "内部转移"
            b.category = "内部转移"
            used.add(a.id)
            used.add(b.id)
            break
    return txns
