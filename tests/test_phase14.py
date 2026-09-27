"""Offline tests for Phase 14: the human-approval gate for mutating tools.

Run with:  .venv/bin/python -m unittest discover -s tests -v

No network and no model calls. A tiny mutating stub tool is registered per
test (then removed) to exercise the gate end-to-end: default-deny when no
human can be asked, y/n flow with the asker seam, session memory, reset,
the audit ring, and proof that read-only tools never touch the gate.
"""

import shutil
import tempfile
import unittest
from types import SimpleNamespace

import agent.agent  # noqa: F401  # registers every tool
from tools import approval
from tools.base import Tool
from tools.registry import _TOOLS, execute_tool, get_tools, register


def _make_mutating_tool(name: str = "p14_stub_mutate") -> Tool:
    def executor(args: dict) -> str:
        return f"$ (mutating stub ran) {args}"

    return Tool(
        name=name,
        description="Phase 14 stub: pretends to mutate something. Read-only test.",
        parameters={"type": "object", "properties": {
            "target": {"type": "string", "description": "what to mutate"},
        }, "additionalProperties": False},
        executor=executor,
        mutating=True,
    )


class ApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.tool = _make_mutating_tool()
        register(self.tool)
        self.addCleanup(_TOOLS.pop, self.tool.name, None)
        self.addCleanup(approval.set_asker, None)
        self.addCleanup(approval.reset_approvals)
        self.addCleanup(approval.reset_audit)
        # keep the JSONL audit out of the real home dir
        tmp = tempfile.mkdtemp(prefix="p14-audit-")
        os_old = self._patch_env(str(tmp))
        self.addCleanup(self._restore_env, os_old)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

    def _patch_env(self, value):
        import os
        old = os.environ.get("AGENT_STORE_DIR")
        os.environ["AGENT_STORE_DIR"] = value
        return old

    def _restore_env(self, old):
        import os
        if old is None:
            os.environ.pop("AGENT_STORE_DIR", None)
        else:
            os.environ["AGENT_STORE_DIR"] = old

    def run_tool(self, args: str = '{"target": "pod/api-5d6f"}') -> str:
        return execute_tool(self.tool.name, args)

    # --- default-deny ----------------------------------------------------------

    def test_no_asker_means_auto_deny(self):
        approval.set_asker(None)  # one-shot mode, pipes, tests
        result = self.run_tool()
        self.assertTrue(result.startswith("Tool error: denied"), result)
        self.assertIn("denied by the human operator", result)

    def test_denied_tool_never_runs(self):
        result = self.run_tool()
        self.assertNotIn("mutating stub ran", result)

    def test_asker_saying_no_denies(self):
        approval.set_asker(lambda prompt: False)
        result = self.run_tool()
        self.assertTrue(result.startswith("Tool error: denied"), result)

    def test_asker_saying_yes_runs_once(self):
        approval.set_asker(lambda prompt: True)
        result = self.run_tool()
        self.assertIn("mutating stub ran", result)

    def test_asker_sees_the_action_summary(self):
        seen = {}
        def asker(prompt: str) -> bool:
            seen["prompt"] = prompt
            return True
        approval.set_asker(asker)
        self.run_tool('{"target": "svc/checkout"}')
        self.assertIn("p14_stub_mutate", seen["prompt"])
        self.assertIn("svc/checkout", seen["prompt"])

    # --- session memory ----------------------------------------------------------

    def test_identical_action_rides_one_approval(self):
        asks = {"n": 0}
        def asker(prompt: str) -> bool:
            asks["n"] += 1
            return True
        approval.set_asker(asker)
        self.run_tool()
        self.run_tool()  # same tool, same action
        self.assertEqual(asks["n"], 1)

    def test_different_action_re_asks(self):
        asks = {"n": 0}
        def asker(prompt: str) -> bool:
            asks["n"] += 1
            return True
        approval.set_asker(asker)
        self.run_tool('{"target": "a"}')
        self.run_tool('{"target": "b"}')
        self.assertEqual(asks["n"], 2)

    def test_reset_forgets_session_approvals(self):
        approval.set_asker(lambda prompt: True)
        self.run_tool()
        n = approval.reset_approvals()
        self.assertEqual(n, 1)
        asks = {"n": 0}
        def asker(prompt: str) -> bool:
            asks["n"] += 1
            return True
        approval.set_asker(asker)
        self.run_tool()
        self.assertEqual(asks["n"], 1)  # had to ask again

    # --- audit ---------------------------------------------------------------------

    def test_audit_records_all_decisions(self):
        approval.set_asker(None)
        self.run_tool()                      # auto-denied
        approval.set_asker(lambda prompt: True)
        self.run_tool()                      # approved
        audit = approval.audit_text()
        self.assertIn("DENIED", audit)
        self.assertIn("APPROVED", audit)
        self.assertIn("auto: no human to ask", audit)

    def test_audit_text_none_when_empty(self):
        self.assertIsNone(approval.audit_text())

    # --- read-only surface is untouched ----------------------------------------------

    def test_read_only_tools_bypass_the_gate(self):
        # a registered read-only tool runs without any asker — the 61
        # existing tools' behavior is unchanged
        result = execute_tool("system_info", '{"command": "uname"}')
        self.assertTrue(result.startswith("$ uname"), result)

    def test_mutating_flag_defaults_false(self):
        tool = next(t for t in get_tools() if t.name == "system_info")
        self.assertFalse(tool.mutating)

    def test_denial_keeps_the_loop_alive_shape(self):
        # the returned string is a normal "Tool error:" line — the model can
        # read it and adapt, exactly like any other tool failure
        result = self.run_tool()
        self.assertTrue(result.startswith("Tool error:"), result)
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
