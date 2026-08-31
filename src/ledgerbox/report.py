from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .parsers import Txn


def month_of(txn: Txn) -> str:
    return (txn.time or "")[:7]


def summarize(txns: list[Txn], month: str | None = None) -> dict:
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    rows = [t for t in txns if month_of(t) == month]
    expense = sum(t.amount for t in rows if t.direction == "支出")
    income = sum(t.amount for t in rows if t.direction == "收入")
    transfer = sum(t.amount for t in rows if t.direction == "内部转移")
    by_cat: dict[str, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)
    for t in rows:
        if t.direction == "支出":
            by_cat[t.category or "其他"] += t.amount
            by_day[t.time[:10]] += t.amount
    return {
        "month": month,
        "count": len(rows),
        "expense": round(expense, 2),
        "income": round(income, 2),
        "net": round(income - expense, 2),
        "transfer": round(transfer, 2),
        "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
        "by_day": dict(sorted(by_day.items())),
        "rows": rows,
    }


def render_markdown(summary: dict) -> str:
    lines = [
        f"# {summary['month']} 账单",
        "",
        f"- 支出 **{summary['expense']:.2f}**",
        f"- 收入 **{summary['income']:.2f}**",
        f"- 净额 **{summary['net']:.2f}**（内部转移 {summary['transfer']:.2f} 已排除）",
        f"- 笔数 {summary['count']}",
        "",
        "## 分类",
        "",
    ]
    for cat, amt in summary["by_category"].items():
        lines.append(f"- {cat}: {amt:.2f}")
    lines += ["", "## 明细", "", "| 时间 | 平台 | 方向 | 金额 | 对方 | 分类 |", "| --- | --- | --- | --- | --- | --- |"]
    for t in summary["rows"][:200]:
        lines.append(
            f"| {t.time} | {t.platform} | {t.direction} | {t.amount:.2f} | {t.counterparty} | {t.category} |"
        )
    return "\n".join(lines) + "\n"
