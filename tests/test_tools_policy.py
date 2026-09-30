import unittest

from automaton51 import tools as toolbox
from automaton51.catalog import Catalog
from automaton51.ledger import Ledger
from automaton51.money import D
from automaton51.revenue import RevenueInbox, SimulatedMarket
from tests.helpers import make_state


class ToolPolicyTests(unittest.TestCase):
    def setUp(self):
        self.state, self.cfg = make_state("20")
        self.t = 1_700_000_000.0
        self.ledger = Ledger(self.state.ledger_path, clock=lambda: self.t, lock_path=self.state.lock_path)
        self.ctx = toolbox.AgentContext(
            state=self.state, cfg=self.cfg, ledger=self.ledger, catalog=Catalog(self.state, clock=lambda: self.t),
            inbox=RevenueInbox(self.state, clock=lambda: self.t), clock=lambda: self.t,
            market=SimulatedMarket(1, clock=lambda: self.t), tier="normal", born_at=self.t,
        )

    def test_strict_schemas(self):
        for spec in toolbox.api_tools():
            schema = spec["input_schema"]
            self.assertFalse(schema["additionalProperties"], spec["name"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]), spec["name"])
            self.assertTrue(spec["strict"])

    def test_path_traversal_blocked(self):
        out, err = toolbox.execute(self.ctx, "write_product", {
            "name": "x", "kind": "tool", "description": "mô tả đủ dài", "price_usd": 10, "job_id": "",
            "files": [{"path": "../../etc/passwd", "content": "x"}]})
        self.assertTrue(err)
        self.assertIn("không an toàn", out)
        out, err = toolbox.execute(self.ctx, "write_product", {
            "name": "x", "kind": "tool", "description": "mô tả đủ dài", "price_usd": 10, "job_id": "",
            "files": [{"path": "/tmp/evil", "content": "x"}]})
        self.assertTrue(err)

    def test_price_bounds_and_files_required(self):
        out, err = toolbox.execute(self.ctx, "write_product", {
            "name": "x", "kind": "tool", "description": "mô tả", "price_usd": 0.1, "job_id": "", "files": [{"path": "a", "content": "b"}]})
        self.assertTrue(err)
        out, err = toolbox.execute(self.ctx, "write_product", {
            "name": "x", "kind": "tool", "description": "mô tả", "price_usd": 10, "job_id": "", "files": []})
        self.assertTrue(err)

    def test_product_lifecycle(self):
        out, err = toolbox.execute(self.ctx, "write_product", {
            "name": "Landing page", "kind": "web", "description": "Trang giới thiệu 1 trang", "price_usd": 29, "job_id": "",
            "files": [{"path": "index.html", "content": "<h1>hi</h1>"}, {"path": "README.md", "content": "hướng dẫn"}]})
        self.assertFalse(err, out)
        self.assertTrue((self.state.products_dir / "landing-page" / "index.html").exists())
        out, err = toolbox.execute(self.ctx, "publish_listing", {"product_id": "P0001", "price_usd": 39, "channels": ["storefront"]})
        self.assertFalse(err, out)
        self.assertEqual(self.ctx.catalog.get_product("P0001")["status"], "listed")
        self.assertEqual(D(self.ctx.catalog.get_product("P0001")["price"]), D("39"))

    def test_replicate_requires_growth_fund(self):
        self.ctx.spawn_child = lambda name, seed, genesis: {"name": name, "path": "x"}
        out, err = toolbox.execute(self.ctx, "replicate", {"name": "Con", "seed_usd": 5, "genesis_prompt": "kiếm tiền"})
        self.assertTrue(err)
        self.assertIn("Quỹ mở rộng", out)

    def test_expansion_forbidden_when_critical(self):
        self.ctx.tier = "critical"
        self.ctx.spawn_child = lambda name, seed, genesis: {"name": name, "path": "x"}
        out, err = toolbox.execute(self.ctx, "replicate", {"name": "Con", "seed_usd": 5, "genesis_prompt": "kiếm tiền"})
        self.assertTrue(err)
        self.assertIn("critical", out)

    def test_tool_call_cap(self):
        self.ctx.turn_tool_calls = self.cfg.max_tool_calls_per_turn
        out, err = toolbox.execute(self.ctx, "check_wallet", {})
        self.assertTrue(err)

    def test_funding_request_cooldown(self):
        out, err = toolbox.execute(self.ctx, "request_funding", {"amount_usd": 10, "reason": "cần vốn"})
        self.assertFalse(err, out)
        out, err = toolbox.execute(self.ctx, "request_funding", {"amount_usd": 10, "reason": "cần vốn nữa"})
        self.assertTrue(err)
        rows = self.state.read_jsonl(self.state.funding_requests_path)
        self.assertEqual(len(rows), 1)

    def test_check_wallet_mentions_51_49(self):
        out, err = toolbox.execute(self.ctx, "check_wallet", {})
        self.assertFalse(err)
        self.assertIn("51%", out)
        self.assertIn("49%", out)

    def test_unknown_tool(self):
        out, err = toolbox.execute(self.ctx, "hack_owner_fund", {})
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
