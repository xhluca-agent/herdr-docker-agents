"""Tests for the relay's request filter: python3 -m unittest discover -s tests"""

import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader(
    "herdr_docker_run", os.path.join(HERE, "..", "bin", "herdr-docker-run"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
hdr = importlib.util.module_from_spec(_spec)
_loader.exec_module(hdr)


def report(**params):
    return {"id": "x", "method": "pane.report_agent", "params": params}


class SanitizeTest(unittest.TestCase):
    def setUp(self):
        self.relay = hdr.Relay("/nonexistent", "w1:p9", "pi")

    def test_state_report_is_rebuilt_for_own_pane(self):
        out = self.relay.sanitize(report(pane_id="w1:p1", source="herdr:codex", agent="codex",
                                         state="working", seq=5))
        self.assertEqual(out["method"], "pane.report_agent")
        self.assertEqual(out["params"], {"pane_id": "w1:p9", "source": "docker:pi", "agent": "pi",
                                         "state": "working", "seq": 5})

    def test_drops_session_refs_and_resume_argv(self):
        out = self.relay.sanitize(report(state="idle", agent_session_id="s", agent_session_path="/p",
                                         resume_argv=["touch", "/tmp/pwned"], extra=1))
        self.assertEqual(set(out["params"]), {"pane_id", "source", "agent", "state"})

    def test_refuses_other_methods(self):
        for method in ("pane.report_agent_session", "pane.send_keys", "pane.send_text", "pane.run",
                       "pane.read", "pane.close", "agent.prompt", "plugin.link", "pane.report_metadata"):
            req = {"id": "x", "method": method, "params": {"pane_id": "w1:p9", "state": "idle"}}
            self.assertIsNone(self.relay.sanitize(req), method)

    def test_refuses_bad_states_and_shapes(self):
        for req in (report(state="done"), report(state=None), report(), {"method": "pane.report_agent"},
                    {"method": "pane.report_agent", "params": "x"}, [], "x", None):
            self.assertIsNone(self.relay.sanitize(req), req)

    def test_message_is_capped_and_cleaned(self):
        out = self.relay.sanitize(report(state="blocked", message="\x1b]0;evil\x07ok\n" + "a" * 500))
        msg = out["params"]["message"]
        self.assertLessEqual(len(msg), hdr.MAX_MESSAGE)
        self.assertFalse(any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in msg))

    def test_seq_must_be_a_sane_int(self):
        for seq in (True, -1, 2**63, "5", 1.5):
            self.assertNotIn("seq", self.relay.sanitize(report(state="idle", seq=seq))["params"], seq)

    def test_release_is_allowed_and_forced(self):
        out = self.relay.sanitize({"method": "pane.release_agent",
                                   "params": {"pane_id": "w1:p1", "source": "a", "agent": "b"}})
        self.assertEqual(out["params"], {"pane_id": "w1:p9", "source": "docker:pi", "agent": "pi"})

    def test_rate_limit(self):
        allowed = sum(self.relay.allow() for _ in range(100))
        self.assertLessEqual(allowed, hdr.RATE_PER_SEC + 1)


if __name__ == "__main__":
    unittest.main()
