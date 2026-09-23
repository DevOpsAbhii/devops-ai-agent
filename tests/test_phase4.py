"""Offline tests for the Phase 4 investigation loop.

Run with:  .venv/bin/python -m unittest discover -s tests -v

Three layers, all network-free:
1. InvestigationStateTests — the pure data model in agent/investigation.py
   (hypotheses, verdicts, evidence links, conclude, report rendering).
2. InvestigationToolTests — the meta-tools: lifecycle through the tool
   functions, "no active investigation" behaviour, registry presence.
3. InvestigationLoopTest — the full tool-use loop with a fake client: the
   model opens an investigation, records a verdict, concludes, and answers;
   the tracked state must exist in the application afterwards.
"""

import json
import unittest
from types import SimpleNamespace

from agent.investigation import Investigation, InvestigationError
from tools.investigation import (
    conclude_investigation,
    finish_investigation,
    record,
    report_text,
    start_investigation,
    status_text,
)
from tools.registry import execute_tool, get_tools


class InvestigationStateTests(unittest.TestCase):
    """The pure data model — no tools, no globals."""

    def test_empty_problem_rejected(self):
        with self.assertRaises(InvestigationError):
            Investigation("   ")

    def test_initial_hypotheses_get_sequential_ids(self):
        inv = Investigation("pod is crashing", ["bad image", "wrong env"])
        self.assertEqual([h.id for h in inv.hypotheses], ["H1", "H2"])
        self.assertEqual([h.status for h in inv.hypotheses], ["proposed", "proposed"])

    def test_add_hypothesis_and_verdict(self):
        inv = Investigation("pod is crashing")
        inv.add_hypothesis("liveness probe is misconfigured")
        self.assertEqual(inv.hypotheses[0].id, "H1")
        inv.verify_hypothesis("H1", "refuted", note="probe exists and passes")
        self.assertEqual(inv.hypotheses[0].status, "refuted")
        self.assertIn("probe exists and passes", inv.hypotheses[0].notes)

    def test_invalid_verdict_status_rejected(self):
        inv = Investigation("x")
        inv.add_hypothesis("h")
        with self.assertRaises(InvestigationError):
            inv.verify_hypothesis("H1", "probably")

    def test_unknown_hypothesis_id_rejected(self):
        inv = Investigation("x")
        with self.assertRaises(InvestigationError):
            inv.verify_hypothesis("H9", "confirmed")
        with self.assertRaises(InvestigationError):
            inv.record_evidence("some log line", hypothesis_id="H9")

    def test_evidence_records_with_pairing(self):
        inv = Investigation("x")
        inv.add_hypothesis("h")
        inv.record_evidence("logs show exit 1", hypothesis_id="H1")
        self.assertEqual(inv.evidence[0].id, "E1")
        self.assertEqual(inv.evidence[0].hypothesis_id, "H1")

    def test_conclude_requires_fields(self):
        inv = Investigation("x")
        with self.assertRaises(InvestigationError):
            conclude_with_bad_confidence(inv)
        with self.assertRaises(InvestigationError):
            conclude_with_empty_remediation(inv)

    def test_conclude_and_report_renders_all_sections(self):
        inv = Investigation("checkout pod CrashLoopBackOff", ["bad image"])
        inv.record_evidence("restartCount climbing; exit code 1", hypothesis_id="H1")
        inv.conclude(
            summary="The image entrypoint exits immediately.",
            root_cause="The container image's command exits with code 1 at startup.",
            remediation=["Fix the image entrypoint", "Add a liveness probe"],
            verification=["kubectl rollout restart", "await Running with restartCount stable"],
            confidence="high",
        )
        self.assertIsNotNone(inv.conclusion)
        report = inv.render_report()
        for section in (
            "# Investigation report",
            "**Problem:** checkout pod CrashLoopBackOff",
            "## Facts / evidence",
            "## Hypotheses",
            "- **H1** [proposed] bad image",  # never verified in this test
            "## Root cause",
            "## Remediation (recommendations — nothing was executed)",
            "## Verification steps",
            "**Confidence:** high",
        ):
            self.assertIn(section, report)

    def test_report_falls_back_to_tracker_before_conclusion(self):
        inv = Investigation("x")
        self.assertTrue(inv.render_report().startswith("**Investigation tracker**"))


def conclude_with_bad_confidence(inv):
    inv.conclude(summary="s", root_cause="c", remediation=["r"],
                 verification=["v"], confidence="certainly")


def conclude_with_empty_remediation(inv):
    inv.conclude(summary="s", root_cause="c", remediation=[],
                 verification=["v"], confidence="medium")


class InvestigationToolTests(unittest.TestCase):
    """Meta-tools: lifecycle + misuse, through the shared functions/registry."""

    def setUp(self):
        finish_investigation()

    def tearDown(self):
        finish_investigation()

    def test_tools_are_registered(self):
        names = {tool.name for tool in get_tools()}
        self.assertIn("investigation_begin", names)
        self.assertIn("investigation_record", names)
        self.assertIn("investigation_conclude", names)

    def test_record_without_active_investigation_errors(self):
        result = execute_tool(
            "investigation_record", json.dumps({"kind": "hypothesis", "content": "x"})
        )
        self.assertTrue(result.startswith("Tool error: no active investigation"), result)

    def test_conclude_without_active_investigation_errors(self):
        with self.assertRaisesRegex(Exception, "no active investigation"):
            conclude_investigation(
                summary="s", root_cause="c", remediation=["r"], verification=["v"]
            )

    def test_full_lifecycle_via_tool_functions(self):
        start_investigation("pod CrashLoopBackOff", ["bad image", "OOMKilled"])
        # Hypothesis ids came from `initial_hypotheses`; update one to a verdict.
        verdict = record(
            kind="verdict", hypothesis_id="H1", status="refuted",
            content="image exists and pulled fine",
        )
        self.assertIn("H1 is now [refuted]", verdict)
        self.assertIn("**Investigation tracker**", verdict)  # live state returned
        evidence = record(
            kind="evidence", content="kubelet: exit code 1", hypothesis_id="H2"
        )
        self.assertIn("E1", evidence)
        status = status_text()
        self.assertIn("H2 [proposed]", status)
        conclusion = conclude_investigation(
            summary="Entrypoint exits immediately.",
            root_cause="The image command exits with code 1 at startup.",
            remediation=["Fix the image entrypoint"],
            verification=["check restartCount stays flat for 5m"],
            confidence="high",
        )
        self.assertIn("investigation concluded", conclusion)
        report = report_text()
        self.assertIn("# Investigation report", report)
        self.assertIn("**Confidence:** high", report)
        self.assertEqual(finish_investigation(), "investigation cleared")
        self.assertIsNone(status_text())

    def test_unknown_kind_rejected(self):
        start_investigation("x", ["h"])
        with self.assertRaises(Exception) as ctx:
            record(kind="banana", content="nonsense")
        self.assertIn("expected hypothesis | evidence | verdict", str(ctx.exception))


class InvestigationLoopTest(unittest.TestCase):
    """The tool-use loop drives the investigation, like the real model would."""

    def setUp(self):
        finish_investigation()

    def tearDown(self):
        finish_investigation()

    def _tool_response(self, name, args, call_id="call_1"):
        call = SimpleNamespace(
            id=call_id,
            type="function",
            function=SimpleNamespace(name=name, arguments=json.dumps(args)),
        )
        message = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _text_response(self, text):
        message = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def test_loop_tracks_investigation_and_concludes(self):
        from agent.agent import DevOpsAgent

        responses = [
            self._tool_response("investigation_begin", {
                "problem": "checkout pod is CrashLoopBackOff",
                "initial_hypotheses": ["bad image", "exiting entrypoint"],
            }),
            self._tool_response("investigation_record", {
                "kind": "verdict", "hypothesis_id": "H1", "status": "refuted",
                "content": "image pulls cleanly",
            }),
            self._tool_response("investigation_conclude", {
                "summary": "The entrypoint exits immediately.",
                "root_cause": "The image command exits with code 1.",
                "remediation": ["Fix the entrypoint", "add a liveness probe"],
                "verification": ["rollout restart", "restartCount flat"],
                "confidence": "high",
            }),
            self._text_response("Diagnosis complete. The report below summarises the tracking."),
        ]
        class _Seq:
            def __init__(self, items): self._items = list(items); self.calls = 0
            def create(self, **kwargs):
                self.calls += 1
                return self._items.pop(0)

        fake = _Seq(responses)
        agent = DevOpsAgent(api_key="sk-test-not-a-real-key")
        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))

        answer = agent.ask("Investigate: the checkout pod is CrashLoopBackOff.")

        self.assertIn("Diagnosis complete", answer)
        # The application holds a first-class record of the whole investigation.
        self.assertEqual(fake.calls, 4)  # 3 tool turns + final answer
        self.assertEqual(agent.messages[1], {
            "role": "user",
            "content": "Investigate: the checkout pod is CrashLoopBackOff.",
        })
        # State persisted outside the model: the tracker shows the verdict the
        # model delivered through investigation_record.
        tracker = status_text()
        self.assertIn("Status: concluded (confidence high)", tracker)
        self.assertIn("- H1 [refuted] bad image", tracker)

        report = report_text()
        self.assertIn("## Hypotheses", report)
        self.assertIn("- **H1** [refuted] bad image", report)
        self.assertIn("The entrypoint exits immediately.", report)


if __name__ == "__main__":
    unittest.main()