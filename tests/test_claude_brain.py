import unittest
from types import SimpleNamespace

from automaton51.brain.claude import ClaudeBrain


class FakeMessages:
    def __init__(self, responses, reject_fallbacks=False):
        self.responses = list(responses)
        self.calls = []
        self.reject_fallbacks = reject_fallbacks

    def create(self, **kw):
        if self.reject_fallbacks and "fallbacks" in kw:
            raise TypeError("unexpected keyword argument 'fallbacks'")
        snapshot = dict(kw)
        snapshot["messages"] = [dict(m) for m in kw["messages"]]
        self.calls.append(snapshot)
        return self.responses.pop(0)


def fake_client(responses, reject_fallbacks=False):
    msgs = FakeMessages(responses, reject_fallbacks)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def resp(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, stop_details=None,
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_creation_input_tokens=50, cache_read_input_tokens=900))


class ClaudeBrainTests(unittest.TestCase):
    def test_tool_use_round_trip_and_request_shape(self):
        client, msgs = fake_client([
            resp([SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="tool_use", id="tu_1", name="check_wallet", input={})], "tool_use"),
            resp([SimpleNamespace(type="text", text="Nhật ký: xong.")], "end_turn"),
        ])
        brain = ClaudeBrain(model="claude-opus-5-5", effort="high", client=client)
        brain.begin_turn("SYSTEM", "INPUT", [{"name": "check_wallet", "description": "d", "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, "strict": True}], {})
        s1 = brain.step(None)
        self.assertEqual([c.name for c in s1.tool_calls], ["check_wallet"])
        self.assertEqual(s1.usage["input_tokens"], 1200)
        kw = msgs.calls[0]
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertEqual(kw["output_config"], {"effort": "high"})
        self.assertEqual(kw["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        s2 = brain.step([{"tool_use_id": "tu_1", "content": "ví 10", "is_error": False}])
        self.assertEqual(s2.text, "Nhật ký: xong.")
        self.assertEqual(s2.tool_calls, [])
        # lịch sử: user, assistant(tool_use), user(tool_result), assistant(text)
        roles = [m["role"] for m in msgs.calls[1]["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(msgs.calls[1]["messages"][2]["content"][0]["type"], "tool_result")

    def test_haiku_has_no_effort_or_fallbacks(self):
        client, msgs = fake_client([resp([SimpleNamespace(type="text", text="ok")], "end_turn", model="claude-haiku-4-5")])
        brain = ClaudeBrain(model="claude-haiku-4-5", effort="low", client=client)
        brain.begin_turn("S", "I", [], {})
        brain.step(None)
        kw = msgs.calls[0]
        self.assertNotIn("thinking", kw)
        self.assertNotIn("output_config", kw)
        self.assertNotIn("fallbacks", kw)

    def test_retries_without_fallbacks_when_unsupported(self):
        client, msgs = fake_client([resp([SimpleNamespace(type="text", text="ok")])], reject_fallbacks=True)
        brain = ClaudeBrain(model="claude-opus-5-5", client=client)
        brain.begin_turn("S", "I", [], {})
        s = brain.step(None)
        self.assertEqual(s.text, "ok")
        self.assertFalse(brain.enable_fallbacks)
        self.assertNotIn("fallbacks", msgs.calls[0])

    def test_refusal_and_max_tokens_drop_tool_calls(self):
        client, _ = fake_client([
            resp([SimpleNamespace(type="tool_use", id="x", name="sleep", input={"seconds": 60, "reason": ""})], "max_tokens"),
            resp([SimpleNamespace(type="text", text="")], "refusal"),
        ])
        brain = ClaudeBrain(client=client)
        brain.begin_turn("S", "I", [], {})
        s = brain.step(None)
        self.assertEqual(s.tool_calls, [])
        self.assertIn("max_tokens", s.error)
        s = brain.step(None)
        self.assertIn("từ chối", s.error)


if __name__ == "__main__":
    unittest.main()
