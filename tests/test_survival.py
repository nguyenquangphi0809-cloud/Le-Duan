import unittest

from automaton51.money import D
from automaton51.survival import SurvivalMonitor, Tier, tier_for_balance


class KV(dict):
    def get_(self, k, d=None):
        return self.get(k, d)

    def set_(self, k, v):
        self[k] = v


class SurvivalTests(unittest.TestCase):
    def make(self, grace=3600):
        kv = KV()
        return SurvivalMonitor("5", "1", grace, kv.get_, kv.set_), kv

    def test_tiers(self):
        self.assertEqual(tier_for_balance(D("10"), D("5"), D("1")), Tier.NORMAL)
        self.assertEqual(tier_for_balance(D("5"), D("5"), D("1")), Tier.LOW)
        self.assertEqual(tier_for_balance(D("1"), D("5"), D("1")), Tier.CRITICAL)
        self.assertEqual(tier_for_balance(D("0"), D("5"), D("1")), Tier.CRITICAL)

    def test_death_after_grace(self):
        m, kv = self.make(grace=3600)
        s = m.evaluate(D("0"), 1000.0)
        self.assertEqual(s.tier, Tier.CRITICAL)
        self.assertEqual(kv["zero_since"], 1000.0)
        s = m.evaluate(D("0"), 1000.0 + 3599)
        self.assertEqual(s.tier, Tier.CRITICAL)
        self.assertAlmostEqual(s.seconds_to_death, 1.0)
        s = m.evaluate(D("0"), 1000.0 + 3600)
        self.assertEqual(s.tier, Tier.DEAD)
        self.assertTrue(s.changed)
        # chết là vĩnh viễn (cho tới khi chủ hồi sinh)
        s = m.evaluate(D("100"), 1000.0 + 9999)
        self.assertEqual(s.tier, Tier.DEAD)

    def test_funding_before_grace_resets(self):
        m, kv = self.make(grace=3600)
        m.evaluate(D("0"), 1000.0)
        s = m.evaluate(D("3"), 2000.0)
        self.assertEqual(s.tier, Tier.LOW)
        self.assertIsNone(kv.get("zero_since"))
        s = m.evaluate(D("0"), 3000.0)
        self.assertEqual(kv["zero_since"], 3000.0)


if __name__ == "__main__":
    unittest.main()
