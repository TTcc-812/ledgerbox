from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .api import serve_api
from .config import load_config
from .pipeline import DB, EXTRACTED, INBOX, import_paths, sync_once, unlock_pending, write_report
from .store import attachments_with_status, connect, list_imports


def cmd_fetch(cfg: dict) -> None:
    from .pipeline import fetch_new

    con = connect(DB)
    try:
        attachments = fetch_new(cfg, con)
    finally:
        con.close()
    print(f"新增拉取 {len(attachments)} 个附件到 inbox/")


def cmd_sync(cfg: dict) -> None:
    result = sync_once(cfg)
    print(
        "同步完成："
        f"新增附件 {result['new_attachments']}，"
        f"写入/更新流水 {result['imported']}，"
        f"等待密码 {result['waiting_password']}，"
        f"失败 {result['errors']}"
    )
    print(f"月报：{result['report']}")


def cmd_unlock(cfg: dict, digest: str, password: str | None) -> None:
    secret = password or getpass.getpass("账单压缩包密码: ")
    try:
        result = unlock_pending(cfg, digest, secret)
    except (LookupError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"解锁结果：{result['status']}，"
        f"写入/更新流水 {result['imported']} 条；月报：{result['report']}"
    )
    if result.get("error"):
        print(f"提示：{result['error']}")


def cmd_status() -> None:
    con = connect(DB)
    try:
        waiting = attachments_with_status(con, "waiting_password", "error")
        imports = list_imports(con, limit=20)
    finally:
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
    n = import_paths(paths, cfg)
    print(f"写入/更新 {n} 条 → {DB}")


def cmd_report(month: str | None) -> None:
    if not DB.exists():
        raise SystemExit("还没有账本，先 import 或 sync。")
    con = connect(DB)
    try:
        out = write_report(con, month)
        text = out.read_text(encoding="utf-8")
    finally:
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
    p_unlock.add_argument("password", nargs="?", help="可省略；省略时安全提示输入，避免进入 shell history")

    p_imp = sub.add_parser("import", help="解析并入库")
    p_imp.add_argument("files", nargs="*")

    p_rep = sub.add_parser("report", help="生成月报")
    p_rep.add_argument("--month", help="YYYY-MM")

    p_api = sub.add_parser("api", help="启动 Dashboard + HTTP API，默认仅监听 127.0.0.1")
    p_api.add_argument("--host", help="覆盖 config.yaml 的 api.host")
    p_api.add_argument("--port", type=int, help="覆盖 config.yaml 的 api.port")

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
    elif args.cmd == "api":
        serve_api(cfg, DB, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
