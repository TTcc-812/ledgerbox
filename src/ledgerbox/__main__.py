from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .classify import classify
from .config import ROOT, load_config
from .mail import fetch_bills
from .parsers import parse_file
from .report import render_markdown, summarize
from .store import connect, load_all, upsert
from .transfers import mark_transfers
from .unzip import extract_archive

INBOX = ROOT / "inbox"
DATA = ROOT / "data"
DB = DATA / "ledger.db"


def _passwords(cfg: dict) -> dict[str, str]:
    return dict(cfg.get("zip_passwords") or {})


def cmd_fetch(cfg: dict) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    files = fetch_bills(cfg, INBOX)
    print(f"拉取 {len(files)} 个附件到 inbox/")
    pwds = _passwords(cfg)
    for f in list(INBOX.glob("*.zip")):
        platform = "wechat"
        name = f.name.lower()
        if "ali" in name or "支付宝" in f.name:
            platform = "alipay"
        elif "cmb" in name or "招商" in f.name:
            platform = "cmb"
        password = pwds.get(platform) or getpass.getpass(f"{f.name} 解压密码: ")
        extracted = extract_archive(f, INBOX / "extracted", password)
        print("解压:", ", ".join(p.name for p in extracted))


def _import_paths(paths: list[Path], cfg: dict) -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    txns = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            continue
        if p.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
            continue
        txns.extend(parse_file(p))
    rules = cfg.get("classify") if isinstance(cfg.get("classify"), dict) else None
    keywords = (cfg.get("transfers") or {}).get("keywords")
    window = int((cfg.get("transfers") or {}).get("window_hours") or 48)
    mark_transfers(txns, keywords=keywords, window_hours=window)
    classify(txns, rules=rules)
    con = connect(DB)
    n = upsert(con, txns)
    con.close()
    print(f"写入 {n} 条（含更新）→ {DB}")
    return n


def cmd_import(cfg: dict, extra: list[str]) -> None:
    paths: list[Path] = []
    if extra:
        paths = [Path(x) for x in extra]
    else:
        for folder in (INBOX, INBOX / "extracted"):
            if folder.exists():
                paths.extend(folder.glob("*"))
    paths = [p for p in paths if p.is_file()]
    if not paths:
        raise SystemExit("没有可导入的文件。把账单放到 inbox/ 或传入路径。")
    _import_paths(paths, cfg)


def cmd_report(cfg: dict, month: str | None) -> None:
    if not DB.exists():
        raise SystemExit("还没有账本，先 import。")
    con = connect(DB)
    txns = load_all(con)
    con.close()
    summary = summarize(txns, month)
    text = render_markdown(summary)
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"report-{summary['month']}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"已写入 {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledgerbox", description="微信/支付宝/招行账单归集")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="从邮箱拉取附件")
    p_imp = sub.add_parser("import", help="解析并入库")
    p_imp.add_argument("files", nargs="*")
    p_rep = sub.add_parser("report", help="生成月报")
    p_rep.add_argument("--month", help="YYYY-MM")
    args = parser.parse_args()
    cfg = load_config()
    if args.cmd == "fetch":
        cmd_fetch(cfg)
    elif args.cmd == "import":
        cmd_import(cfg, args.files)
    elif args.cmd == "report":
        cmd_report(cfg, args.month)


if __name__ == "__main__":
    main()
