"""Offline tests for Phase 12: streaming model output (REPL-only).

Run with:  .venv/bin/python -m unittest discover -s tests -v

No network calls and no API key needed. Streamed responses are faked as
iterators of chunk objects shaped like the OpenAI SDK's streaming chunks
(delta .content and .tool_calls fragments, keep-alive frames); text deltas
are captured by patching the agent.agent._emit seam instead of printing.
The non-streaming path is asserted unchanged — one-shot mode and every
earlier suite behave exactly as before.
"""

import unittest
from types import SimpleNamespace

import agent.agent as agent_module
from agent.agent import DevOpsAgent


# --- chunk builders ----------------------------------------------------------

def _text_chunk(text):
    """One streaming chunk carrying only text content."""
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
        content=text, tool_calls=None))])


def _tool_delta(index, id=None, name=None, arguments=None):
    """One streaming chunk carrying a tool-call fragment for `index`."""
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(
            index=index, id=id, type="function",
            function=SimpleNamespace(name=name, arguments=arguments),
        )],
    ))])


def _keepalive_chunk():
    return SimpleNamespace(choices=[])


def _text_turn(*pieces):
    """A scripted streaming turn: plain text arriving in pieces."""
    return [_text_chunk(piece) for piece in pieces]


class StreamChat:
    """Replaces client.chat.completions.create with a scripted turn list.

    Each scripted turn is either a str (a non-streaming reply) or a list of
    chunks (a streaming turn). create() pops turns in order and records the
    stream flag of every call, plus the last request for inspection.
    """

    def __init__(self, turns):
        self._turns = list(turns)
        self.stream_flags = []
        self.last_request = None

    def create(self, **kwargs):
        self.stream_flags.append(kwargs.get("stream", False))
        self.last_request = kwargs
        turn = self._turns.pop(0)
        if isinstance(turn, str):
            message = SimpleNamespace(content=turn, tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])
        return iter(turn)


def make_agent(turns):
    agent = DevOpsAgent(api_key="test-key-for-offline-tests")
    agent.client.chat.completions = StreamChat(turns)
    return agent


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        original = agent_module._emit
        agent_module._emit = self.emitted.append
        self.addCleanup(
            lambda original=original: setattr(agent_module, "_emit", original)
        )

    # --- text streaming -------------------------------------------------------

    def test_streamed_text_is_emitted_and_returned(self):
        agent = make_agent([_text_turn("checking ", "the host")])
        reply = agent.ask("what OS is this?", stream=True)
        self.assertEqual(reply, "checking the host")
        self.assertEqual(self.emitted, ["checking ", "the host"])
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertEqual(agent.messages[-1]["content"], "checking the host")

    def test_stream_flag_is_passed_to_the_client(self):
        agent = make_agent([_text_turn("ok")])
        agent.ask("hi", stream=True)
        self.assertEqual(agent.client.chat.completions.stream_flags, [True])

    def test_multi_turn_streamed_history(self):
        agent = make_agent([_text_turn("first"), _text_turn("second")])
        agent.ask("Q1", stream=True)
        agent.ask("Q2", stream=True)
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(
            roles, ["system", "user", "assistant", "user", "assistant"]
        )

    def test_non_streaming_calls_unchanged(self):
        agent = make_agent(["plain reply"])
        self.assertEqual(agent.ask("hi"), "plain reply")
        self.assertEqual(agent.client.chat.completions.stream_flags, [False])
        self.assertEqual(self.emitted, [])  # nothing emitted when not streaming

    # --- tool calls arrive as fragments ---------------------------------------

    def test_streamed_tool_call_fragments_are_reassembled_and_executed(self):
        turn = [
            _text_chunk("checking "),
            _tool_delta(0, id="call_1", name="system_info",
                        arguments='{"comm'),
            _tool_delta(0, arguments='and": "uname"}'),
            _keepalive_chunk(),
        ]
        agent = make_agent([turn, _text_turn("the host is Linux.")])
        reply = agent.ask("what OS? use your tool.", stream=True)
        self.assertEqual(reply, "the host is Linux.")
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertIn("uname", agent.messages[-2]["content"])
        # text streamed alongside the tool call reached _emit too
        self.assertIn("checking ", self.emitted)

    def test_parallel_tool_call_fragments_reassemble_by_index(self):
        # two interleaved call streams — fragments must not cross wires
        turn = [
            _tool_delta(0, id="call_a", name="system_info", arguments='{"comm'),
            _tool_delta(1, id="call_b", name="system_info", arguments='{"comm'),
            _tool_delta(0, arguments='and": "uname"}'),
            _tool_delta(1, arguments='and": "uname"}'),
        ]
        agent = make_agent([turn, _text_turn("both done")])
        agent.ask("two calls", stream=True)
        tool_messages = [m for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 2)
        self.assertEqual({m["tool_call_id"] for m in tool_messages},
                         {"call_a", "call_b"})
        self.assertTrue(all("uname" in m["content"] for m in tool_messages))

    def test_keepalive_chunks_with_no_choices_are_ignored(self):
        agent = make_agent([[_keepalive_chunk(), _text_chunk("ok"),
                             _keepalive_chunk()]])
        self.assertEqual(agent.ask("hi", stream=True), "ok")

    def test_empty_stream_raises_like_the_sync_path(self):
        agent = make_agent([[]])
        with self.assertRaises(RuntimeError):
            agent.ask("hi", stream=True)


if __name__ == "__main__":
    unittest.main()
