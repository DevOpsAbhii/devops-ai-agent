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
import tempfile
import time
import types
import unittest
from pathlib import Path

import httpx2 as httpx  # openai 3.19 depends on the httpx2 fork
import main as main_module
import agent.agent as agent_module
from agent import config as user_config
from agent.agent import DEFAULT_MODEL, DevOpsAgent
from agent.investigation import Investigation
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
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
            main_module.parse_args([]), (None, False, None, False, None, None)
        )
        self.assertEqual(
            main_module.parse_args(["why is it down?"]),
            ("why is it down?", False, None, False, None, None),
        )
        self.assertEqual(
            main_module.parse_args(["--json", "why", "is it down?"]),
            ("why is it down?", True, None, False, None, None),
        )
        self.assertEqual(
            main_module.parse_args(["--json"]),
            (None, True, None, False, None, None),
        )
        self.assertEqual(
            main_module.parse_args(["--model", "openai/gpt-4o-mini", "why?"]),
            ("why?", False, None, False, None, "openai/gpt-4o-mini"),
        )
        self.assertEqual(
            main_module.parse_args(["--model", "anthropic/claude-sonnet-5"]),
            (None, False, None, False, None, "anthropic/claude-sonnet-5"),
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


class KeylessTests(unittest.TestCase):
    """Model-less mode: no API key configured.

    The agent must still construct (record commands + tool layer never call
    the model); only the chat path raises, and the CLI reports it loudly.
    """

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.addCleanup(self._restore_key)
        inv_tools.set_store(None)

    def _restore_key(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

    def test_agent_constructs_without_a_key(self):
        agent = DevOpsAgent()
        self.assertIsNone(agent.client)
        self.assertIn("OPENROUTER_API_KEY", agent.model_error)
        self.assertTrue(agent.tools)  # the tool layer is fully usable

    def test_placeholder_key_is_also_model_less(self):
        os.environ["OPENROUTER_API_KEY"] = "your_key_here"
        agent = DevOpsAgent()
        self.assertIsNone(agent.client)
        self.assertIn("placeholder", agent.model_error)

    def test_ask_without_key_raises_loud(self):
        agent = DevOpsAgent()
        with self.assertRaises(ValueError) as ctx:
            agent.ask("why is it down?")
        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_oneshot_slash_command_works_without_key(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main_module.run_one_shot("/report")
        self.assertEqual(code, 0)
        self.assertIn("(no investigation recorded)", out.getvalue())

    def test_oneshot_question_without_key_exits_1(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(err), contextlib.redirect_stderr(err):
            code = main_module.run_one_shot("why is api-5d6f crash-looping?")
        self.assertEqual(code, 1)
        self.assertIn("OPENROUTER_API_KEY", err.getvalue())


class ModelChoiceTests(unittest.TestCase):
    """Model preference ladder + the /model command + agent/config.py.

    Precedence, highest first: explicit model argument > config.json >
    OPENROUTER_MODEL env > built-in default. Tests point AGENT_CONFIG_FILE
    at a tmp file so the developer's real ~/.devops-ai-agent/config.json
    is never read or written.
    """

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        self.config_file = tmp.name
        os.environ["AGENT_CONFIG_FILE"] = self.config_file
        self.addCleanup(self._restore)

    def _restore(self):
        os.environ.pop("AGENT_CONFIG_FILE", None)
        Path(self.config_file).unlink(missing_ok=True)

    def _set_env(self, name, value):
        old = os.environ.get(name)
        os.environ[name] = value
        self.addCleanup(lambda: (
            os.environ.pop(name, None) if old is None
            else os.environ.__setitem__(name, old)
        ))

    def test_config_round_trip_and_corrupt_tolerance(self):
        self.assertEqual(user_config.load_user_config(), {})  # missing file
        path = user_config.save_user_config({"model": "openai/gpt-4o-mini"})
        self.assertEqual(path, Path(self.config_file))
        self.assertEqual(user_config.load_user_config(),
                         {"model": "openai/gpt-4o-mini"})
        # Merging keeps existing keys and overwrites the given one.
        user_config.save_user_config({"model": "anthropic/claude-sonnet-5"})
        self.assertEqual(user_config.load_user_config(),
                         {"model": "anthropic/claude-sonnet-5"})
        # Corrupt content degrades to {} instead of raising.
        Path(self.config_file).write_text("{not json", encoding="utf-8")
        self.assertEqual(user_config.load_user_config(), {})

    def test_model_precedence_ladder(self):
        # 4. built-in default
        self.assertEqual(DevOpsAgent().model, DEFAULT_MODEL)
        # 3. environment
        self._set_env("OPENROUTER_MODEL", "env/model")
        self.assertEqual(DevOpsAgent().model, "env/model")
        # 2. config file (outranks env)
        user_config.save_user_config({"model": "config/model"})
        self.assertEqual(DevOpsAgent().model, "config/model")
        # 1. explicit argument (outranks everything)
        self.assertEqual(DevOpsAgent(model="flag/model").model, "flag/model")

    def test_model_command_shows_current_model(self):
        agent = DevOpsAgent()
        before = agent.model
        text = main_module.handle_command("/model", agent)
        self.assertIn(before, text)
        self.assertIn(str(user_config.config_path()), text)
        self.assertEqual(agent.model, before)  # show-only changes nothing

    def test_model_command_saves_and_switches(self):
        agent = DevOpsAgent()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            text = main_module.handle_command(
                "/model openai/gpt-4o-mini", agent)
        self.assertIn("openai/gpt-4o-mini", text)
        self.assertEqual(agent.model, "openai/gpt-4o-mini")
        self.assertEqual(
            user_config.load_user_config(), {"model": "openai/gpt-4o-mini"})
        # A multi-token name is rejected; the config stays untouched.
        text = main_module.handle_command("/model two words", agent)
        self.assertIn("single token", text)
        self.assertEqual(agent.model, "openai/gpt-4o-mini")


class FlakyChat:
    """Chat stub that raises the queued errors, then answers with content."""

    def __init__(self, errors: list[Exception], content: str = "ok"):
        self._errors = list(errors)
        self._content = content
        self.calls = 0

    def create(self, **kwargs):  # noqa: D102
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        message = types.SimpleNamespace(content=self._content, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )


def _api_status_error(status: int, headers: dict | None = None):
    """Build an openai status error offline (no HTTP round-trip)."""
    request = httpx.Request(
        "POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        status, request=request, headers=headers or {})
    return APIStatusError("boom", response=response, body=None)


def _api_connection_error():
    request = httpx.Request(
        "POST", "https://openrouter.ai/api/v1/chat/completions")
    return APIConnectionError(request=request)


class RetryTests(unittest.TestCase):
    """_call_model: transient failures retry with backoff, others fail fast.

    Sleeps are intercepted via the agent.agent._sleep seam, so the tests
    run instantly; the recorded delays prove the backoff schedule.
    """

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-for-offline-tests"
        self.agent = DevOpsAgent()
        self.sleeps: list[float] = []
        agent_module._sleep = self.sleeps.append
        self.addCleanup(self._restore)

    def _restore(self):
        agent_module._sleep = time.sleep
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key

    def test_connection_errors_are_retried_then_succeed(self):
        chat = FlakyChat([_api_connection_error(), _api_connection_error()])
        self.agent.client.chat.completions = chat
        self.assertEqual(self.agent.ask("why is it down?"), "ok")
        self.assertEqual(chat.calls, 3)  # original + 2 retries
        # Backoff: attempt 0 -> ~2s (+jitter), attempt 1 -> ~4s (+jitter).
        self.assertGreaterEqual(self.sleeps[0], 2.0)
        self.assertLessEqual(self.sleeps[0], 3.0)
        self.assertGreaterEqual(self.sleeps[1], 4.0)
        self.assertLessEqual(self.sleeps[1], 5.0)

    def test_timeout_is_transient(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        chat = FlakyChat([APITimeoutError(request)])
        self.agent.client.chat.completions = chat
        self.assertEqual(self.agent.ask("hello"), "ok")
        self.assertEqual(chat.calls, 2)

    def test_rate_limit_honors_retry_after_header(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        response = httpx.Response(
            429, request=request, headers={"retry-after": "7"})
        chat = FlakyChat([RateLimitError("slow down", response=response,
                                         body=None)])
        self.agent.client.chat.completions = chat
        self.assertEqual(self.agent.ask("hello"), "ok")
        self.assertEqual(self.sleeps, [7.0])

    def test_rate_limit_without_header_uses_backoff(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        response = httpx.Response(429, request=request)
        chat = FlakyChat([RateLimitError("slow down", response=response,
                                         body=None)])
        self.agent.client.chat.completions = chat
        self.assertEqual(self.agent.ask("hello"), "ok")
        self.assertGreaterEqual(self.sleeps[0], 2.0)

    def test_auth_error_fails_immediately(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        response = httpx.Response(401, request=request)
        chat = FlakyChat([AuthenticationError("bad key", response=response,
                                              body=None)])
        self.agent.client.chat.completions = chat
        with self.assertRaises(AuthenticationError):
            self.agent.ask("hello")
        self.assertEqual(chat.calls, 1)  # no retry on a rejected key
        self.assertEqual(self.sleeps, [])

    def test_client_400_fails_immediately(self):
        chat = FlakyChat([_api_status_error(400)])
        self.agent.client.chat.completions = chat
        with self.assertRaises(APIStatusError):
            self.agent.ask("hello")
        self.assertEqual(chat.calls, 1)

    def test_server_500_is_retried(self):
        chat = FlakyChat([_api_status_error(500), _api_status_error(502)])
        self.agent.client.chat.completions = chat
        self.assertEqual(self.agent.ask("hello"), "ok")
        self.assertEqual(chat.calls, 3)

    def test_retries_are_exhausted_loudly(self):
        chat = FlakyChat([_api_connection_error() for _ in range(4)])
        self.agent.client.chat.completions = chat
        with self.assertRaises(APIConnectionError):
            self.agent.ask("hello")
        self.assertEqual(chat.calls, 4)  # original + 3 retries, then raise
        self.assertEqual(len(self.sleeps), 3)  # 2s, 4s, 8s schedule


if __name__ == "__main__":
    unittest.main()