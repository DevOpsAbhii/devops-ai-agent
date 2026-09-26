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

from openai import OpenAI

from agent.prompts import SYSTEM_PROMPT
from agent.store import InvestigationStore
from tools import (  # noqa: F401 — side effect: each module registers its tools
    ansible,
    cloud,
    docker,
    git_ci,
    investigation,
    kubernetes,
    monitoring,
    preflight,
    system,
    terraform,
)
from tools.investigation import (
    finish_investigation,
    list_saved_text,
    report_json,
    report_text,
    resume_investigation as load_resumable_investigation,
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
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and "
                "fill in your key, or export OPENROUTER_API_KEY in your shell."
            )
        if self.api_key.strip().lower() == PLACEHOLDER_KEY:
            raise ValueError(
                "OPENROUTER_API_KEY still has the placeholder value. Edit .env "
                "and replace `your_key_here` with your real key."
            )

        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)

        # OpenRouter exposes an OpenAI-compatible API, so the official OpenAI
        # SDK is a drop-in client — just pointed at OpenRouter's base URL.
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        # Short-term conversation history. Starts with the system prompt;
        # grows as user, model, and tool results exchange turns.
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Tools the model may call this session (read-only by construction).
        self.tools = get_tools()

    def ask(self, user_message: str) -> str:
        """Send one user message; run the tool-use loop; return the final answer.

        The message, any tool exchanges, and the final assistant reply are all
        kept in this session's history so the model retains context across
        turns. Raises ValueError on empty input.
        """
        message = user_message.strip()
        if not message:
            raise ValueError("Cannot send an empty user message.")

        self.messages.append({"role": "user", "content": message})
        reply = self._complete()
        self.messages.append({"role": "assistant", "content": reply})
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

    def _complete(self) -> str:
        """The tool-use loop — the single chokepoint where the backend is called.

        Each turn sends the full history (with tool schemas attached when tools
        are available). If the reply requests tools, every requested tool is
        executed locally, the results are appended, and the loop calls the
        model again. Stops when the model answers in plain text, or when the
        iteration cap is reached.
        """
        for _ in range(MAX_TOOL_ITERATIONS):
            request: dict = {"model": self.model, "messages": self.messages}
            if self.tools:
                request["tools"] = [tool.schema() for tool in self.tools]

            response = self.client.chat.completions.create(**request)
            message = response.choices[0].message

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