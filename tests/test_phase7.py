"""Offline tests for Phase 7 persistence: the investigation record survives
CLI exits.

Run with:  .venv/bin/python -m unittest discover -s tests -v

Four layers, all network-free:
1. RoundTripTests — to_dict/from_dict on the pure data model in
   agent/investigation.py.
2. StoreTests — agent/store.py: file creation, in-place updates, resume,
   listing, corrupt/unwritable tolerance.
3. WiringTests — the mutation chokepoint in tools/investigation.py
   auto-saves; resume works through the shared functions.
4. CliTests — the CLI flags (--store-dir/--resume/--out), the
   /investigations command, and the auto-resume notice.

No test touches the real home directory: every store under test is pointed
at a tempdir, and set_store(None) disables persistence everywhere else.
"""

import contextlib
import datetime as _dt
import io
import json
import os
import shutil
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import main as main_module
from agent import store as store_module
from agent.agent import DevOpsAgent
from agent.investigation import Investigation, InvestigationError
from agent.store import InvestigationStore
from tools import investigation as inv_tools


def _concluded() -> Investigation:
    inv = Investigation("checkout pod crash-loops", ["bad image", "OOMKilled"])
    inv.verify_hypothesis("H1", "refuted", "image pulls cleanly")
    inv.record_evidence("exit code 1 in logs", "H2")
    inv.conclude(
        summary="entrypoint exits 1",
        root_cause="broken command in the image",
        remediation=["fix the CMD"],
        verification=["redeploy and watch restart count"],
        confidence="high",
    )
    return inv


class RoundTripTests(unittest.TestCase):
    """to_dict / from_dict — the serialization the store relies on."""

    def test_round_trip_preserves_state(self):
        inv = _concluded()
        restored = Investigation.from_dict(
            inv.to_dict(saved_at="2026-09-26T12:00:00")
        )
        self.assertEqual(restored.problem, inv.problem)
        self.assertEqual([h.id for h in restored.hypotheses], ["H1", "H2"])
        self.assertEqual(restored.hypotheses[0].status, "refuted")
        self.assertEqual(restored.hypotheses[0].notes, ["image pulls cleanly"])
        self.assertEqual(restored.evidence[0].hypothesis_id, "H2")
        self.assertEqual(
            restored.conclusion.root_cause, "broken command in the image"
        )
        # byte-identical views after the round trip
        self.assertEqual(restored.render_report(), inv.render_report())
        self.assertEqual(restored.render_report_json(), inv.render_report_json())

    def test_schema_and_saved_at_round_trip_as_metadata(self):
        data = _concluded().to_dict(saved_at="2026-09-26T12:00:00")
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["saved_at"], "2026-09-26T12:00:00")

    def test_ids_continue_after_restore(self):
        restored = Investigation.from_dict(_concluded().to_dict())
        self.assertEqual(
            restored.add_hypothesis("third candidate"),
            "recorded hypothesis H3: third candidate",
        )
        self.assertEqual(
            restored.record_evidence("more logs"),
            "recorded evidence E2: more logs",
        )

    def test_unknown_keys_are_tolerated(self):
        data = _concluded().to_dict()
        data["future_field"] = {"anything": True}
        Investigation.from_dict(data)  # must not raise

    def test_malformed_hypothesis_id_rejected(self):
        data = _concluded().to_dict()
        data["hypotheses"][0]["id"] = "X9"
        with self.assertRaises(InvestigationError):
            Investigation.from_dict(data)

    def test_invalid_hypothesis_status_rejected(self):
        data = _concluded().to_dict()
        data["hypotheses"][0]["status"] = "certainly"
        with self.assertRaises(InvestigationError):
            Investigation.from_dict(data)

    def test_dangling_evidence_link_rejected(self):
        data = _concluded().to_dict()
        data["evidence"][0]["hypothesis_id"] = "H9"
        with self.assertRaises(InvestigationError):
            Investigation.from_dict(data)

    def test_missing_problem_rejected(self):
        with self.assertRaises(KeyError):
            Investigation.from_dict({"hypotheses": []})


class StoreTests(unittest.TestCase):
    """agent/store.py — files, in-place updates, resume, listing, tolerance."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p7-store-")
        self.store = InvestigationStore(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_save_writes_slug_named_json(self):
        path = self.store.save(Investigation("Checkout Pod Crash-loops!"))
        self.assertIsNotNone(path)
        self.assertTrue(path.name.endswith("checkout-pod-crash-loops.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["problem"], "Checkout Pod Crash-loops!")
        self.assertEqual(data["status"], "in_progress")
        self.assertEqual(data["schema"], 1)
        self.assertIn("saved_at", data)

    def test_save_updates_same_file_in_place(self):
        inv = Investigation("one problem only")
        first = self.store.save(inv)
        inv.record_evidence("some evidence")
        second = self.store.save(inv)
        self.assertEqual(first, second)
        self.assertEqual(list(Path(self.tmp).glob("*.json")), [first])
        data = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(data["evidence"][0]["content"], "some evidence")

    def test_unslugifiable_problem_gets_fallback_name(self):
        path = self.store.save(Investigation("???"))
        self.assertIn("investigation", path.name)

    def test_second_investigation_same_second_gets_suffix(self):
        class _Fixed:
            class datetime:
                @staticmethod
                def now():
                    return _dt.datetime(2026, 9, 26, 12, 0, 0)

        with mock.patch.object(store_module, "datetime", _Fixed):
            self.store.save(Investigation("duplicate problem"))
            self.store.forget()
            second = self.store.save(Investigation("duplicate problem"))
        self.assertIsNotNone(second)
        self.assertTrue(second.name.endswith("-2.json"))
        self.assertEqual(len(list(Path(self.tmp).glob("*.json"))), 2)

    def test_resume_latest_skips_concluded_and_corrupt(self):
        self.store.save(Investigation("older in-progress"))
        self.store.forget()
        newer = Investigation("newer concluded")
        newer.conclude(summary="s", root_cause="r", remediation=["x"],
                       verification=["y"], confidence="low")
        self.store.save(newer)
        (Path(self.tmp) / "99999999-999999-garbage.json").write_text("{not json")
        resumed = self.store.resume_latest()
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed.problem, "older in-progress")
        # subsequent saves update the resumed file, not a new one
        resumed.record_evidence("after resume")
        self.store.save(resumed)
        self.assertEqual(len(list(Path(self.tmp).glob("*.json"))), 3)

    def test_resume_none_when_only_concluded(self):
        self.store.save(_concluded())
        self.assertIsNone(self.store.resume_latest())

    def test_list_saved_newest_first(self):
        self.store.save(Investigation("alpha problem"))
        self.store.forget()
        self.store.save(Investigation("beta problem"))
        rows = self.store.list_saved()
        self.assertEqual(
            [r["problem"] for r in rows], ["beta problem", "alpha problem"]
        )
        self.assertEqual(rows[0]["status"], "in_progress")
        self.assertIn("saved_at", rows[0])

    def test_list_and_resume_skip_corrupt_files(self):
        (Path(self.tmp) / "20260101-000000-broken.json").write_text("[]")
        self.store.save(Investigation("good one"))
        self.assertEqual(
            [r["problem"] for r in self.store.list_saved()], ["good one"]
        )
        self.assertIsNotNone(self.store.resume_latest())


@unittest.skipIf(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    "root can write anywhere, so the unwritable case cannot be simulated",
)
class UnwritableStoreTests(unittest.TestCase):
    """A broken store degrades to None — it must never break an investigation."""

    def test_save_degrades_to_none(self):
        d = tempfile.mkdtemp(prefix="p7-locked-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.addCleanup(os.chmod, d, 0o755)  # LIFO: runs before the rmtree
        os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)  # r-x: readable, not writable
        store = InvestigationStore(d)
        self.assertIsNone(store.save(Investigation("cannot save this")))
        self.assertIsNone(store.save(Investigation("still cannot")))
        self.assertEqual(store.list_saved(), [])


class WiringTests(unittest.TestCase):
    """The mutation chokepoint auto-saves; resume works through the tools."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p7-wire-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(inv_tools.set_store, None)
        self.addCleanup(inv_tools.finish_investigation)
        inv_tools.set_store(InvestigationStore(self.tmp))

    def test_start_and_record_save_with_note(self):
        result = inv_tools.start_investigation("api-5d6f stuck rollout")
        self.assertIn("(saved to", result)
        self.assertEqual(len(list(Path(self.tmp).glob("*.json"))), 1)
        result = inv_tools.record(kind="evidence", content="image pull fails")
        self.assertIn("(saved to", result)
        data = json.loads(next(Path(self.tmp).glob("*.json")).read_text())
        self.assertEqual(data["evidence"][0]["content"], "image pull fails")

    def test_conclude_updates_saved_status(self):
        inv_tools.start_investigation("api-5d6f stuck rollout")
        inv_tools.conclude_investigation(
            summary="s", root_cause="r", remediation=["x"], verification=["y"]
        )
        data = json.loads(next(Path(self.tmp).glob("*.json")).read_text())
        self.assertEqual(data["status"], "concluded")

    def test_finish_keeps_file_and_frees_the_path(self):
        inv_tools.start_investigation("keep me")
        path = next(Path(self.tmp).glob("*.json"))
        inv_tools.finish_investigation()
        self.assertTrue(path.exists())  # the saved copy remains as history
        self.assertIsNone(inv_tools._get_store().current_file)
        # a new investigation gets its own file
        inv_tools.start_investigation("fresh one")
        self.assertEqual(len(list(Path(self.tmp).glob("*.json"))), 2)

    def test_resume_through_chokepoint(self):
        inv_tools.start_investigation("first problem", ["h1"])
        inv_tools.record(kind="evidence", content="e1")
        inv_tools.finish_investigation()
        inv_tools.start_investigation("second problem")
        inv_tools.conclude_investigation(
            summary="s", root_cause="r", remediation=["x"], verification=["y"]
        )
        inv_tools.finish_investigation()

        notice = inv_tools.resume_investigation()
        self.assertIn("first problem", notice)
        self.assertIn("E1", inv_tools.status_text())
        # already active -> nothing to resume
        self.assertIsNone(inv_tools.resume_investigation())

    def test_disabled_store_saves_nothing(self):
        inv_tools.set_store(None)
        result = inv_tools.start_investigation("unsaved")
        self.assertNotIn("(saved to", result)
        self.assertIsNone(inv_tools.list_saved_text())


class StubChat:
    """Drop-in replacement for client.chat: returns one plain-text reply."""

    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        message = types.SimpleNamespace(content=self._content, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )


class CliTests(unittest.TestCase):
    """parse_args, run_one_shot flags, and the /investigations command."""

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-for-offline-tests"
        self.agent = DevOpsAgent()
        self.agent.client.chat.completions = StubChat("investigation complete.")
        self.addCleanup(self._restore)
        inv_tools.set_store(None)

    def _restore(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

    def _run(self, task, as_json=False, store_dir=None, resume=False, out=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main_module.run_one_shot(
                task,
                as_json=as_json,
                agent=self.agent,
                store_dir=store_dir,
                resume=resume,
                out=out,
            )
        return code, buf.getvalue()

    # --- parse_args -----------------------------------------------------------

    def test_parse_args_defaults(self):
        self.assertEqual(
            main_module.parse_args([]), (None, False, None, False, None, None)
        )
        self.assertEqual(
            main_module.parse_args(["why is it down?"]),
            ("why is it down?", False, None, False, None, None),
        )

    def test_parse_args_all_flags(self):
        args = main_module.parse_args(
            ["--json", "--resume", "--store-dir", "/tmp/s", "--out", "r.json",
             "why", "is it down?"]
        )
        self.assertEqual(
            args, ("why is it down?", True, "/tmp/s", True, "r.json", None))

    def test_parse_args_flags_only_runs_repl(self):
        self.assertEqual(
            main_module.parse_args(["--json", "--resume"]),
            (None, True, None, True, None, None),
        )

    def test_parse_args_flag_without_value_is_ignored(self):
        self.assertEqual(
            main_module.parse_args(["--store-dir"]),
            (None, False, None, False, None, None),
        )

    # --- --store-dir ----------------------------------------------------------

    def test_store_dir_propagates_and_autosaves(self):
        tmp = tempfile.mkdtemp(prefix="p7-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        code, _ = self._run("hello", store_dir=tmp)
        self.assertEqual(code, 0)
        self.assertEqual(self.agent.store_dir, str(Path(tmp)))
        # auto-save writes there as soon as a record exists
        inv_tools.start_investigation("saved by the cli-configured store")
        files = list(Path(tmp).glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["problem"], "saved by the cli-configured store")

    # --- /investigations ------------------------------------------------------

    def test_investigations_command_lists_and_marks_active(self):
        tmp = tempfile.mkdtemp(prefix="p7-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.agent.use_store_dir(tmp)
        inv_tools.start_investigation("sshd is not accepting connections")
        listed = main_module.handle_command("/investigations", self.agent)
        self.assertIn("sshd is not accepting connections", listed)
        self.assertIn("<- active", listed)
        main_module.handle_command("/endinvestigation", self.agent)
        listed = main_module.handle_command("/investigations", self.agent)
        self.assertIn("sshd is not accepting connections", listed)  # file remains
        self.assertNotIn("<- active", listed)

    def test_investigations_command_empty(self):
        tmp = tempfile.mkdtemp(prefix="p7-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.agent.use_store_dir(tmp)
        self.assertEqual(
            main_module.handle_command("/investigations", self.agent),
            "(no saved investigations yet)",
        )

    # --- --out ----------------------------------------------------------------

    def test_out_writes_report_file_markdown_on_stdout(self):
        inv_tools.start_investigation("checkout pod crash-loops")
        inv_tools.conclude_investigation(
            summary="s",
            root_cause="command exits immediately",
            remediation="fix",
            verification="verify",
            confidence="high",
        )
        target = Path(tempfile.mkdtemp(prefix="p7-out-")) / "report.json"
        self.addCleanup(shutil.rmtree, str(target.parent), ignore_errors=True)
        code, stdout = self._run("report it", as_json=False, out=str(target))
        self.assertEqual(code, 0)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["conclusion"]["root_cause"], "command exits immediately")
        self.assertIn("investigation complete.", stdout)  # markdown, not json

    def test_out_without_investigation_fails_loud(self):
        target = Path(tempfile.mkdtemp(prefix="p7-out-")) / "report.json"
        self.addCleanup(shutil.rmtree, str(target.parent), ignore_errors=True)
        code, _ = self._run("hello", out=str(target))
        self.assertEqual(code, 1)
        self.assertFalse(target.exists())

    def test_json_and_out_together(self):
        inv_tools.start_investigation("checkout pod crash-loops")
        inv_tools.conclude_investigation(
            summary="s", root_cause="r", remediation="fix",
            verification="verify", confidence="low",
        )
        target = Path(tempfile.mkdtemp(prefix="p7-out-")) / "report.json"
        self.addCleanup(shutil.rmtree, str(target.parent), ignore_errors=True)
        code, stdout = self._run("go", as_json=True, out=str(target))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), json.loads(target.read_text()))

    # --- --resume -------------------------------------------------------------

    def test_resume_flag_continues_saved_record(self):
        tmp = tempfile.mkdtemp(prefix="p7-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        # seed a store file via the tools (the same path the CLI would use)
        inv_tools.set_store(InvestigationStore(tmp))
        inv_tools.start_investigation("api-5d6f rollout is stuck", ["registry"])
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

        code, _ = self._run("any update?", store_dir=tmp, resume=True)
        self.assertEqual(code, 0)
        status = inv_tools.status_text()
        self.assertIn("api-5d6f rollout is stuck", status)
        self.assertIn("H1 [proposed] registry", status)

    def test_fresh_run_does_not_resume(self):
        tmp = tempfile.mkdtemp(prefix="p7-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inv_tools.set_store(InvestigationStore(tmp))
        inv_tools.start_investigation("older problem")
        inv_tools.finish_investigation()
        inv_tools.set_store(None)

        code, _ = self._run("a new question", store_dir=tmp)
        self.assertEqual(code, 0)
        self.assertIsNone(inv_tools.status_text())  # nothing was resumed


if __name__ == "__main__":
    unittest.main()
