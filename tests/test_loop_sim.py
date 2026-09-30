import unittest

from automaton51.brain.simulated import SimulatedBrain
from automaton51.ledger import Ledger
from automaton51.loop import Automaton, VirtualClock
from automaton51.money import D, ZERO
from automaton51.profit_split import distributable_profit
from automaton51.replication import list_children
from automaton51.revenue import RevenueInbox
from automaton51.survival import Tier
from tests.helpers import make_state


class LoopSimTests(unittest.TestCase):
    def test_full_economy_runs_and_split_invariants_hold(self):
        state, cfg = make_state("20", sim_seed=7)
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, SimulatedBrain(seed=7), clock=clock, log=lambda m: None)
        rep = auto.run(max_ticks=200)
        t = auto.ledger.totals()
        self.assertGreater(t["inference_costs"], ZERO)
        self.assertGreater(t["server_costs"], ZERO)
        ok, why = auto.ledger.verify_chain()
        self.assertTrue(ok, why)
        self.assertTrue(state.status_path.exists())
        self.assertTrue(state.journal_path.exists())
        # bất biến 51/49
        self.assertEqual(t["distributed"], t["owner_received"] + t["growth_received"])
        if t["distributed"] > ZERO:
            self.assertGreaterEqual(t["owner_received"], t["distributed"] * D("0.51") - D("0.001"))
            self.assertGreater(t["revenue"], ZERO)
        # số dư không âm, quỹ chủ chỉ tăng
        for v in auto.ledger.balances().values():
            self.assertGreaterEqual(v, ZERO)
        self.assertEqual(auto.ledger.balance("owner"), t["owner_received"] - t["owner_paid_out"])

    def test_dies_without_money(self):
        state, cfg = make_state("0.02", dead_grace_seconds=3600, sim_tick_minutes=30)
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, None, clock=clock, log=lambda m: None)  # không có não: chỉ trừ tiền server
        rep = auto.run(max_ticks=100)
        self.assertTrue(rep.died)
        self.assertEqual(state.kv_get("survival_tier"), Tier.DEAD.value)
        self.assertTrue((state.root / "DEATH_CERTIFICATE.md").exists())
        self.assertFalse(auto.alive)
        self.assertEqual(auto.ledger.balance("operating"), ZERO)
        self.assertTrue(any(e.kind == "death" for e in auto.ledger.entries))

    def test_growth_fund_rescues_operating_wallet(self):
        state, cfg = make_state("1", growth_rescue_usd="2")
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, None, clock=clock, log=lambda m: None)
        auto.ledger.revenue("100", "job", "gig")
        auto.tick()  # chia: owner 51, growth 49; operating về lại vốn mồi = 1
        self.assertEqual(auto.ledger.balance("operating"), D("1"))
        auto.ledger.charge("0.6", "inference", "đốt")  # operating 0.4 < critical 1
        rep = auto.tick()
        self.assertEqual(auto.ledger.totals()["rescued"], D("2"))
        self.assertGreaterEqual(auto.ledger.balance("operating"), D("2"))
        self.assertEqual(auto.ledger.balance("growth"), D("47"))
        self.assertEqual(auto.ledger.balance("owner"), D("51"))  # quỹ chủ không bị đụng

    def test_manual_revenue_and_kill_switch(self):
        state, cfg = make_state("10")
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, SimulatedBrain(seed=3), clock=clock, log=lambda m: None)
        job = auto.catalog.add_job("Việc thật", "40", "mô tả", "web")
        RevenueInbox(state, clock=clock.now).append("40", source="manual", memo="khách trả", job_id=job["id"])
        state.kill_switch_path.write_text("STOP", encoding="utf-8")
        rep = auto.tick()
        self.assertTrue(rep.stopped)
        self.assertFalse(rep.turn_ran)
        self.assertEqual(auto.ledger.totals()["revenue"], D("40"))
        self.assertEqual(auto.catalog.get_job(job["id"])["status"], "paid")
        state.kill_switch_path.unlink()
        rep = auto.tick()
        self.assertTrue(rep.turn_ran)
        self.assertEqual(auto.ledger.balance("owner"), D("20.4"))  # 51% của 40 (chi phí server tick đầu ≈ 0)
        self.assertLessEqual(distributable_profit(auto.ledger), ZERO)

    def test_owner_message_reaches_turn_input(self):
        state, cfg = make_state("10")
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, SimulatedBrain(seed=3), clock=clock, log=lambda m: None)
        state.append_jsonl(state.owner_inbox_path, {"ts": clock.now(), "text": "Ưu tiên làm landing page cho tiệm hoa"})
        status = auto.monitor.evaluate(auto.ledger.balance("operating"), clock.now())
        text = auto._turn_input(status, clock.now(), auto._unread_owner_messages())
        self.assertIn("tiệm hoa", text)
        self.assertIn("51%", text)
        auto.tick()
        self.assertEqual(state.kv_get("owner_cursor"), 1)

    def test_daily_inference_cap_stops_thinking(self):
        state, cfg = make_state("50", daily_inference_cap_usd="0.01")
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, SimulatedBrain(seed=3), clock=clock, log=lambda m: None)
        auto.tick()
        state.kv_set("sleep_until", None)  # bỏ trạng thái ngủ để kiểm tra riêng trần chi phí
        rep = auto.tick()
        self.assertFalse(rep.turn_ran)
        self.assertTrue(any("trần" in e for e in rep.events), rep.events)

    def test_replication_from_growth_fund(self):
        state, cfg = make_state("5", replicate_min_growth_usd="10", child_seed_usd="5")
        clock = VirtualClock(start=1_700_000_000.0)
        auto = Automaton(state, cfg, None, clock=clock, log=lambda m: None)
        auto.ledger.revenue("100", "job")
        auto.tick()
        rec = auto._spawn_child("Con-1", D("5"), "Bán template email")
        self.assertEqual(auto.ledger.balance("growth"), D("44"))
        kids = list_children(state)
        self.assertEqual(len(kids), 1)
        child_ledger = Ledger(kids[0]["path"] + "/ledger.jsonl")
        self.assertEqual(child_ledger.balance("operating"), D("5"))
        self.assertEqual(auto.ledger.balance("owner"), D("51"))


if __name__ == "__main__":
    unittest.main()
