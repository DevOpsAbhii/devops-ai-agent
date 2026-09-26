"""Offline tests for the Phase 8 tool expansion (k8s depth, Docker depth,
GitHub Actions, cloud identity, monitoring, Ansible).

Run with:  .venv/bin/python -m unittest discover -s tests -v

Same strategy as Phases 3/5: stub binaries on PATH echo their arguments, so
tests assert the EXACT argv the application built — and that invalid names,
ids, paths or unconfigured endpoints are rejected with a Tool error *without
the binary ever being invoked*. No network is touched; the monitoring tests
prove the endpoint comes from environment configuration (and fail honestly
when it is unset).
"""

import os
import shutil
import stat
import tempfile
import unittest

import agent.agent  # noqa: F401  # registers every tool via side-effect imports
from tools.registry import execute_tool
from tools.base import ToolError
from tools.monitoring import _endpoint


class FakeBins:
    """A temp dir of stub executables (echo "ARGS: $*") placed first on PATH."""

    def __init__(self, *names: str):
        self._dir = tempfile.mkdtemp(prefix="p8-bins-")
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


class Phase8TestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bins = None
        self._env_snapshot = {
            k: os.environ.get(k)
            for k in ("PROMETHEUS_URL", "LOKI_URL", "GRAFANA_URL")
        }
        for k in self._env_snapshot:
            os.environ.pop(k, None)

    def tearDown(self):
        if self.bins is not None:
            self.bins.close()
        for k, v in self._env_snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def stub(self, *names: str) -> None:
        self.bins = FakeBins(*names)

    def run_tool(self, name: str, args: str) -> str:
        return execute_tool(name, args)


class KubernetesPhase8Tests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("kubectl")

    def test_pods_argv_and_namespace(self):
        result = self.run_tool("k8s_pods", "{}")
        self.assertTrue(
            result.startswith("$ kubectl get pods -n default -o wide "
                              "--request-timeout=10"),
            result,
        )
        result = self.run_tool("k8s_pods", '{"namespace": "prod"}')
        self.assertTrue(result.startswith("$ kubectl get pods -n prod"), result)

    def test_top_pods_default_and_sort(self):
        result = self.run_tool("k8s_top_pods", "{}")
        self.assertTrue(
            result.startswith("$ kubectl top pods -n default --request-timeout=10"),
            result,
        )
        result = self.run_tool(
            "k8s_top_pods", '{"namespace": "prod", "sort_by": "memory"}'
        )
        self.assertTrue(
            result.startswith("$ kubectl top pods -n prod --sort-by=memory"),
            result,
        )
        result = self.run_tool("k8s_top_pods", '{"sort_by": "cpu"}')
        self.assertIn("--sort-by=cpu", result)

    def test_top_pods_invalid_sort_rejected(self):
        for bad in ("disk", "n; rm -rf /", ""):
            result = self.run_tool("k8s_top_pods", f'{{"sort_by": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)  # kubectl was never invoked

    def test_top_nodes_argv(self):
        result = self.run_tool("k8s_top_nodes", "{}")
        self.assertTrue(
            result.startswith("$ kubectl top nodes --request-timeout=10"), result
        )

    def test_hpa_list_and_named(self):
        result = self.run_tool("k8s_hpa", "{}")
        self.assertTrue(
            result.startswith("$ kubectl get hpa -n default -o json "
                              "--request-timeout=10"),
            result,
        )
        result = self.run_tool(
            "k8s_hpa", '{"name": "api-hpa", "namespace": "prod"}'
        )
        self.assertTrue(
            result.startswith("$ kubectl get hpa api-hpa -n prod -o json"), result
        )

    def test_pvc_list_and_named(self):
        result = self.run_tool("k8s_pvc", '{"name": "data-0"}')
        self.assertTrue(
            result.startswith("$ kubectl get pvc data-0 -n default -o json"), result
        )

    def test_hpa_pvc_invalid_names_rejected(self):
        for name in ("-o", "x y", "UPPER", "x" * 300):
            result = self.run_tool("k8s_hpa", f'{{"name": "{name}"}}')
            self.assertTrue(result.startswith("Tool error"), (name, result))
            self.assertNotIn("ARGS:", result)
            result = self.run_tool("k8s_pvc", f'{{"name": "{name}"}}')
            self.assertTrue(result.startswith("Tool error"), (name, result))
            self.assertNotIn("ARGS:", result)

    def test_contexts_is_a_listing_only(self):
        result = self.run_tool("k8s_contexts", "{}")
        self.assertTrue(
            result.startswith("$ kubectl config get-contexts"), result
        )
        # the mutating sibling verb must be unreachable by construction
        self.assertNotIn("use-context", result)


class DockerPhase8Tests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("docker")

    def test_networks_volumes_disk_usage(self):
        self.assertTrue(
            self.run_tool("docker_networks", "{}").startswith("$ docker network ls")
        )
        self.assertTrue(
            self.run_tool("docker_volumes", "{}").startswith("$ docker volume ls")
        )
        self.assertTrue(
            self.run_tool("docker_disk_usage", "{}").startswith("$ docker system df")
        )

    def test_no_mutating_verb_is_reachable(self):
        for tool in ("docker_networks", "docker_volumes", "docker_disk_usage"):
            result = self.run_tool(tool, "{}")
            for verb in ("rm", "prune", "create", "up", "down"):
                self.assertNotIn(f" {verb}", result, (tool, result))


class GitActionsTests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("gh")

    def test_gh_runs_default_and_limit(self):
        result = self.run_tool("gh_runs", "{}")
        self.assertTrue(
            result.startswith(
                "$ gh run list --limit 10 --json databaseId,displayTitle,status,"
                "conclusion,workflowName,createdAt,event,headBranch"
            ),
            result,
        )
        result = self.run_tool("gh_runs", '{"limit": 3}')
        self.assertTrue(result.startswith("$ gh run list --limit 3"), result)

    def test_gh_run_view_uses_the_id(self):
        result = self.run_tool("gh_run_view", '{"run_id": "1234567890"}')
        self.assertTrue(
            result.startswith(
                "$ gh run view 1234567890 --json status,conclusion,jobs"
            ),
            result,
        )

    def test_gh_run_id_must_be_digits(self):
        for bad in ("-1", "abc", "12; rm -rf /", "--jobs", "1 2", "x" * 21, ""):
            result = self.run_tool("gh_run_view", f'{{"run_id": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)  # gh was never invoked

    def test_gh_workflows_default_and_limit(self):
        result = self.run_tool("gh_workflows", "{}")
        self.assertTrue(
            result.startswith("$ gh workflow list --limit 20 --json id,name,state"),
            result,
        )
        result = self.run_tool("gh_workflows", '{"limit": 200}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertNotIn("ARGS:", result)


class CloudToolTests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("aws", "gcloud", "az")

    def test_aws_identity_argv(self):
        result = self.run_tool("aws_identity", "{}")
        self.assertTrue(
            result.startswith("$ aws sts get-caller-identity --output json"), result
        )

    def test_gcloud_identity_argv(self):
        result = self.run_tool("gcloud_identity", "{}")
        self.assertTrue(
            result.startswith("$ gcloud config list --format=json"), result
        )

    def test_az_account_and_groups(self):
        self.assertTrue(
            self.run_tool("az_account", "{}").startswith("$ az account show")
        )
        self.assertTrue(
            self.run_tool("az_groups", "{}").startswith("$ az group list")
        )

    def test_no_arguments_are_ever_passed(self):
        # The cloud tools take no user/model input at all — so nothing can be
        # injected. Any args the model sends are simply ignored by design.
        for tool in ("aws_identity", "gcloud_identity", "az_account", "az_groups"):
            result = self.run_tool(tool, '{"evil": "--profile hacker"}')
            self.assertNotIn("evil", result, (tool, result))


class MonitoringToolTests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("curl")

    def test_unset_endpoint_is_an_honest_error(self):
        for tool, var in (
            ("prom_query", "PROMETHEUS_URL"),
            ("loki_query", "LOKI_URL"),
            ("grafana_health", "GRAFANA_URL"),
        ):
            result = self.run_tool(tool, '{"query": "up"}')
            self.assertTrue(result.startswith("Tool error"), (tool, result))
            self.assertIn(var, result)
            self.assertNotIn("ARGS:", result)  # curl was never invoked

    def test_unsafe_endpoint_scheme_rejected(self):
        os.environ["PROMETHEUS_URL"] = "file:///etc/passwd"
        result = self.run_tool("prom_query", '{"query": "up"}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertNotIn("ARGS:", result)

    def test_endpoint_reader_strips_trailing_slash(self):
        os.environ["PROMETHEUS_URL"] = "http://prom:9090/"
        self.assertEqual(_endpoint("PROMETHEUS_URL"), "http://prom:9090")

    def test_prom_query_pinned_curl_and_encoded_query(self):
        os.environ["PROMETHEUS_URL"] = "http://prometheus:9090"
        result = self.run_tool(
            "prom_query", '{"query": "sum(rate(http_errors[5m])) by (job)"}'
        )
        self.assertTrue(
            result.startswith("$ curl -fsS --max-time 10 --proto =https,http "
                              "-H Accept:application/json "),
            result,
        )
        self.assertIn(
            "http://prometheus:9090/api/v1/query?query="
            "sum%28rate%28http_errors%5B5m%5D%29%29%20by%20%28job%29",
            result,
        )

    def test_loki_query_limit_bounds(self):
        os.environ["LOKI_URL"] = "https://loki:3100"
        result = self.run_tool(
            "loki_query", '{"query": "{app=\\"api\\"}", "limit": 25}'
        )
        self.assertIn("https://loki:3100/loki/api/v1/query?", result)
        self.assertIn("limit=25", result)
        for bad in ("0", "1001", '"ten"'):
            result = self.run_tool(
                "loki_query", f'{{"query": "{{}}", "limit": {bad}}}'
            )
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)

    def test_grafana_health_fixed_path(self):
        os.environ["GRAFANA_URL"] = "https://grafana.example.com"
        result = self.run_tool("grafana_health", "{}")
        self.assertIn("https://grafana.example.com/api/health", result)

    def test_empty_and_oversized_queries_rejected(self):
        os.environ["PROMETHEUS_URL"] = "http://prom:9090"
        for bad in ('{"query": ""}', '{"query": "   "}'):
            result = self.run_tool("prom_query", bad)
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)
        result = self.run_tool("prom_query", '{"query": "' + "x" * 501 + '"}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertNotIn("ARGS:", result)


class AnsibleToolTests(Phase8TestCase):
    def setUp(self):
        super().setUp()
        self.stub("ansible-inventory", "ansible-playbook")

    def test_inventory_default_and_named(self):
        result = self.run_tool("ansible_inventory", "{}")
        self.assertTrue(result.startswith("$ ansible-inventory --list"), result)
        result = self.run_tool("ansible_inventory", '{"inventory": "prod.ini"}')
        self.assertTrue(
            result.startswith("$ ansible-inventory --inventory prod.ini --list"),
            result,
        )

    def test_playbook_tasks_argv(self):
        result = self.run_tool("ansible_playbook_tasks", '{"playbook": "site.yml"}')
        self.assertTrue(
            result.startswith(
                "$ ansible-playbook --list-tasks --list-hosts site.yml"
            ),
            result,
        )

    def test_path_traversal_and_absolute_paths_rejected(self):
        for bad in ("../site.yml", "/etc/passwd", "-e hack=1", "a/b.yml",
                    "a/b/c", "..", ""):
            result = self.run_tool(
                "ansible_playbook_tasks", f'{{"playbook": "{bad}"}}'
            )
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)  # ansible-playbook never invoked
            if bad and "/" not in bad:
                result = self.run_tool(
                    "ansible_inventory", f'{{"inventory": "{bad}"}}'
                )
                self.assertTrue(result.startswith("Tool error"), (bad, result))
                self.assertNotIn("ARGS:", result)


class RegistryPhase8Tests(Phase8TestCase):
    def test_phase8_tools_all_registered(self):
        from tools.registry import get_tools

        names = {tool.name for tool in get_tools()}
        expected = {
            # Kubernetes depth
            "k8s_pods", "k8s_top_pods", "k8s_top_nodes",
            "k8s_hpa", "k8s_pvc", "k8s_contexts",
            # Docker depth
            "docker_networks", "docker_volumes", "docker_disk_usage",
            # GitHub Actions
            "gh_runs", "gh_run_view", "gh_workflows",
            # Cloud identity
            "aws_identity", "gcloud_identity", "az_account", "az_groups",
            # Monitoring / logging
            "prom_query", "loki_query", "grafana_health",
            # Ansible listing
            "ansible_inventory", "ansible_playbook_tasks",
        }
        self.assertLessEqual(expected, names)
        self.assertEqual(len(names), 47)


if __name__ == "__main__":
    unittest.main()
