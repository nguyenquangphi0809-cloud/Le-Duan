import json
import threading
import unittest
import urllib.error
import urllib.request

from automaton51.loop import Automaton, VirtualClock
from automaton51.revenue import RevenueInbox
from automaton51.server import DashboardServer
from tests.helpers import make_state


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.state, self.cfg = make_state("10")
        auto = Automaton(self.state, self.cfg, None, clock=VirtualClock(1_700_000_000.0), log=lambda m: None)
        auto.tick()
        self.server = DashboardServer(("127.0.0.1", 0), self.state, self.cfg)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.read().decode("utf-8")

    def _post(self, path, payload, secret=None):
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Automaton-Secret"] = secret
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_pages(self):
        code, body = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn("Test-51", body)
        self.assertIn("51%", body)
        code, body = self._get("/store")
        self.assertEqual(code, 200)
        code, body = self._get("/api/status")
        self.assertEqual(json.loads(body)["owner_share"], "0.51")

    def test_webhook_secret_and_dedupe(self):
        code, body = self._post("/webhook/revenue", {"amount": 12.5}, secret=None)
        self.assertEqual(code, 401)
        code, body = self._post("/webhook/revenue", {"amount": 12.5, "memo": "Stripe", "external_id": "ch_1"}, secret="s3cret")
        self.assertEqual(code, 200)
        self.assertFalse(body["duplicate"])
        code, body = self._post("/webhook/revenue", {"amount": 12.5, "external_id": "ch_1"}, secret="s3cret")
        self.assertTrue(body["duplicate"])
        self.assertEqual(len(RevenueInbox(self.state).pending()), 1)
        code, body = self._post("/webhook/revenue", {"amount": -1}, secret="s3cret")
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
