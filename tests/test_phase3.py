"""Offline tests for the Phase 3 read-only Kubernetes tools.

Run with:  .venv/bin/python -m unittest discover -s tests -v

No cluster and no real kubectl are needed: a FAKE kubectl stub (a test
double that records its arguments and echoes canned JSON) is placed first on
PATH so the exact command lines the agent would run can be verified. This is
how we prove, without a cluster, that the tools can only ever construct
read-only `kubectl get` / `kubectl logs` invocations. The application itself
never uses a fake kubectl; real cluster verification is separate.
"""

import os
import shutil
import stat
import tempfile
import unittest
from types import SimpleNamespace

from agent.agent import DevOpsAgent
from tools.registry import execute_tool, get_tools

# Canned kubectl output for the stub.
STUB = """#!/usr/bin/env bash
echo "ARGS: $*"
"""


class FakeKubectlMixin(unittest.TestCase):
    """Places a fake kubectl stub first on PATH for the duration of a test."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._kubectl = os.path.join(self._tmpdir.name, "kubectl")
        with open(self._kubectl, "w") as fh:
            fh.write(STUB)
        os.chmod(self._kubectl, os.stat(self._kubectl).st_mode | stat.S_IEXEC)
        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self._tmpdir.name + os.pathsep + self._old_path

    def tearDown(self):
        os.environ["PATH"] = self._old_path
        self._tmpdir.cleanup()


class KubernetesToolTests(FakeKubectlMixin):
    def test_kubernetes_tools_registered(self):
        names = {tool.name for tool in get_tools()}
        self.assertTrue(
            {"k8s_pod_status", "k8s_pod_logs", "k8s_deployment_status"} <= names
        )

    def test_pod_status_command(self):
        result = execute_tool("k8s_pod_status", '{"pod": "web-1", "namespace": "prod"}')
        self.assertIn(
            "ARGS: get pod web-1 -n prod -o json --request-timeout=10", result
        )

    def test_pod_status_default_namespace(self):
        result = execute_tool("k8s_pod_status", '{"pod": "web-1"}')
        self.assertIn(
            "ARGS: get pod web-1 -n default -o json --request-timeout=10", result
        )

    def test_pod_logs_arguments_and_default_lines(self):
        result = execute_tool("k8s_pod_logs", '{"pod": "worker-3", "lines": 50}')
        self.assertIn(
            "ARGS: logs worker-3 -n default --tail 50 --request-timeout=10", result
        )
        result = execute_tool("k8s_pod_logs", '{"pod": "worker-3"}')
        self.assertIn("--tail 100", result)

    def test_deployment_status_command(self):
        result = execute_tool(
            "k8s_deployment_status", '{"deployment": "api", "namespace": "prod"}'
        )
        self.assertIn(
            "ARGS: get deployment api -n prod -o json --request-timeout=10", result
        )

    def test_only_read_only_verbs_are_possible(self):
        # Walk every generated command line: the verb must be get or logs only.
        invocations = [
            ("k8s_pod_status", '{"pod": "x"}'),
            ("k8s_pod_logs", '{"pod": "x"}'),
            ("k8s_deployment_status", '{"deployment": "x"}'),
        ]
        for tool, args in invocations:
            result = execute_tool(tool, args)
            line = next(l for l in result.splitlines() if l.startswith("ARGS: "))
            verb = line.split()[1]
            self.assertIn(verb, {"get", "logs"}, f"{tool} used a non-read-only verb")

    def test_invalid_pod_name_rejected_without_invoking_kubectl(self):
        for bad in ["--flag", "UPPER", "has space", "x" * 300, "..", "-n"]:
            result = execute_tool("k8s_pod_status", '{"pod": "%s"}' % bad)
            self.assertTrue(result.startswith("Tool error"), bad)
            self.assertNotIn("ARGS:", result)  # kubectl never ran

    def test_invalid_lines_rejected(self):
        for bad in ["0", "501", "-3"]:
            result = execute_tool("k8s_pod_logs", '{"pod": "x", "lines": %s}' % bad)
            self.assertTrue(result.startswith("Tool error"), bad)

    def test_missing_required_argument(self):
        result = execute_tool("k8s_pod_logs", "{}")
        self.assertTrue(result.startswith("Tool error"))


class KubernetesLoopTest(FakeKubectlMixin):
    """The tool-use loop with a k8s tool: real execution, evidence fed back."""

    def test_loop_executes_k8s_tool(self):
        responses = _FakeResponses(
            [
                _tool_call_response(
                    name="k8s_pod_status", arguments='{"pod": "web-1"}'
                ),
                _text_response("The pod is crashing."),
            ]
        )
        agent = DevOpsAgent(api_key="sk-test-not-a-real-key")
        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=responses))

        answer = agent.ask("What is the status of pod web-1?")
        self.assertEqual(answer, "The pod is crashing.")
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        tool_msg = agent.messages[3]
        self.assertEqual(tool_msg["tool_call_id"], "call_1")
        # The tool result must contain the real (stub-captured) invocation.
        self.assertIn("ARGS: get pod web-1 -n default", tool_msg["content"])


class _FakeResponses:
    """Stands in for client.chat.completions.create()."""

    def __init__(self, payloads):
        self._payloads = list(payloads)

    def create(self, **kwargs):
        return self._payloads.pop(0)


def _tool_call_response(name, arguments):
    call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return _choice({"content": None, "tool_calls": [call]})


def _text_response(text):
    return _choice({"content": text, "tool_calls": None})


def _choice(payload):
    message = SimpleNamespace(**payload)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@unittest.skipIf(shutil.which("kubectl"), "a real kubectl is installed here")
class MissingKubectlTest(unittest.TestCase):
    """Honest behavior when kubectl is not present (the current sandbox)."""

    def test_clean_error_message(self):
        result = execute_tool("k8s_pod_status", '{"pod": "web-1"}')
        self.assertEqual(
            result,
            "Tool error: required executable 'kubectl' is not installed on "
            "this host",
        )


if __name__ == "__main__":
    unittest.main()