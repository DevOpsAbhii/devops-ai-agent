"""Offline tests for the automation surface: structured JSON investigation
reports (render_report_json) and the one-shot CLI mode (main.run_one_shot).

Run with:  .venv/bin/python -m unittest discover -s tests -v

No network or LLM is touched: the one-shot tests inject a stub chat client
and exercise state that was populated by the pure-data investigation API.
"""

import contextlib
import io
import json
import os
import types
import unittest

import main as main_module
from agent.agent import DevOpsAgent
from agent.investigation import Investigation
from tools import investigation as inv_tools


class JSONReportTests(unittest.TestCase):
    """render_report_json — the pure data view for CI/automation."""

    def _concluded(self) -> Investigation:
        inv = Investigation("pod api-7d is CrashLoopBackOff")
        inv.add_hypothesis("bad image digest")
        inv.record_evidence("exit 1 in logs", "H1")
        inv.conclude(
            summary="entrypoint exits immediately",
            root_cause="the command exits 1 right after start",
            remediation=["correct the command", "pin a healthy image tag"],
            verification=["kubectl logs follow a redeploy", "check restart count stops rising"],
            confidence="high",
        )
        return inv

    def test_in_progress_shape(self):
        inv = Investigation("pod is crash-looping")
        inv.add_hypothesis("image digest missing")
        inv.record_evidence("image not found", "H1")
        data = inv.render_report_json()
        self.assertEqual(data["problem"], "pod is crash-looping")
        self.assertEqual(data["status"], "in_progress")
        self.assertNotIn("conclusion", data)
        self.assertEqual(data["hypotheses"][0]["statement"], "image digest missing")
        self.assertEqual(data["hypotheses"][0]["status"], "proposed")
        self.assertEqual(data["evidence"][0]["hypothesis_id"], "H1")
        self.assertEqual(data["evidence"][0]["content"], "image not found")

    def test_concluded_shape(self):
        data = self._concluded().render_report_json()
        self.assertEqual(data["status"], "concluded")
        c = data["conclusion"]
        self.assertEqual(c["root_cause"], "the command exits 1 right after start")
        self.assertEqual(c["confidence"], "high")
        self.assertEqual(c["remediation"], ["correct the command", "pin a healthy image tag"])
        self.assertEqual(c["verification"][1], "check restart count stops rising")
        # hypotheses/evidence survive into the concluded export
        self.assertEqual(data["hypotheses"][0]["status"], "proposed")
        self.assertEqual(len(data["evidence"]), 1)

    def test_status_enum_validates(self):
        inv = self._concluded()
        inv.verify_hypothesis("H1", "refuted", "digest exists in the registry")
        data = inv.render_report_json()
        self.assertEqual(data["hypotheses"][0]["status"], "refuted")
        self.assertEqual(data["hypotheses"][0]["notes"], ["digest exists in the registry"])

    def test_json_agrees_with_markdown_report(self):
        inv = self._concluded()
        data = inv.render_report_json()
        text = inv.render_report()
        self.assertIn(data["conclusion"]["root_cause"], text)
        for item in data["conclusion"]["remediation"]:
            self.assertIn(item, text)
        self.assertIn(data["conclusion"]["summary"], text)


class ToolsReportJsonTests(unittest.TestCase):
    """report_json() — the module-level export the agent delegate calls."""

    def setUp(self):
        # Persistence is not under test here — keep it off so nothing is
        # written outside the test sandbox (Phase 7).
        inv_tools.set_store(None)

    def tearDown(self):
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

    def test_none_without_active_investigation(self):
        self.assertIsNone(inv_tools.report_json())

    def test_matches_render_report_json_through_lifecycle(self):
        inv_tools.start_investigation("docker p5loop keeps restarting")
        inv_tools.record(
            "evidence", "exit code 1 in container logs", hypothesis_id=None
        )
        inv_tools.conclude_investigation(
            summary="the entrypoint exits 1 immediately",
            root_cause="broken command in the image",
            remediation="fix the CMD and redeploy",
            verification="docker logs after recreate shows a long-lived process",
            confidence="medium",
        )
        direct = inv_tools._active.render_report_json()
        self.assertEqual(inv_tools.report_json(), direct)
        self.assertEqual(inv_tools.report_json()["status"], "concluded")

    def test_cleared_after_finish(self):
        inv_tools.start_investigation("sshd is not accepting connections")
        inv_tools.finish_investigation()
        self.assertIsNone(inv_tools.report_json())


class AgentDelegateTests(unittest.TestCase):
    """DevOpsAgent.investigation_report_json() routes to the same record."""

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-for-offline-tests"
        self.agent = DevOpsAgent()
        self.addCleanup(self._restore_key)
        inv_tools.set_store(None)

    def _restore_key(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

    def test_delegate_returns_none_when_idle(self):
        self.assertIsNone(self.agent.investigation_report_json())

    def test_delegate_returns_the_tracked_report(self):
        inv_tools.start_investigation("api-5d6f rollout is stuck")
        inv_tools.conclude_investigation(
            summary="image pull fails in registry",
            root_cause="missing tag in the registry",
            remediation="push the tag or pin an existing digest",
            verification="kubectl rollout status api-5d6f reaches ready",
            confidence="high",
        )
        report = self.agent.investigation_report_json()
        self.assertEqual(report["conclusion"]["root_cause"], "missing tag in the registry")


class StubChat:
    """Drop-in replacement for client.chat: returns one plain-text reply."""

    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):  # noqa: D102
        message = types.SimpleNamespace(content=self._content, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )


class OneShotCliTests(unittest.TestCase):
    """main.parse_args and main.run_one_shot (stubbed client, no network)."""

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-for-offline-tests"
        self.agent = DevOpsAgent()
        self.agent.client.chat.completions = StubChat("investigation complete.")
        self.addCleanup(self._restore_key)
        inv_tools.set_store(None)

    def _restore_key(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

    def _run(self, task: str, as_json: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main_module.run_one_shot(task, as_json=as_json, agent=self.agent)
        return code, out.getvalue()

    def test_parse_args(self):
        self.assertEqual(
            main_module.parse_args([]), (None, False, None, False, None)
        )
        self.assertEqual(
            main_module.parse_args(["why is it down?"]),
            ("why is it down?", False, None, False, None),
        )
        self.assertEqual(
            main_module.parse_args(["--json", "why", "is it down?"]),
            ("why is it down?", True, None, False, None),
        )
        self.assertEqual(
            main_module.parse_args(["--json"]),
            (None, True, None, False, None),
        )

    def test_slash_command_routes_without_model(self):
        code, out = self._run("/report")
        self.assertEqual(code, 0)
        self.assertIn("(no investigation recorded)", out)

    def test_json_output_is_valid_and_structured(self):
        inv_tools.start_investigation("checkout pod crash-loops")
        inv_tools.conclude_investigation(
            summary="image entrypoint exits 1",
            root_cause="command exits immediately",
            remediation="fix the entrypoint command",
            verification="redeploy and watch restart count",
            confidence="high",
        )
        code, out = self._run("report it as json", as_json=True)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["status"], "concluded")
        self.assertEqual(data["problem"], "checkout pod crash-loops")
        self.assertEqual(data["conclusion"]["root_cause"], "command exits immediately")

    def test_json_flag_without_investigation_fails_loud(self):
        code, out = self._run("hello", as_json=True)
        self.assertEqual(code, 1)
        self.assertNotIn("investigation complete.", out)

    def test_plain_run_prints_the_answer(self):
        code, out = self._run("say hello")
        self.assertEqual(code, 0)
        self.assertIn("investigation complete.", out)

    def test_markdown_never_leaks_to_json_stdout(self):
        inv_tools.start_investigation("x")
        inv_tools.conclude_investigation(
            summary="s",
            root_cause="r",
            remediation="fix",
            verification="verify",
            confidence="low",
        )
        code, out = self._run("go", as_json=True)
        self.assertEqual(code, 0)
        json.loads(out)  # the entire stdout must be one valid JSON document


if __name__ == "__main__":
    unittest.main()