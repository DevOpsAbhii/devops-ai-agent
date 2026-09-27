"""Offline tests for the Phase 5 tool expansion (Linux, Docker, k8s depth,
Terraform, git/gh).

Run with:  .venv/bin/python -m unittest discover -s tests -v

Strategy (same as Phase 3's fake kubectl): each test class puts tiny stub
binaries on PATH for the CLIs its module uses. A stub just echoes its
arguments, so the tests assert the EXACT argv template that the application
built — and that invalid names/arguments are rejected with a Tool error
*without the binary ever being invoked*.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest

import agent.agent  # noqa: F401  # registers every tool via side-effect imports
from tools.registry import execute_tool


class FakeBins:
    """A temp dir of stub executables (echo "ARGS: $*") placed first on PATH."""

    def __init__(self, *names: str):
        self._dir = tempfile.mkdtemp(prefix="p5-bins-")
        self._prev_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self._dir}:{self._prev_path}"
        for name in names:
            path = os.path.join(self._dir, name)
            with open(path, "w") as fh:
                fh.write('#!/bin/sh\necho "ARGS: $*"\n')
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def close(self):
        os.environ["PATH"] = self._prev_path
        shutil.rmtree(self._dir, ignore_errors=True)


class Phase5TestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bins = None

    def tearDown(self):
        if self.bins is not None:
            self.bins.close()
        super().tearDown()

    def stub(self, *names: str) -> None:
        self.bins = FakeBins(*names)

    def run_tool(self, name: str, args: str) -> str:
        return execute_tool(name, args)


class SystemToolTests(Phase5TestCase):
    def setUp(self):
        super().setUp()
        self.stub("systemctl", "journalctl", "ss", "ps")

    def test_service_status_command(self):
        result = self.run_tool("sys_service_status", '{"unit": "docker.service"}')
        self.assertTrue(
            result.startswith("$ systemctl status docker.service --no-pager"),
            result,
        )

    def test_service_logs_default_and_custom_lines(self):
        result = self.run_tool("sys_service_logs", '{"unit": "sshd"}')
        self.assertIn("journalctl -u sshd --no-pager -n 100", result)
        result = self.run_tool(
            "sys_service_logs", '{"unit": "ssh@0.0.0.0:22", "lines": 25}'
        )
        self.assertIn("journalctl -u ssh@0.0.0.0:22 --no-pager -n 25", result)

    def test_service_logs_invalid_lines_rejected(self):
        for bad in ("0", "501", "-3"):
            result = self.run_tool("sys_service_logs", f'{{"unit": "sshd", "lines": {bad}}}')
            self.assertTrue(result.startswith("Tool error"), result)
            self.assertNotIn("ARGS:", result)  # journalctl was never invoked

    def test_unit_name_validation(self):
        for bad in ("/etc/passwd", "-l", "a b", "x" * 256):
            result = self.run_tool("sys_service_status", f'{{"unit": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), result)
            self.assertNotIn("ARGS:", result)

    def test_open_ports_command(self):
        result = self.run_tool("sys_open_ports", "{}")
        self.assertTrue(result.startswith("$ ss -tlnp"), result)

    def test_top_processes_command(self):
        result = self.run_tool("sys_top_processes", "{}")
        self.assertTrue(result.startswith("$ ps aux --sort=-%cpu --no-headers"), result)


class DockerToolTests(Phase5TestCase):
    def setUp(self):
        super().setUp()
        self.stub("docker")

    def test_docker_ps_command(self):
        self.assertTrue(self.run_tool("docker_ps", "{}").startswith("$ docker ps -a"))

    def test_docker_inspect_command(self):
        result = self.run_tool("docker_inspect", '{"name": "web.1_abc"}')
        self.assertTrue(result.startswith("$ docker inspect web.1_abc"), result)

    def test_docker_logs_command_and_lines(self):
        result = self.run_tool("docker_logs", '{"container": "web1"}')
        self.assertTrue(result.startswith("$ docker logs --tail 100 web1"), result)
        result = self.run_tool("docker_logs", '{"container": "web1", "lines": 5}')
        self.assertTrue(result.startswith("$ docker logs --tail 5 web1"), result)

    def test_docker_stats_always_no_stream(self):
        # The one docker verb that would block forever without --no-stream.
        result = self.run_tool("docker_stats", "{}")
        self.assertTrue(result.startswith("$ docker stats --no-stream"), result)

    def test_docker_images_command(self):
        self.assertTrue(self.run_tool("docker_images", "{}").startswith("$ docker images"))

    def test_container_name_validation(self):
        for bad in ("rm -rf /", "-l", "a/b", "has space", "x" * 200):
            result = self.run_tool("docker_inspect", f'{{"name": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), result)
            self.assertNotIn("ARGS:", result)

    def test_docker_logs_invalid_lines_rejected(self):
        result = self.run_tool("docker_logs", '{"container": "web1", "lines": 0}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertNotIn("ARGS:", result)


class KubernetesDepthTests(Phase5TestCase):
    def setUp(self):
        super().setUp()
        self.stub("kubectl")

    def test_events_default_argv(self):
        result = self.run_tool("k8s_events", "{}")
        self.assertTrue(
            result.startswith(
                "$ kubectl get events -n default --sort-by=.lastTimestamp "
                "-o wide --request-timeout=10"
            ),
            result,
        )

    def test_events_involving_filter(self):
        result = self.run_tool("k8s_events", '{"namespace": "prod", "involving": "web-7d9c"}')
        self.assertIn("--field-selector involvedObject.name=web-7d9c", result)
        self.assertIn("-n prod", result)

    def test_events_invalid_involving_rejected(self):
        result = self.run_tool("k8s_events", '{"involving": "-n"}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertNotIn("ARGS:", result)

    def test_nodes_command(self):
        result = self.run_tool("k8s_nodes", "{}")
        self.assertTrue(result.startswith("$ kubectl get nodes -o json --request-timeout=10"), result)

    def test_services_command_and_namespace(self):
        result = self.run_tool("k8s_services", "{}")
        self.assertTrue(
            result.startswith("$ kubectl get services -n default -o json --request-timeout=10"),
            result,
        )
        result = self.run_tool("k8s_services", '{"namespace": "kube-system"}')
        self.assertTrue(result.startswith("$ kubectl get services -n kube-system"), result)


class TerraformToolTests(Phase5TestCase):
    def setUp(self):
        super().setUp()
        self.stub("terraform")

    def test_show_command(self):
        self.assertTrue(self.run_tool("tf_show", "{}").startswith("$ terraform show -no-color"))

    def test_state_list_command(self):
        self.assertTrue(self.run_tool("tf_state_list", "{}").startswith("$ terraform state list"))

    def test_plan_command_pinned_safe_flags(self):
        # -input=false is what keeps plan from ever sitting on a prompt.
        result = self.run_tool("tf_plan", "{}")
        self.assertTrue(
            result.startswith("$ terraform plan -no-color -input=false"), result
        )


class GitCIToolTests(Phase5TestCase):
    def setUp(self):
        super().setUp()
        self.stub("git", "gh")

    def test_repo_status_command(self):
        result = self.run_tool("git_repo_status", "{}")
        self.assertTrue(result.startswith("$ git status --short --branch"), result)

    def test_git_log_default_and_custom(self):
        result = self.run_tool("git_log", "{}")
        self.assertTrue(result.startswith("$ git log --oneline -n 20"), result)
        result = self.run_tool("git_log", '{"count": 3}')
        self.assertTrue(result.startswith("$ git log --oneline -n 3"), result)

    def test_git_diff_command(self):
        self.assertTrue(self.run_tool("git_diff", "{}").startswith("$ git diff --stat HEAD"))

    def test_gh_prs_default_and_limit(self):
        result = self.run_tool("gh_prs", "{}")
        self.assertTrue(
            result.startswith(
                "$ gh pr list --limit 10 --json number,title,state,headRefName,isDraft,updatedAt"
            ),
            result,
        )
        result = self.run_tool("gh_prs", '{"limit": 3}')
        self.assertTrue(result.startswith("$ gh pr list --limit 3"), result)

    def test_invalid_counters_rejected(self):
        for args in ('{"count": 0}', '{"count": 500}', '{"limit": "ten"}'):
            name = "git_log" if "count" in args else "gh_prs"
            result = self.run_tool(name, args)
            self.assertTrue(result.startswith("Tool error"), (name, args, result))
            self.assertNotIn("ARGS:", result)


class RegistryTests(Phase5TestCase):
    def test_all_phase5_tools_registered(self):
        from tools.registry import get_tools

        names = {tool.name for tool in get_tools()}
        # Phase 8 added 21 tools on top of Phase 5's 26 (full set asserted
        # in tests/test_phase2.py); here we check the Phase 5 tools plus the
        # total count the registry must hold after Phase 8.
        phase5_tools = {
            "system_info",
            "k8s_pod_status", "k8s_pod_logs", "k8s_deployment_status",
            "k8s_events", "k8s_nodes", "k8s_services",
            "sys_service_status", "sys_service_logs", "sys_open_ports",
            "sys_top_processes",
            "docker_ps", "docker_inspect", "docker_logs", "docker_stats",
            "docker_images",
            "tf_show", "tf_state_list", "tf_plan",
            "git_repo_status", "git_log", "git_diff", "gh_prs",
            "investigation_begin", "investigation_record", "investigation_conclude",
        }
        self.assertLessEqual(phase5_tools, names)
        self.assertEqual(len(names), 61)


if __name__ == "__main__":
    unittest.main()