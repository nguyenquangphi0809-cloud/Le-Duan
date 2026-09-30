import json
import tempfile
import unittest
from pathlib import Path

from automaton51.ledger import InsufficientFunds, Ledger, LedgerError, ProtectedAccount
from automaton51.money import D


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "ledger.jsonl"
        self.t = 1_000_000.0
        self.ledger = Ledger(self.path, clock=lambda: self.t)

    def test_deposit_charge_revenue(self):
        self.ledger.deposit("100")
        self.ledger.charge("2.5", "inference", "think")
        self.ledger.revenue("10", "store", "sale")
        self.assertEqual(self.ledger.balance("operating"), D("107.5"))
        t = self.ledger.totals()
        self.assertEqual(t["revenue"], D("10"))
        self.assertEqual(t["operating_costs"], D("2.5"))
        self.assertEqual(t["inference_costs"], D("2.5"))

    def test_no_debt(self):
        self.ledger.deposit("1")
        with self.assertRaises(InsufficientFunds):
            self.ledger.charge("1.5", "server", "vps")
        self.assertEqual(self.ledger.balance("operating"), D("1"))

    def test_owner_fund_is_protected(self):
        self.ledger.deposit("10")
        self.ledger.revenue("100", "job", "gig")
        self.ledger.split("100", "51", "49")
        self.assertEqual(self.ledger.balance("owner"), D("51"))
        self.assertEqual(self.ledger.balance("growth"), D("49"))
        with self.assertRaises(ProtectedAccount):
            self.ledger.growth_spend("5", "inference", "not allowed")
        self.ledger.growth_spend("5", "marketing", "ads")
        self.assertEqual(self.ledger.balance("growth"), D("44"))
        with self.assertRaises(InsufficientFunds):
            self.ledger.payout("60")
        self.ledger.payout("51")
        self.assertEqual(self.ledger.balance("owner"), D("0"))

    def test_split_must_balance(self):
        self.ledger.deposit("10")
        self.ledger.revenue("10", "store")
        with self.assertRaises(LedgerError):
            self.ledger.split("10", "6", "5")

    def test_rescue_moves_growth_to_operating(self):
        self.ledger.deposit("1")
        self.ledger.revenue("100", "job")
        self.ledger.split("100", "51", "49")
        self.ledger.rescue("2")
        self.assertEqual(self.ledger.balance("growth"), D("47"))
        self.assertEqual(self.ledger.balance("operating"), D("3"))

    def test_hash_chain_detects_tampering(self):
        self.ledger.deposit("10")
        self.ledger.charge("1", "server", "x")
        ok, _ = self.ledger.verify_chain()
        self.assertTrue(ok)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[1])
        row["amount"] = "-0.000001"  # sửa chi phí cho nhỏ đi
        lines[1] = json.dumps(row, ensure_ascii=False, sort_keys=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tampered = Ledger(self.path)
        ok, why = tampered.verify_chain()
        self.assertFalse(ok)
        self.assertIn("hash", why)

    def test_other_process_appends_are_picked_up(self):
        self.ledger.deposit("10")
        other = Ledger(self.path, clock=lambda: self.t)
        other.deposit("5", memo="CLI fund")
        self.assertEqual(self.ledger.balance("operating"), D("10"))
        self.ledger.reload()
        self.assertEqual(self.ledger.balance("operating"), D("15"))
        # ghi tiếp từ instance đầu vẫn nối chuỗi băm đúng
        self.ledger.charge("1", "tool", "x")
        ok, why = Ledger(self.path).verify_chain()
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
