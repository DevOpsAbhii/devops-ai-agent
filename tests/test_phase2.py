"""Offline tests for the Phase 2 tool contract and tool-use loop.

Run with:  .venv/bin/python -m unittest discover -s tests -v

These tests make NO network calls and do not need an API key. The
tool-use-loop tests swap the real OpenAI client for a fake one so the loop
logic is exercised deterministically; the system_info tool still runs for
real (it executes only allowlisted read-only commands).
"""

import unittest
from types import SimpleNamespace

from agent.agent import MAX_TOOL_ITERATIONS, DevOpsAgent
from agent.prompts import SYSTEM_PROMPT
from tools.base import Tool, ToolError, truncate_output
from tools.registry import execute_tool, get_tools


class FakeResponses:
    """Stands in for client.chat.completions.create()."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.last_request = None
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.last_request = kwargs
        return self._payloads.pop(0)


def _choice(message_payload):
    message = SimpleNamespace(**message_payload)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call_response(name="system_info", arguments='{"command": "uname"}'):
    call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return _choice({"content": None, "tool_calls": [call]})


def _text_response(text):
    return _choice({"content": text, "tool_calls": None})


class ToolContractTests(unittest.TestCase):
    def test_tools_are_registered(self):
        names = {tool.name for tool in get_tools()}
        self.assertEqual(
            names,
            {
                # host + investigation
                "system_info",
                "investigation_begin",
                "investigation_record",
                "investigation_conclude",
                # Kubernetes
                "k8s_pod_status",
                "k8s_pod_logs",
                "k8s_deployment_status",
                "k8s_events",
                "k8s_nodes",
                "k8s_services",
                # Linux system
                "sys_service_status",
                "sys_service_logs",
                "sys_open_ports",
                "sys_top_processes",
                # Docker
                "docker_ps",
                "docker_inspect",
                "docker_logs",
                "docker_stats",
                "docker_images",
                # Terraform
                "tf_show",
                "tf_state_list",
                "tf_plan",
                # git / GitHub
                "git_repo_status",
                "git_log",
                "git_diff",
                "gh_prs",
                # GitHub Actions (Phase 8)
                "gh_runs",
                "gh_run_view",
                "gh_workflows",
                # Kubernetes depth (Phase 8)
                "k8s_pods",
                "k8s_top_pods",
                "k8s_top_nodes",
                "k8s_hpa",
                "k8s_pvc",
                "k8s_contexts",
                # Docker depth (Phase 8)
                "docker_networks",
                "docker_volumes",
                "docker_disk_usage",
                # Cloud identity (Phase 8)
                "aws_identity",
                "gcloud_identity",
                "az_account",
                "az_groups",
                # Monitoring / logging (Phase 8)
                "prom_query",
                "loki_query",
                "grafana_health",
                # Ansible listing (Phase 8)
                "ansible_inventory",
                "ansible_playbook_tasks",
            },
        )

    def test_schema_shape(self):
        tool = next(t for t in get_tools() if t.name == "system_info")
        schema = tool.schema()
        self.assertEqual(schema["type"], "function")
        fn = schema["function"]
        self.assertEqual(fn["name"], "system_info")
        self.assertIn("description", fn)
        self.assertEqual(fn["parameters"]["type"], "object")
        enum = fn["parameters"]["properties"]["command"]["enum"]
        self.assertIn("date_utc", enum)
        self.assertNotIn("rm", enum)

    def test_execute_valid_command(self):
        result = execute_tool("system_info", '{"command": "uname"}')
        self.assertTrue(result.startswith("$ uname -a"))
        self.assertIn("Linux", result)

    def test_execute_rejects_non_allowlisted_command(self):
        # Proof the model cannot smuggle arbitrary commands through arguments:
        # the call must fail with an error, never run anything.
        result = execute_tool("system_info", '{"command": "rm -rf /"}')
        self.assertTrue(result.startswith("Tool error"))
        self.assertIn("unknown command", result)
        self.assertEqual(result.count("\n"), 0)  # single-line error, no output

    def test_execute_unknown_tool(self):
        result = execute_tool("definitely_not_a_tool", "{}")
        self.assertTrue(result.startswith("Tool error: unknown tool"))
        self.assertIn("system_info", result)

    def test_execute_bad_json_arguments(self):
        result = execute_tool("system_info", "{not json")
        self.assertTrue(result.startswith("Tool error: could not parse"))

    def test_execute_non_object_arguments(self):
        result = execute_tool("system_info", '["not", "an", "object"]')
        self.assertTrue(result.startswith("Tool error"))

    def test_execute_missing_required_argument(self):
        result = execute_tool("system_info", "{}")
        self.assertTrue(result.startswith("Tool error"))


class TruncationTests(unittest.TestCase):
    def test_short_output_untouched(self):
        self.assertEqual(truncate_output("short"), "short")

    def test_long_output_keeps_head_and_tail(self):
        text = "x" * 10_000
        cut = truncate_output(text, limit=200)
        self.assertLessEqual(len(cut), 200)  # total stays bounded
        self.assertTrue(cut.startswith("xx"))  # head kept
        self.assertTrue(cut.endswith("xx"))  # tail kept
        self.assertIn("characters omitted", cut)


class ToolUseLoopTests(unittest.TestCase):
    def make_agent(self, responses):
        agent = DevOpsAgent(api_key="sk-test-not-a-real-key")
        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=responses))
        return agent

    def test_loop_executes_tool_and_returns_final_answer(self):
        responses = FakeResponses([_tool_call_response(), _text_response("Reboot buddy.")])
        agent = self.make_agent(responses)

        answer = agent.ask("What OS is this host running? Use your tool.")

        self.assertEqual(answer, "Reboot buddy.")
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        # The assistant tool-request plus its result must be in history verbatim.
        echo = agent.messages[2]
        self.assertEqual(echo["tool_calls"][0]["id"], "call_1")
        self.assertEqual(echo["tool_calls"][0]["function"]["name"], "system_info")
        tool_msg = agent.messages[3]
        self.assertEqual(tool_msg["tool_call_id"], "call_1")
        self.assertIn("$ uname -a", tool_msg["content"])  # real output was used
        # Tool schemas were attached to the API request (all of them).
        self.assertIn("tools", responses.last_request)
        tool_names = [t["function"]["name"] for t in responses.last_request["tools"]]
        self.assertIn("system_info", tool_names)

    def test_ask_keeps_multi_turn_history(self):
        responses = FakeResponses(
            [_text_response("first"), _tool_call_response(), _text_response("second")]
        )
        agent = self.make_agent(responses)
        agent.ask("Q1")
        agent.ask("Q2")
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "tool", "assistant"])

    def test_loop_stops_after_max_iterations(self):
        responses = FakeResponses(
            [_tool_call_response() for _ in range(MAX_TOOL_ITERATIONS + 1)]
        )
        agent = self.make_agent(responses)
        with self.assertRaises(RuntimeError):
            agent.ask("keep calling tools forever")

    def test_system_prompt_loaded(self):
        responses = FakeResponses([_text_response("ok")])
        agent = self.make_agent(responses)
        self.assertEqual(agent.messages[0], {"role": "system", "content": SYSTEM_PROMPT})


if __name__ == "__main__":
    unittest.main()