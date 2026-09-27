"""Offline tests for the Phase 9 tool expansion (New Relic, Trivy, Helm,
Argo CD, Istio, Docker Compose).

Run with:  .venv/bin/python -m unittest discover -s tests -v

Same strategy as Phases 5/8: stub binaries on PATH echo their arguments, so
tests assert the EXACT argv the application built — and that invalid image
refs, release names, project names or unconfigured credentials are rejected
with a Tool error *without the binary ever being invoked*. The New Relic
tests also prove the credentials and payload come from environment
configuration (and fail honestly when unset).
"""

import json
import os
import shutil
import stat
import tempfile
import unittest

import agent.agent  # noqa: F401  # registers every tool via side-effect imports
from tools.registry import execute_tool


class FakeBins:
    """A temp dir of stub executables (echo "ARGS: $*") placed first on PATH."""

    def __init__(self, *names: str):
        self._dir = tempfile.mkdtemp(prefix="p9-bins-")
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


class Phase9TestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bins = None
        self._env_snapshot = {
            k: os.environ.get(k)
            for k in ("NEW_RELIC_API_KEY", "NEW_RELIC_ACCOUNT_ID")
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


class NewRelicTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("curl")

    def test_unset_credentials_are_an_honest_error(self):
        for tool, var in (
            ("newrelic_nrql", "NEW_RELIC_API_KEY"),
            ("newrelic_alerts", "NEW_RELIC_API_KEY"),
        ):
            result = self.run_tool(tool, '{"query": "SELECT 1"}')
            self.assertTrue(result.startswith("Tool error"), (tool, result))
            self.assertIn(var, result)
            self.assertNotIn("ARGS:", result)  # curl was never invoked
        os.environ["NEW_RELIC_API_KEY"] = "nrk-test"
        result = self.run_tool("newrelic_nrql", '{"query": "SELECT 1"}')
        self.assertIn("NEW_RELIC_ACCOUNT_ID", result)
        self.assertNotIn("ARGS:", result)

    def test_non_digit_account_id_rejected(self):
        os.environ["NEW_RELIC_API_KEY"] = "nrk-test"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "my-account"
        result = self.run_tool("newrelic_nrql", '{"query": "SELECT 1"}')
        self.assertTrue(result.startswith("Tool error"), result)
        self.assertIn("numeric", result)
        self.assertNotIn("ARGS:", result)

    def test_nrql_query_pinned_curl_and_payload(self):
        os.environ["NEW_RELIC_API_KEY"] = "nrk-test-key"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "1234567"
        result = self.run_tool(
            "newrelic_nrql",
            '{"query": "SELECT count(*) FROM Transaction SINCE 1 hour ago"}',
        )
        self.assertTrue(
            result.startswith("$ curl -sS --max-time 15 -H API-Key: nrk-test-key "
                              "-H content-type: application/json -d "),
            result,
        )
        # The -d payload is one argv element between "-d" and the URL:
        # take everything from the first '{"query"' to the trailing URL.
        line = result.splitlines()[0]
        payload = line[line.index('{"query"'):].rsplit(" https://", 1)[0]
        data = json.loads(payload)
        self.assertEqual(data["variables"]["accountId"], 1234567)
        self.assertEqual(
            data["variables"]["nrql"],
            "SELECT count(*) FROM Transaction SINCE 1 hour ago",
        )
        self.assertIn("nrql(query: $nrql)", data["query"])
        self.assertIn("https://api.newrelic.com/graphql", result)

    def test_alerts_payload_ignores_model_args(self):
        # No model input reaches the payload — a no-injection proof.
        os.environ["NEW_RELIC_API_KEY"] = "nrk-test"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "42"
        result = self.run_tool("newrelic_alerts", '{"evil": "drop tables"}')
        line = result.splitlines()[0]
        payload = line[line.index('{"query"'):].rsplit(" https://", 1)[0]
        data = json.loads(payload)
        self.assertEqual(data["variables"], {"accountId": 42})
        self.assertNotIn("evil", result)
        self.assertIn("incidents(filter: {states: [ACTIVE, ACKNOWLEDGED]})",
                      data["query"])

    def test_nrql_validation(self):
        os.environ["NEW_RELIC_API_KEY"] = "nrk-test"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "42"
        for bad in ('{"query": ""}', '{"query": "   "}',
                    '{"query": "' + "x" * 501 + '"}'):
            result = self.run_tool("newrelic_nrql", bad)
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)


class TrivyTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("trivy")

    def test_scan_argv(self):
        result = self.run_tool("trivy_image_scan", '{"image": "nginx:1.27"}')
        self.assertTrue(
            result.startswith(
                "$ trivy image --scanners vuln --format table nginx:1.27"
            ),
            result,
        )
        result = self.run_tool(
            "trivy_image_scan",
            '{"image": "registry.example.com/team/api:v2"}',
        )
        self.assertIn("registry.example.com/team/api:v2", result)

    def test_invalid_image_refs_rejected(self):
        for bad in ("-q", "img; rm -rf /", "img extra", "", "x" * 201,
                    "nginx@...", "-format json"):
            result = self.run_tool("trivy_image_scan", f'{{"image": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)  # trivy was never invoked


class HelmTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("helm")

    def test_list_default_and_all_namespaces(self):
        result = self.run_tool("helm_list", "{}")
        self.assertTrue(result.startswith("$ helm list -n default"), result)
        result = self.run_tool(
            "helm_list", '{"all_namespaces": true, "namespace": "prod"}'
        )
        self.assertTrue(result.startswith("$ helm list --all-namespaces"), result)
        result = self.run_tool("helm_list", '{"namespace": "prod"}')
        self.assertTrue(result.startswith("$ helm list -n prod"), result)

    def test_status_and_history_argv(self):
        result = self.run_tool(
            "helm_status", '{"release": "api", "namespace": "prod"}'
        )
        self.assertTrue(result.startswith("$ helm status api -n prod"), result)
        result = self.run_tool(
            "helm_history", '{"release": "api", "max": 20}'
        )
        self.assertTrue(
            result.startswith("$ helm history api -n default --max 20"), result
        )

    def test_invalid_release_names_rejected(self):
        for bad in ("-n", "a b", "UPPER", "x" * 300, ""):
            for tool in ("helm_status", "helm_history"):
                result = self.run_tool(tool, f'{{"release": "{bad}"}}')
                self.assertTrue(result.startswith("Tool error"), (tool, bad, result))
                self.assertNotIn("ARGS:", result)  # helm was never invoked

    def test_invalid_max_rejected(self):
        for bad in ("0", "51", '"ten"'):
            result = self.run_tool(
                "helm_history", f'{{"release": "api", "max": {bad}}}'
            )
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)


class ArgoCDTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("argocd")

    def test_apps_argv(self):
        result = self.run_tool("argocd_apps", "{}")
        self.assertTrue(result.startswith("$ argocd app list --output json"), result)

    def test_app_status_argv(self):
        result = self.run_tool("argocd_app_status", '{"app": "checkout-prod"}')
        self.assertTrue(result.startswith("$ argocd app get checkout-prod"), result)

    def test_invalid_app_names_rejected(self):
        for bad in ("--help", "a b", "x" * 300, ""):
            result = self.run_tool("argocd_app_status", f'{{"app": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)


class IstioTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("istioctl")

    def test_proxy_status_no_arguments(self):
        result = self.run_tool("istioctl_proxy_status", "{}")
        self.assertTrue(result.startswith("$ istioctl proxy-status"), result)


class ComposeTests(Phase9TestCase):
    def setUp(self):
        super().setUp()
        self.stub("docker")

    def test_compose_ls(self):
        result = self.run_tool("docker_compose_ls", "{}")
        self.assertTrue(result.startswith("$ docker compose ls"), result)

    def test_compose_ps_default_and_project(self):
        result = self.run_tool("docker_compose_ps", "{}")
        self.assertTrue(result.startswith("$ docker compose ps -a"), result)
        result = self.run_tool("docker_compose_ps", '{"project": "webapp"}')
        self.assertTrue(
            result.startswith("$ docker compose -p webapp ps -a"), result
        )

    def test_invalid_project_names_rejected(self):
        for bad in ("rm -rf /", "-p", "a/b", "has space"):
            result = self.run_tool("docker_compose_ps", f'{{"project": "{bad}"}}')
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("ARGS:", result)


class RegistryPhase9Tests(Phase9TestCase):
    def test_phase9_tools_all_registered(self):
        from tools.registry import get_tools

        names = {tool.name for tool in get_tools()}
        expected = {
            "newrelic_nrql", "newrelic_alerts",
            "trivy_image_scan",
            "helm_list", "helm_status", "helm_history",
            "argocd_apps", "argocd_app_status",
            "istioctl_proxy_status",
            "docker_compose_ls", "docker_compose_ps",
        }
        self.assertLessEqual(expected, names)
        self.assertEqual(len(names), 61)


if __name__ == "__main__":
    unittest.main()
