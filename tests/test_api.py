from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerbox.api import _imports, _jsonable_summary, _pending, _transactions
from ledgerbox.parsers import Txn
from ledgerbox.store import connect, record_attachment, record_mail, upsert
from ledgerbox.web import DASHBOARD_HTML


class ApiDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "ledger.db"
        con = connect(self.db)
        upsert(
            con,
            [
                Txn("wx-1", "2026-08-10 09:00:00", "wechat", "支出", 12.5, "早餐店", "早餐", "零钱", "成功", "餐饮", "商户消费"),
                Txn("ali-1", "2026-08-11 12:00:00", "alipay", "收入", 100.0, "朋友", "转账", "余额", "成功", "收入", "转账红包"),
                Txn("cmb-1", "2026-07-11 12:00:00", "cmb", "支出", 50.0, "超市", "购物", "招商银行", "成功", "购物", "消费"),
            ],
        )
        record_mail(
            con,
            message_id="<mail-1@example>",
            imap_uid="123",
            sender="service@example.com",
            subject="微信账单",
            received_at="2026-08-12T10:00:00+00:00",
            status="waiting_password",
        )
        record_attachment(
            con,
            sha256="a" * 64,
            message_id="<mail-1@example>",
            filename="微信账单.zip",
            path="/tmp/微信账单.zip",
            platform="wechat",
            status="waiting_password",
            error="等待解压密码",
        )
        con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_summary_is_month_scoped_and_lists_months(self) -> None:
        data = _jsonable_summary(self.db, "2026-08")
        self.assertEqual(data["month"], "2026-08")
        self.assertEqual(data["expense"], 12.5)
        self.assertEqual(data["income"], 100.0)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["months"], ["2026-08", "2026-07"])

    def test_transactions_support_month_and_pagination(self) -> None:
        page = _transactions(self.db, "2026-08", limit=1, offset=0)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["id"], "ali-1")

    def test_imports_omit_sender_and_pending_omit_local_path(self) -> None:
        imports = _imports(self.db, 10)
        self.assertEqual(len(imports), 1)
        self.assertNotIn("sender", imports[0])
        pending = _pending(self.db)
        self.assertEqual(len(pending), 1)
        self.assertNotIn("path", pending[0])
        self.assertEqual(pending[0]["status"], "waiting_password")

    def test_dashboard_contains_real_api_workflow(self) -> None:
        self.assertIn("账单匣", DASHBOARD_HTML)
        self.assertIn("/api/summary", DASHBOARD_HTML)
        self.assertIn("/api/transactions", DASHBOARD_HTML)
        self.assertIn("/api/sync", DASHBOARD_HTML)
        self.assertIn("/api/unlock", DASHBOARD_HTML)
        self.assertIn("sessionStorage", DASHBOARD_HTML)
        self.assertNotIn("localStorage", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
