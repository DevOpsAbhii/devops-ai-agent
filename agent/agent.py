"""Core agent: the conversation + tool-use loop to the LLM backend.

Phase 2 builds the tool-use loop on top of the Phase 1 skeleton, Phase 4
adds the investigation loop on top of that, and Phase 5 broadens coverage
from Kubernetes-only to the wider DevOps surface:

    user reports a problem
      -> the model opens an investigation (investigation_begin)
      -> it gathers evidence with the read-only tools — Kubernetes,
         Linux systemd/journal/journal/ports/processes, Docker containers,
         Terraform state/plan, git/gh — tracking hypotheses and evidence in
         a first-class record (investigation_record)
      -> it concludes with root cause + remediation + verification
         (investigation_conclude), ending with a structured report

The tool-use loop itself is unchanged: every model call funnels through the
single `_complete()` chokepoint, and the investigation tools are just three
more registered tools — they persist state in agent/investigation.py, which
mutates nothing outside the agent's own memory. The read-only guarantee
holds: every tool is a fixed, allowlisted argv template; no tool can touch
a cluster, a file, or infrastructure beyond reading it.

Phase 7 makes that record durable: every mutation is auto-saved to the
InvestigationStore (agent/store.py), so the investigation survives CLI
exits; the delegates below expose resume/list/store-location to the CLI.
"""

import os
import random
import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from agent.chat_store import (
    chat_directory_text,
    close_conversation,
    list_conversations_text,
    load_resumable_conversation,
    prune_messages,
    save_conversation,
)
from agent.config import load_user_config
from agent.prompts import SYSTEM_PROMPT
from agent.store import InvestigationStore
from tools import (  # noqa: F401 — side effect: each module registers its tools
    ansible,
    argocd,
    cloud,
    docker,
    git_ci,
    helm,
    investigation,
    istio,
    kubernetes,
    monitoring,
    newrelic,
    preflight,
    system,
    terraform,
    trivy,
)
from tools.investigation import (
    finish_investigation,
    list_saved_text,
    report_json,
    report_text,
    current_investigation_file,
    resume_investigation as load_resumable_investigation,
    resume_investigation_file,
    set_store as set_investigation_store,
    start_investigation,
    status_text,
    store_directory_text,
)
from tools.registry import execute_tool, get_tools

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "z-ai/glm-5.3"
PLACEHOLDER_KEY = "your_key_here"

# Safety valve: the model gets at most this many tool-use turns before we stop.
MAX_TOOL_ITERATIONS = 10

# Transient-failure retries for the model call itself (network blips, 429,
# 5xx). MAX_MODEL_RETRIES attempts beyond the first, exponential backoff
# starting at RETRY_BASE_DELAY (2s -> 4s -> 8s) plus jitter, capped at
# RETRY_MAX_DELAY. A 429's Retry-After header wins when present.
MAX_MODEL_RETRIES = 3
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 60.0

_sleep = time.sleep  # test seam: offline tests patch agent.agent._sleep

# Streaming seam: where streamed text deltas are written. The REPL gets
# tokens as the model writes them; tests patch agent.agent._emit.
def _emit(text: str) -> None:
    print(text, end="", flush=True)


def _is_transient(exc: Exception) -> bool:
    """True when retrying `exc` can plausibly succeed.

    Timeouts, connection failures, rate limits, and server-side 5xx are
    transient. A rejected key (401) or any other client 4xx is not — the
    same request would fail identically forever, so it fails immediately.
    """
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


def _retry_delay(exc: Exception, attempt: int) -> float:
    """Seconds to wait before retry number `attempt` (0-based).

    Exponential backoff with jitter, except on a rate limit carrying a
    Retry-After header — the server knows its own budget, so it wins
    (clamped to [1, RETRY_MAX_DELAY] so a bad header cannot hurt us).
    """
    response = getattr(exc, "response", None)
    retry_after = getattr(response, "headers", {}).get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), RETRY_MAX_DELAY)
        except (TypeError, ValueError):
            pass  # non-numeric header: fall through to backoff
    return min(
        RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1),
        RETRY_MAX_DELAY,
    )


class DevOpsAgent:
    """Minimal DevOps investigation assistant (read-only by design)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        # Configuration resolution order: explicit argument > environment > default.
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")

        self.model = (
            model                                   # 1. explicit --model flag
            or load_user_config().get("model")      # 2. ~/.devops-ai-agent/config.json
            or os.getenv("OPENROUTER_MODEL")        # 3. environment / .env
            or DEFAULT_MODEL                        # 4. built-in default
        )
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)

        # Model-less mode: a missing (or placeholder) key no longer blocks
        # construction. Record operations (the slash commands) and the tool
        # layer never call the model, so the agent builds with client=None
        # and only the chat path (_complete) demands a working key.
        self.client = None
        self.model_error: str | None = None
        if not self.api_key:
            self.model_error = (
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and "
                "fill in your key, or export OPENROUTER_API_KEY in your shell."
            )
        elif self.api_key.strip().lower() == PLACEHOLDER_KEY:
            self.model_error = (
                "OPENROUTER_API_KEY still has the placeholder value. Edit .env "
                "and replace `your_key_here` with your real key."
            )
        else:
            # OpenRouter exposes an OpenAI-compatible API, so the official
            # OpenAI SDK is a drop-in client — just pointed at the base URL.
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        # Short-term conversation history. Starts with the system prompt;
        # grows as user, model, and tool results exchange turns. Phase 11
        # makes it durable: auto-saved after every exchange and restored
        # (with the investigation it was linked to) on the next run.
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Name of the saved investigation the active conversation was linked
        # to (set when a conversation is restored; None until then).
        self._linked_investigation: str | None = None

        # Tools the model may call this session (read-only by construction).
        self.tools = get_tools()

    def ask(self, user_message: str, stream: bool = False) -> str:
        """Send one user message; run the tool-use loop; return the final answer.

        The message, any tool exchanges, and the final assistant reply are all
        kept in this session's history so the model retains context across
        turns. With stream=True (the REPL), the model's text arrives via
        _emit as it is generated — the full reply is still assembled and
        returned. Raises ValueError on empty input, or when no API key is
        configured (model-less mode).
        """
        message = user_message.strip()
        if not message:
            raise ValueError("Cannot send an empty user message.")

        self.messages.append({"role": "user", "content": message})
        reply = self._complete(stream=stream)
        self.messages.append({"role": "assistant", "content": reply})
        self._autosave_conversation()
        return reply

    # --- investigation lifecycle (Phase 4) — thin CLI-facing delegates --------
    #
    # The investigation record itself lives in agent/investigation.py; the
    # model drives it via the investigation_* tools inside the normal loop.
    # These methods let the CLI inspect and control the same state (/investigate,
    # /investigation, /report, /endinvestigation).

    def begin_investigation(self, problem: str) -> str:
        """Open a formal investigation for `problem` (the /investigate command)."""
        return start_investigation(problem)

    def investigation_status_text(self) -> str | None:
        """Live tracker text, or None when no investigation is active."""
        return status_text()

    def investigation_report_text(self) -> str | None:
        """Canonical report once concluded (tracker while in progress), or None."""
        return report_text()

    def investigation_report_json(self) -> dict | None:
        """Structured JSON export of the investigation (for CI/automation), or None."""
        return report_json()

    def end_investigation(self) -> str:
        """Clear the active investigation (read-only: discards only memory)."""
        return finish_investigation()

    # --- persistence (Phase 7) — thin CLI-facing delegates ---------------------
    #
    # The record is auto-saved by the mutation chokepoint in
    # tools/investigation.py; these methods expose resume/list/store-location
    # to the CLI (REPL startup auto-resume, /investigations, --store-dir).

    @property
    def store_dir(self) -> str | None:
        """Directory records are saved to, or None when persistence is off."""
        return store_directory_text()

    def list_investigations(self) -> str | None:
        """Saved investigation records, newest first, or None if none."""
        return list_saved_text()

    def resume_investigation(self) -> str | None:
        """Continue the newest in-progress record, or None if there is none."""
        return load_resumable_investigation()

    def use_store_dir(self, directory: str) -> None:
        """Point persistence at `directory` (--store-dir; tests use tmpdirs)."""
        set_investigation_store(InvestigationStore(directory))

    # --- conversation persistence (Phase 11) — thin CLI-facing delegates -----
    #
    # The conversation is auto-saved at the end of every ask() (chat_store.py);
    # these methods expose session restore, listing, and starting fresh to
    # the CLI (REPL/one-shot auto-restore, /conversations, /newchat).

    @property
    def chat_dir(self) -> str | None:
        """Directory conversations are saved to, or None when persistence is off."""
        return chat_directory_text()

    def _autosave_conversation(self) -> None:
        """Auto-save the conversation after an exchange (silent, best-effort).

        The saved file links to the investigation file active during the
        exchange, so a later restore puts the pair back together.
        """
        save_conversation(self.messages, current_investigation_file())

    def resume_session(self) -> str | None:
        """Auto-restore the newest conversation, with its linked investigation.

        The newest open conversation's messages replay into self.messages
        (already pruned at save time), and the investigation file the
        conversation was linked to is loaded back whatever its status. With
        no conversation to restore, falls back to Phase 7 behavior: the
        newest in-progress investigation only. Returns the notices to show,
        or None when nothing was restored (persistence off, nothing open).
        """
        loaded = load_resumable_conversation()
        if loaded is None:
            return self.resume_investigation()
        messages, investigation_file = loaded
        self.messages = prune_messages(messages)
        self._linked_investigation = investigation_file
        notice = ("Conversation restored — continue where you left off "
                  "(/conversations to list, /newchat to start fresh).")
        if investigation_file:
            resumed = resume_investigation_file(investigation_file)
            if resumed:
                notice += "\n" + resumed
        return notice

    def list_conversations(self) -> str | None:
        """Saved conversations, newest first, or None if none."""
        return list_conversations_text()

    def new_chat(self) -> str:
        """/newchat: clear history and close the saved conversation.

        The saved copy stays on disk as history but will not auto-restore.
        An active investigation is untouched (that is /endinvestigation).
        """
        close_conversation()
        self._linked_investigation = None
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        return ("New conversation — history cleared."
                + (" The active investigation is untouched."
                   if status_text() is not None else ""))

    def _complete(self, stream: bool = False) -> str:
        """The tool-use loop — the single chokepoint where the backend is called.

        Each turn sends the full history (with tool schemas attached when tools
        are available). If the reply requests tools, every requested tool is
        executed locally, the results are appended, and the loop calls the
        model again. Stops when the model answers in plain text, or when the
        iteration cap is reached. With stream=True each model call's text is
        emitted as it arrives; tool exchanges still accumulate silently.
        """
        if self.client is None:
            # Model-less construction: the first chat attempt is where the
            # missing key finally surfaces, as a normal caught ValueError.
            raise ValueError(self.model_error)
        for _ in range(MAX_TOOL_ITERATIONS):
            request: dict = {"model": self.model, "messages": self.messages}
            if self.tools:
                request["tools"] = [tool.schema() for tool in self.tools]

            response = self._call_model(request, stream=stream)
            message = (
                _consume_stream(response) if stream
                else response.choices[0].message
            )

            if not message.tool_calls:
                content = message.content
                if content is None:
                    raise RuntimeError("The model returned an empty response.")
                return content

            # Echo the assistant tool-request turn verbatim, then answer each
            # call with a sibling "tool" message referencing its call id.
            self.messages.append(_echo_tool_request(message))
            for call in message.tool_calls:
                result = execute_tool(call.function.name, call.function.arguments)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )

        raise RuntimeError(
            f"The model did not finish after {MAX_TOOL_ITERATIONS} tool-use turns."
        )

    def _call_model(self, request: dict, stream: bool = False):
        """One model call with bounded retries on transient failures.

        Timeouts, connection errors, rate limits (429) and server-side 5xx
        are retried up to MAX_MODEL_RETRIES times with exponential backoff
        (2s, 4s, 8s + jitter); a 429's Retry-After header wins when present.
        Client errors — a rejected key (401) most notably — fail immediately,
        because retrying the identical request cannot fix them.

        With stream=True the call returns a chunk iterator; the retries cover
        the request setup (connection, auth, 429 on connect) — a drop after
        chunks started flowing is surfaced as-is, since replaying a partially
        streamed answer is not something a retry can do cleanly.
        """
        for attempt in range(MAX_MODEL_RETRIES + 1):
            try:
                return self.client.chat.completions.create(**request, stream=stream)
            except Exception as exc:  # noqa: BLE001 — classified right below
                if attempt >= MAX_MODEL_RETRIES or not _is_transient(exc):
                    raise
                _sleep(_retry_delay(exc, attempt))


def _consume_stream(stream) -> object:
    """Drain a streamed response into a message-shaped object.

    Text deltas are written through _emit as they arrive (the REPL's live
    output) and accumulated into the final content; tool-call deltas are
    accumulated silently by index (name, then argument fragments) and
    reconstructed into the same .tool_calls shape the non-streaming path
    reads. The returned object exposes .content and .tool_calls exactly
    like the SDK's message, so the rest of the loop is unchanged.
    """
    from types import SimpleNamespace  # local: keeps the hot path cheap

    content_parts: list[str] = []
    calls: dict[int, dict] = {}
    next_index = 0
    for chunk in stream:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue  # keep-alive / final usage chunks carry no delta
        delta = choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            content_parts.append(text)
            _emit(text)
        for tc in (getattr(delta, "tool_calls", None) or []):
            index = getattr(tc, "index", None)
            if index is None:
                index = next_index
                next_index += 1
            slot = calls.setdefault(
                index,
                {"id": "", "function": {"name": "", "arguments": ""}},
            )
            if getattr(tc, "id", None):
                slot["id"] = tc.id
            function = getattr(tc, "function", None)
            if function is not None:
                if getattr(function, "name", None):
                    slot["function"]["name"] = function.name
                if getattr(function, "arguments", None):
                    slot["function"]["arguments"] += function.arguments

    content = "".join(content_parts)
    tool_calls = [
        SimpleNamespace(
            id=slot["id"],
            type="function",
            function=SimpleNamespace(
                name=slot["function"]["name"],
                arguments=slot["function"]["arguments"],
            ),
        )
        for _, slot in sorted(calls.items())
    ]
    return SimpleNamespace(
        content=content or None,
        tool_calls=tool_calls or None,
    )


def _echo_tool_request(message) -> dict:
    """Rebuild the assistant turn that requested tools, verbatim.

    The OpenAI-compatible API requires the assistant tool-request turn to be
    echoed into history with the exact tool_calls, each one answered by a
    sibling {"role": "tool"} message that references it via tool_call_id.
    """
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in message.tool_calls
        ],
    }