from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledgerbox.parsers import Txn
from ledgerbox.store import (
    attachments_with_status,
    connect,
    record_attachment,
    record_mail,
    seen_attachment_hashes,
    seen_message_ids,
)
from ledgerbox.transfers import mark_transfers


class TransferConfigTests(unittest.TestCase):
    def test_configured_keyword_participates_in_pairing(self) -> None:
        txns = [
            Txn(
                id="a",
                time="2026-08-31 10:00:00",
                platform="cmb",
                direction="支出",
                amount=100.0,
                counterparty="自定义钱包",
                description="充值",
                method="",
                status="成功",
                category="",
                raw_type="充值",
            ),
            Txn(
                id="b",
                time="2026-08-31 10:01:00",
                platform="wechat",
                direction="收入",
                amount=100.0,
                counterparty="自定义钱包",
                description="转入",
                method="",
                status="成功",
                category="",
                raw_type="转入",
            ),
        ]

        mark_transfers(txns, keywords=["自定义钱包"], window_hours=48)

        self.assertEqual([t.direction for t in txns], ["内部转移", "内部转移"])
        self.assertEqual([t.category for t in txns], ["内部转移", "内部转移"])


class ImportStateTests(unittest.TestCase):
    def test_mail_and_attachment_are_deduplicated(self) -> None:
        with TemporaryDirectory() as temp:
            con = connect(Path(temp) / "ledger.db")
            record_mail(
                con,
                message_id="<bill-1@example.com>",
                imap_uid="42",
                sender="service@example.com",
                subject="账单",
                received_at="2026-08-31",
                status="fetched",
            )
            record_attachment(
                con,
                sha256="abc123",
                message_id="<bill-1@example.com>",
                filename="bill.zip",
                path="inbox/bill.zip",
                platform="wechat",
                status="waiting_password",
            )

            self.assertIn("<bill-1@example.com>", seen_message_ids(con))
            self.assertIn("abc123", seen_attachment_hashes(con))
            rows = attachments_with_status(con, "waiting_password")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["filename"], "bill.zip")
            con.close()


if __name__ == "__main__":
    unittest.main()
