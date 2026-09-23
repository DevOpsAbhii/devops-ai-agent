"""The DevOps investigation agent.

Two modes of use:

REPL (default):
    python main.py

One-shot (for cron / CI / scripts):
    python main.py "why is api-5d6f crash-looping?"
    python main.py --json "why is api-5d6f crash-looping?"   # structured report

One-shot mode sends the problem once, prints the agent's report, and exits
with a status code (0 = completed, 1 = setup/API error). With --json the
output is the tracked investigation as JSON (see agent/investigation.py:
render_report_json) instead of the markdown report, so a pipeline can act
on the verdict. Slash commands work in both modes (/investigate, /report,
...). Read-only: nothing here ever mutates a real system.

Type `exit` (or `quit`, or Ctrl-D / Ctrl-C) to leave the REPL.
"""

import json
import sys

from dotenv import load_dotenv
from openai import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from agent.agent import DevOpsAgent

EXIT_WORDS = {"exit", "quit"}

# Slash commands that operate on the investigation record, plus short aliases.
COMMAND_ALIASES = {
    "/investigate": "/investigate",
    "/inv": "/investigate",
    "/investigation": "/investigation",
    "/status": "/investigation",
    "/report": "/report",
    "/endinvestigation": "/endinvestigation",
    "/end": "/endinvestigation",
}


def handle_command(text: str, agent: DevOpsAgent) -> str | None:
    """Handle a slash command; return the text to print, or None to continue.

    Command lines are detected by main() and routed here without ever
    reaching the model. All commands are read-only with respect to real
    systems: they only inspect or clear the agent's in-memory record.
    """
    cmd, _, rest = text.partition(" ")
    canonical = COMMAND_ALIASES.get(cmd.lower())

    if canonical == "/investigate":
        problem = rest.strip()
        if not problem:
            return "Usage: /investigate <one-line problem statement>"
        return agent.begin_investigation(problem)
    if canonical == "/investigation":
        return agent.investigation_status_text() or "(no active investigation)"
    if canonical == "/report":
        return agent.investigation_report_text() or "(no investigation recorded)"
    if canonical == "/endinvestigation":
        return agent.end_investigation()
    return f"unknown command: {cmd}. Try /investigate <problem>, /investigation, /report, /endinvestigation"


def parse_args(argv: list[str]) -> tuple[str | None, bool]:
    """Split one-shot CLI args into (task_text, as_json).

    (None, False) means "run the REPL". A bare task is any positional text;
    --json switches the one-shot output from markdown to the structured JSON
    report. Example: `python main.py --json "why is it down?"` ->
    ("why is it down?", True).
    """
    as_json = "--json" in argv
    positionals = [arg for arg in argv if arg != "--json"]
    text = " ".join(positionals).strip()
    if not positionals or not text:
        return None, False
    return text, as_json


def run_one_shot(
    task: str,
    as_json: bool = False,
    agent: DevOpsAgent | None = None,
) -> int:
    """Non-interactive single run: send `task`, print the result, exit cleanly.

    Exit code 1 on setup/API errors. With as_json, the printed output is the
    tracked investigation as JSON; if the model never opened an investigation
    this is a hard failure (exit 1) — a caller asked for a report and there
    is none to give. `agent` lets embedders reuse a configured agent (also the
    test seam); default builds a fresh one from the environment.
    """
    if agent is None:
        try:
            agent = DevOpsAgent()
        except ValueError as exc:
            print(f"[setup] {exc}", file=sys.stderr)
            return 1

    if task.startswith("/"):
        print(handle_command(task, agent))
        return 0

    try:
        reply = agent.ask(task)
    except ValueError as exc:
        print(f"[input] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — same top-level safety net as the REPL
        print(f"[error] {describe_error(exc)}", file=sys.stderr)
        return 1

    if as_json:
        report = agent.investigation_report_json()
        if report is None:
            print(
                "[error] --json requested but the run recorded no investigation",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(reply)
    return 0


def describe_error(exc: Exception) -> str:
    """Map common SDK/API failures to short, safe messages (never leaks keys)."""
    if isinstance(exc, AuthenticationError):
        return (
            "The API key was rejected (HTTP 401). Check that OPENROUTER_API_KEY "
            "in .env is correct and still valid."
        )
    if isinstance(exc, RateLimitError):
        return "Rate limit hit — OpenRouter is throttling requests. Wait and retry."
    if isinstance(exc, APITimeoutError):
        return "The request to OpenRouter timed out. Check your network and retry."
    if isinstance(exc, APIConnectionError):
        return (
            "Could not reach the OpenRouter API. Check your internet connection "
            "and that the base URL is correct."
        )
    if isinstance(exc, APIStatusError):
        return f"The OpenRouter API returned an error (HTTP {exc.status_code})."
    if isinstance(exc, APIError):
        return "The API returned an unexpected error."
    return f"Unexpected error: {type(exc).__name__}"


def main() -> int:
    # Load .env (never overrides variables already set in the shell).
    load_dotenv()

    # One-shot mode: `python main.py ["--json"] <problem or /command>`.
    task, as_json = parse_args(sys.argv[1:])
    if task is not None:
        return run_one_shot(task, as_json=as_json)

    try:
        agent = DevOpsAgent()
    except ValueError as exc:
        print(f"[setup] {exc}", file=sys.stderr)
        return 1

    tool_names = ", ".join(sorted(tool.name for tool in agent.tools)) or "none"

    print("DevOps AI Agent (Phase 6 — one-shot CLI, JSON reports, git-tracked)")
    print(f"Model:   {agent.model}")
    print(f"Backend: {agent.base_url}")
    print(f"Tools:   {tool_names}")
    print("Commands: /investigate <problem>, /investigation, /report, /endinvestigation")
    print("One-shot: python main.py [--json] \"<problem>\"   (cron/CI-friendly)")
    print("Type 'exit' to quit.")
    print()

    while True:
        try:
            raw = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        text = raw.strip()
        if not text:
            print("(Enter a message, or type 'exit' to quit.)")
            continue
        if text.lower() in EXIT_WORDS:
            print("Bye.")
            return 0
        if text.startswith("/"):
            print(handle_command(text, agent))
            print()
            continue

        try:
            reply = agent.ask(text)
        except ValueError as exc:
            print(f"[input] {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — top-level safety net
            print(f"[error] {describe_error(exc)}")
            continue

        print(f"Agent: {reply}")
        print()


if __name__ == "__main__":
    sys.exit(main())