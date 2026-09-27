"""Offline tests for Phase 11: conversation-history persistence.

Run with:  .venv/bin/python -m unittest discover -s tests -v

No network calls and no API key needed — the model client is stubbed the
same way the Phase 2 loop tests do it. Persistence tests point every store
at a tempdir (AGENT_CHAT_DIR / set_chat_store(None) hygiene), mirroring the
Phase 7 investigation-persistence suite.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import main as main_module
import tools.investigation as inv_tools
from agent import chat_store
from agent.agent import DevOpsAgent
from agent.chat_store import ChatStore, prune_messages
from agent.prompts import SYSTEM_PROMPT
from agent.store import InvestigationStore


class StubChat:
    """Drop-in replacement for client.chat: returns one plain-text reply."""

    def __init__(self, content: str = "ok"):
        self._content = content
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content=self._content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _agent_with(client):
    agent = DevOpsAgent(api_key="test-key-for-offline-tests")
    agent.client.chat.completions = client
    return agent


class ChatStoreTests(unittest.TestCase):
    """save / resume_latest / close / list — the storage primitives."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="p11-store-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        chat_store.set_chat_store(None)  # never touch the real home directory
        self.addCleanup(chat_store.set_chat_store, None)

    def test_save_and_resume_round_trip(self):
        store = ChatStore(self.dir)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "why is api down?"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "evidence"},
            {"role": "assistant", "content": "found it"},
        ]
        path = store.save(messages, investigation_file="20260927-120000-slug.json")
        self.assertIsNotNone(path)

        loaded = ChatStore(self.dir).resume_latest()
        self.assertIsNotNone(loaded)
        restored, inv_file = loaded
        self.assertEqual(restored, messages)  # exact, including the tool exchange
        self.assertEqual(inv_file, "20260927-120000-slug.json")

    def test_save_updates_same_file_in_place(self):
        store = ChatStore(self.dir)
        store.save([{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "first question"}])
        first = store.current_file
        store.save([{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "answer"}])
        self.assertEqual(store.current_file, first)  # one file per conversation
        self.assertEqual(len(list(Path(self.dir).glob("*.json"))), 1)

    def test_resume_latest_skips_closed_and_corrupt(self):
        older = ChatStore(self.dir)
        older.save([{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "old one"}])
        older.close_current()
        (Path(self.dir) / "20260101-000000-broken.json").write_text(
            "{not json", encoding="utf-8"
        )
        newest = ChatStore(self.dir)
        newest.save([{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": "the open one"}])
        loaded = ChatStore(self.dir).resume_latest()
        restored, _ = loaded
        self.assertEqual(restored[-1]["content"], "the open one")

    def test_close_current_marks_closed_and_untracks(self):
        store = ChatStore(self.dir)
        store.save([{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "close me"}])
        name = store.current_file
        store.close_current()
        self.assertIsNone(store.current_file)
        data = json.loads((Path(self.dir) / name).read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "closed")
        # the file remains as history but no longer auto-restores
        loaded = ChatStore(self.dir).resume_latest()
        self.assertIsNone(loaded)

    def test_resume_latest_rejects_bad_message_shapes(self):
        store = ChatStore(self.dir)
        store.directory.mkdir(parents=True, exist_ok=True)
        (store.directory / "20260101-000000-bad.json").write_text(
            json.dumps({"schema": 1, "status": "open",
                        "messages": ["not", "dicts"]}),
            encoding="utf-8",
        )
        self.assertIsNone(ChatStore(self.dir).resume_latest())

    def test_list_saved_reports_turns_and_first_message(self):
        store = ChatStore(self.dir)
        store.save([{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "answer"},
                    {"role": "user", "content": "second question"}])
        rows = ChatStore(self.dir).list_saved()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["turns"], 2)
        self.assertEqual(rows[0]["first_message"], "first question")
        self.assertEqual(rows[0]["status"], "open")

    def test_unwritable_dir_degrades_to_none(self):
        if os.geteuid() == 0:
            self.skipTest("root can write read-only dirs; skipped as root")
        readonly = Path(tempfile.mkdtemp(prefix="p11-ro-"))
        self.addCleanup(readonly.chmod, 0o755)
        readonly.chmod(0o555)
        store = ChatStore(readonly / "conversations")
        self.assertIsNone(store.save([{"role": "user", "content": "x"}]))


class PruneTests(unittest.TestCase):
    """History pruning cuts whole user-started turns, never a tool exchange."""

    def _turn(self, n, with_tools=False):
        msgs = [{"role": "user", "content": f"q{n}"},
                {"role": "assistant", "content": f"a{n}"}]
        if with_tools:
            msgs = [
                {"role": "user", "content": f"q{n}"},
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": f"c{n}"}]},
                {"role": "tool", "tool_call_id": f"c{n}", "content": "e"},
                {"role": "assistant", "content": f"a{n}"},
            ]
        return msgs

    def test_under_the_cap_untouched(self):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += self._turn(1) + self._turn(2, with_tools=True)
        self.assertEqual(prune_messages(messages, max_turns=40), messages)

    def test_over_the_cap_keeps_newest_whole_turns(self):
        system = {"role": "system", "content": SYSTEM_PROMPT}
        messages = [system]
        for n in range(5):
            messages += self._turn(n, with_tools=n % 2 == 0)
        kept = prune_messages(messages, max_turns=2)
        # system prompt + exactly the newest 2 user-started turns
        self.assertEqual(kept[0], system)
        users = [m["role"] for m in kept if m["role"] == "user"]
        self.assertEqual(users, ["user", "user"])
        self.assertEqual(kept[-1]["content"], "a4")
        # a tool exchange never loses its assistant request or result
        self.assertIn(
            "tool", [m["role"] for m in kept],
            "the kept tail must include the full final tool exchange",
        )
        self.assertEqual(kept[1]["role"], "user")  # history starts at a user turn

    def test_prune_handles_history_without_user_turn(self):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.assertEqual(prune_messages(messages), messages)


class ConversationPersistenceTests(unittest.TestCase):
    """ask() auto-saves; resume_session() restores chat + linked investigation."""

    def setUp(self):
        self.chat_dir = tempfile.mkdtemp(prefix="p11-chat-")
        self.inv_dir = tempfile.mkdtemp(prefix="p11-inv-")
        self.addCleanup(shutil.rmtree, self.chat_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.inv_dir, ignore_errors=True)
        chat_store.set_chat_store(ChatStore(self.chat_dir))
        inv_tools.set_store(None)
        self.addCleanup(chat_store.set_chat_store, None)
        self.addCleanup(inv_tools.set_store, None)
        self.addCleanup(inv_tools.finish_investigation)

    def test_ask_autosaves_the_exchange(self):
        agent = _agent_with(StubChat("here is the answer"))
        agent.ask("why is the api pod crash-looping?")
        rows = ChatStore(self.chat_dir).list_saved()
        self.assertEqual(len(rows), 1)
        data = json.loads(
            (Path(self.chat_dir) / rows[0]["file"]).read_text(encoding="utf-8")
        )
        roles = [m["role"] for m in data["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertEqual(data["investigation_file"], None)

    def test_ask_links_the_active_investigation_file(self):
        agent = _agent_with(StubChat("recorded"))
        agent.use_store_dir(self.inv_dir)
        inv_tools.start_investigation("api pod crash-looping")
        agent.ask("gather evidence")
        data = json.loads(
            (Path(self.chat_dir) / ChatStore(self.chat_dir).list_saved()[0]["file"]
             ).read_text(encoding="utf-8")
        )
        self.assertIsNotNone(data["investigation_file"])
        inv_name = data["investigation_file"]
        # the linked name is a real investigation file in the inv store
        self.assertIn(inv_name, [p.name for p in Path(self.inv_dir).glob("*.json")])

    def test_disabled_chat_store_saves_nothing(self):
        chat_store.set_chat_store(None)
        agent = _agent_with(StubChat("fine"))
        agent.ask("anything")
        self.assertIsNone(chat_store._get_chat_store())
        self.assertIsNone(chat_store.list_conversations_text())

    def test_resume_session_restores_messages_and_linked_investigation(self):
        # session 1: investigate + chat, then the process exits (globals reset)
        first = _agent_with(StubChat("first session reply"))
        first.use_store_dir(self.inv_dir)
        inv_tools.start_investigation("api pod crash-looping")
        first.ask("why is the api pod crash-looping?")
        inv_tools.finish_investigation()  # simulate the CLI exit

        # session 2: a fresh agent restores both
        second = _agent_with(StubChat("continuing"))
        notice = second.resume_session()
        self.assertIsNotNone(notice)
        self.assertIn("Conversation restored", notice)
        self.assertIn("Resumed:", notice)
        roles = [m["role"] for m in second.messages]
        self.assertEqual(
            roles, ["system", "user", "assistant"],
            "restored history must replay the saved exchange",
        )
        self.assertIn("api pod crash-looping", inv_tools.status_text())
        # the restored conversation keeps saving to the same file
        second.ask("and the node?")
        self.assertEqual(len(list(Path(self.chat_dir).glob("*.json"))), 1)

    def test_resume_session_falls_back_to_investigation_only(self):
        # a Phase 7-style record with no conversation file
        inv_tools.set_store(InvestigationStore(self.inv_dir))
        inv_tools.start_investigation("orphaned record")
        inv_tools.finish_investigation()  # simulate the CLI exit
        agent = _agent_with(StubChat("ok"))
        notice = agent.resume_session()
        self.assertIsNotNone(notice)
        self.assertIn("orphaned record", notice)
        self.assertEqual(agent.messages, [{"role": "system", "content": SYSTEM_PROMPT}])

    def test_resume_session_none_when_nothing_saved(self):
        agent = _agent_with(StubChat("ok"))
        self.assertIsNone(agent.resume_session())

    def test_new_chat_clears_history_and_closes(self):
        agent = _agent_with(StubChat("reply"))
        agent.ask("hello")
        result = agent.new_chat()
        self.assertIn("history cleared", result)
        self.assertEqual(agent.messages,
                         [{"role": "system", "content": SYSTEM_PROMPT}])
        # closed -> will not auto-restore on the next session
        self.assertIsNone(ChatStore(self.chat_dir).resume_latest())

    def test_new_chat_keeps_active_investigation(self):
        agent = _agent_with(StubChat("reply"))
        agent.use_store_dir(self.inv_dir)
        inv_tools.start_investigation("keep me")
        agent.ask("working on it")
        result = agent.new_chat()
        self.assertIn("active investigation is untouched", result)
        self.assertIn("keep me", inv_tools.status_text())


class CliPhase11Tests(unittest.TestCase):
    """/conversations, /newchat, and --resume in one-shot mode."""

    def setUp(self):
        self._old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-for-offline-tests"
        self.chat_dir = tempfile.mkdtemp(prefix="p11-cli-")
        self.inv_dir = tempfile.mkdtemp(prefix="p11-cli-inv-")
        self.addCleanup(shutil.rmtree, self.chat_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.inv_dir, ignore_errors=True)
        chat_store.set_chat_store(ChatStore(self.chat_dir))
        self.addCleanup(chat_store.set_chat_store, None)
        inv_tools.set_store(None)
        self.addCleanup(inv_tools.set_store, None)
        self.addCleanup(inv_tools.finish_investigation)
        self.agent = _agent_with(StubChat("cli reply"))

    def _run(self, task, resume=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main_module.run_one_shot(
                task, agent=self.agent, store_dir=self.inv_dir, resume=resume
            )
        return code, buf.getvalue()

    def test_conversations_command_lists_and_starts_empty(self):
        self.assertEqual(
            main_module.handle_command("/conversations", self.agent),
            "(no saved conversations yet)",
        )
        self.agent.ask("what broke?")
        listed = main_module.handle_command("/conversations", self.agent)
        self.assertIn("what broke?", listed)
        self.assertIn("<- active", listed)

    def test_newchat_command_clears_and_restores_nothing(self):
        self.agent.ask("what broke?")
        result = main_module.handle_command("/newchat", self.agent)
        self.assertIn("history cleared", result)
        self.assertEqual(self.agent.messages,
                         [{"role": "system", "content": SYSTEM_PROMPT}])
        self.assertIsNone(self.agent.resume_session())

    def test_one_shot_resume_restores_conversation(self):
        # session 1: one exchange via one-shot
        code, _ = self._run("what broke yesterday?")
        self.assertEqual(code, 0)
        # session 2: --resume restores the chat before asking
        code, _ = self._run("any update?", resume=True)
        self.assertEqual(code, 0)
        roles = [m["role"] for m in self.agent.messages]
        self.assertEqual(
            roles, ["system", "user", "assistant", "user", "assistant"],
            "--resume must replay the restored conversation before the new ask",
        )
        self.assertIn("what broke yesterday?", [m["content"] for m in self.agent.messages])

    def test_unknown_command_mentions_new_commands(self):
        unknown = main_module.handle_command("/wat", self.agent)
        self.assertIn("/conversations", unknown)
        self.assertIn("/newchat", unknown)


if __name__ == "__main__":
    unittest.main()