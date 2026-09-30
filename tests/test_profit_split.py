import random
import tempfile
import unittest
from pathlib import Path

from automaton51.constitution import GROWTH_SHARE, OWNER_SHARE
from automaton51.ledger import Ledger
from automaton51.money import D, floor6
from automaton51.profit_split import distributable_profit, settle, split_amounts


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(Path(tempfile.mkdtemp()) / "ledger.jsonl", clock=lambda: 1.0)

    def test_shares_are_51_49(self):
        self.assertEqual(OWNER_SHARE + GROWTH_SHARE, D("1"))
        self.assertEqual(OWNER_SHARE, D("0.51"))

    def test_basic_split_and_capital_untouched(self):
        self.ledger.deposit("100")
        self.ledger.charge("20", "inference", "think")
        self.ledger.revenue("50", "job", "gig")
        s = settle(self.ledger)
        self.assertIsNotNone(s)
        self.assertEqual(s.distributable, D("30"))
        self.assertEqual(s.owner_amount, D("15.3"))
        self.assertEqual(s.growth_amount, D("14.7"))
        self.assertEqual(self.ledger.balance("operating"), D("100"))  # vốn mồi còn nguyên
        self.assertIsNone(settle(self.ledger))  # không chia hai lần

    def test_losses_carry_forward(self):
        self.ledger.deposit("100")
        self.ledger.charge("20", "inference")
        self.ledger.revenue("50", "job")
        settle(self.ledger)
        self.ledger.charge("10", "server")
        self.assertIsNone(settle(self.ledger))  # đang lỗ 10 -> không chia
        self.assertEqual(distributable_profit(self.ledger), D("-10"))
        self.ledger.revenue("30", "store")
        s = settle(self.ledger)
        self.assertEqual(s.distributable, D("20"))
        self.assertEqual(s.owner_amount, D("10.2"))
        self.assertEqual(s.growth_amount, D("9.8"))

    def test_growth_spend_does_not_reduce_owner_profit(self):
        self.ledger.deposit("10")
        self.ledger.revenue("100", "job")
        settle(self.ledger)
        self.ledger.growth_spend("20", "replication", "child")
        self.ledger.revenue("10", "store")
        s = settle(self.ledger)
        self.assertEqual(s.owner_amount, D("5.1"))

    def test_owner_gets_rounding_remainder(self):
        rng = random.Random(1)
        for _ in range(500):
            d = D(rng.uniform(0.000001, 999.0))
            owner, growth = split_amounts(d)
            self.assertEqual(owner + growth, d)
            self.assertGreaterEqual(owner, floor6(d * OWNER_SHARE))
            self.assertLessEqual(growth, d * GROWTH_SHARE)
        owner, growth = split_amounts(D("0.000003"))
        self.assertEqual(growth, D("0.000001"))
        self.assertEqual(owner, D("0.000002"))

    def test_capped_by_operating_balance(self):
        self.ledger.deposit("10")
        self.ledger.revenue("50", "job")
        self.ledger.withdraw("55")  # chủ rút vốn trước khi chia
        s = settle(self.ledger)
        self.assertEqual(s.distributable, D("5"))
        self.assertEqual(self.ledger.balance("operating"), D("0"))
        self.assertEqual(distributable_profit(self.ledger), D("45"))  # phần còn lại chờ doanh thu/tiền về


if __name__ == "__main__":
    unittest.main()
