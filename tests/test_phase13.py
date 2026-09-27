"""Offline tests for Phase 13: region-scoped cloud resource tools.

Run with:  .venv/bin/python -m unittest discover -s tests -v

Same strategy as Phases 3/5/8: stub binaries on PATH echo their arguments,
so tests assert the EXACT argv the application built — and that invalid
region/zone/group names are rejected with a Tool error *without the binary
ever being invoked*. No network is touched.
"""

import os
import shutil
import stat
import tempfile
import unittest

import agent.agent  # noqa: F401  # registers every tool via side-effect imports
from tools.base import ToolError
from tools.registry import execute_tool, get_tools


class FakeBins:
    """A temp dir of stub executables (echo "ARGS: $*") placed first on PATH."""

    def __init__(self, *names: str):
        self._dir = tempfile.mkdtemp(prefix="p13-bins-")
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


class Phase13TestCase(unittest.TestCase):
    def setUp(self):
        self.bins = None
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.bins is not None:
            self.bins.close()

    def stub(self, *names: str) -> None:
        self.bins = FakeBins(*names)

    def run_tool(self, name: str, args: str) -> str:
        return execute_tool(name, args)


class AwsInstancesTests(Phase13TestCase):
    def setUp(self):
        super().setUp()
        self.stub("aws")

    def test_region_argv(self):
        result = self.run_tool("aws_ec2_instances", '{"region": "us-east-1"}')
        self.assertIn("$ aws ec2 describe-instances --region us-east-1", result)
        self.assertIn("--output json", result)
        self.assertIn("--query", result)

    def test_missing_region_is_rejected(self):
        result = self.run_tool("aws_ec2_instances", "{}")
        self.assertTrue(result.startswith("Tool error"), result)

    def test_injection_attempts_are_rejected_without_invoking_aws(self):
        for bad in (
            '{"region": "--output text; rm -rf /"}',
            '{"region": "us-east-1 --role-arn evil"}',
            '{"region": "US East"}',
            '{"region": "../../secrets"}',
        ):
            result = self.run_tool("aws_ec2_instances", bad)
            # rejected before the CLI ever runs (no "$ aws ..." echo) — the
            # error may quote the rejected name, but the stub never executed
            self.assertTrue(result.startswith("Tool error"), (bad, result))
            self.assertNotIn("$ aws", result)


class GcloudInstancesTests(Phase13TestCase):
    def setUp(self):
        super().setUp()
        self.stub("gcloud")

    def test_zone_argv(self):
        result = self.run_tool(
            "gcloud_compute_instances", '{"zone": "us-central1-a"}'
        )
        self.assertIn("$ gcloud compute instances list", result)
        self.assertIn("--zones=us-central1-a", result)

    def test_missing_zone_is_rejected(self):
        result = self.run_tool("gcloud_compute_instances", "{}")
        self.assertTrue(result.startswith("Tool error"), result)


class AzVmTests(Phase13TestCase):
    def setUp(self):
        super().setUp()
        self.stub("az")

    def test_group_argv(self):
        result = self.run_tool("az_vm_list", '{"group": "rg-prod-east"}')
        self.assertIn("$ az vm list -g rg-prod-east -d --output json", result)

    def test_missing_group_is_rejected(self):
        result = self.run_tool("az_vm_list", "{}")
        self.assertTrue(result.startswith("Tool error"), result)


class RegistryPhase13Tests(Phase13TestCase):
    def test_tools_are_registered(self):
        names = {tool.name for tool in get_tools()}
        self.assertIn("aws_ec2_instances", names)
        self.assertIn("gcloud_compute_instances", names)
        self.assertIn("az_vm_list", names)

    def test_schemas_require_their_single_argument(self):
        for name, param in (
            ("aws_ec2_instances", "region"),
            ("gcloud_compute_instances", "zone"),
            ("az_vm_list", "group"),
        ):
            tool = next(t for t in get_tools() if t.name == name)
            self.assertEqual(tool.parameters["required"], [param])
            self.assertFalse(tool.parameters["additionalProperties"])

    def test_descriptions_say_read_only(self):
        for name in ("aws_ec2_instances", "gcloud_compute_instances",
                     "az_vm_list"):
            tool = next(t for t in get_tools() if t.name == name)
            self.assertIn("read-only", tool.description.lower())


if __name__ == "__main__":
    unittest.main()
