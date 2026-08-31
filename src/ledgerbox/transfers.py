from __future__ import annotations

import re
from datetime import datetime, timedelta

from .parsers import Txn

DEFAULT_PAYEE_KEYWORDS = ["支付宝", "微信支付", "微信零钱", "零钱通", "余额宝", "财付通", "招商银行", "招行", "储蓄卡", "信用卡"]
DEFAULT_TYPE_KEYWORDS = ["转账", "充值", "提现", "转入", "转出"]


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _matches_any(text: str, keywords: list[str]) -> bool:
    return any(k and k in text for k in keywords)


def is_transfer_shaped(txn: Txn, keywords: list[str] | None = None) -> bool:
    configured = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    payee_keywords = configured or DEFAULT_PAYEE_KEYWORDS
    type_keywords = DEFAULT_TYPE_KEYWORDS
    payee = f"{txn.counterparty} {txn.description}"
    typed_blob = f"{txn.raw_type} {txn.description}"
    return _matches_any(payee, payee_keywords) and _matches_any(typed_blob, type_keywords)


def mark_transfers(txns: list[Txn], keywords: list[str] | None = None, window_hours: int = 48) -> list[Txn]:
    window = timedelta(hours=window_hours)
    used: set[str] = set()
    pool = [t for t in txns if t.direction in ("支出", "收入") and is_transfer_shaped(t, keywords)]
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
