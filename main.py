"""The DevOps investigation agent.

Two modes of use:

REPL (default):
    python main.py

One-shot (for cron / CI / scripts):
    python main.py "why is api-5d6f crash-looping?"
    python main.py --json "why is api-5d6f crash-looping?"   # structured report
    python main.py --resume --json "any update?"             # continue prior run
    python main.py --store-dir DIR --out report.json "..."   # pipeline paths
    python main.py --model openai/gpt-4o-mini "..."          # one-run model override

One-shot mode sends the problem once, prints the agent's report, and exits
with a status code (0 = completed, 1 = setup/API error). With --json the
output is the tracked investigation as JSON (see agent/investigation.py:
render_report_json) instead of the markdown report, so a pipeline can act
on the verdict. --out additionally writes that JSON to an exact path.
Phase 7: the investigation record is auto-saved on every change
(~/.devops-ai-agent/investigations/ by default) and survives CLI exits; the
REPL resumes the newest in-progress record at startup. Slash commands work
in both modes (/investigate, /investigations, /report, ...). Read-only:
nothing here ever mutates a real system.

Type `exit` (or `quit`, or Ctrl-D / Ctrl-C) to leave the REPL.
"""

import json
import sys
from pathlib import Path
from typing import NamedTuple

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
from agent.config import config_path, save_user_config

EXIT_WORDS = {"exit", "quit"}

# Slash commands that operate on the investigation record, plus short aliases.
COMMAND_ALIASES = {
    "/investigate": "/investigate",
    "/inv": "/investigate",
    "/investigation": "/investigation",
    "/status": "/investigation",
    "/investigations": "/investigations",
    "/history": "/investigations",
    "/report": "/report",
    "/endinvestigation": "/endinvestigation",
    "/end": "/endinvestigation",
    "/model": "/model",
}


def handle_command(text: str, agent: DevOpsAgent) -> str | None:
    """Handle a slash command; return the text to print, or None to continue.

    Command lines are detected by main() and routed here without ever
    reaching the model. All commands are read-only with respect to real
    systems: they only inspect or clear the agent's in-memory record (and,
    for /investigations, list the saved copies on disk).
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
    if canonical == "/investigations":
        return agent.list_investigations() or "(no saved investigations yet)"
    if canonical == "/report":
        return agent.investigation_report_text() or "(no investigation recorded)"
    if canonical == "/endinvestigation":
        return agent.end_investigation()
    if canonical == "/model":
        return handle_model_command(rest, agent)
    return (f"unknown command: {cmd}. Try /investigate <problem>, "
            "/investigation, /investigations, /report, /endinvestigation, "
            "/model")


def handle_model_command(rest: str, agent: DevOpsAgent) -> str:
    """/model (show the active model and where it came from) or /model <name>.

    With a name: save it as the user's preference in the config file
    (~/.devops-ai-agent/config.json) and switch this session to it. The
    next run picks it up automatically — the flag and env still outrank it.
    """
    name = rest.strip()
    if not name:
        return (f"Model: {agent.model}\n"
                f"Config file: {config_path()} "
                "(save a default with /model <name>)")
    if len(name.split()) != 1:
        return "Model name must be a single token, e.g. /model openai/gpt-4o-mini"
    path = save_user_config({"model": name})
    agent.model = name
    return (f"Model set to {name} (saved in {path}).\n"
            "This session now uses it; the --model flag and OPENROUTER_MODEL "
            "still override it per run.")


class OneShotArgs(NamedTuple):
    """Parsed one-shot CLI arguments (task=None means "run the REPL")."""

    task: str | None
    as_json: bool
    store_dir: str | None  # --store-dir PATH (persistence override)
    resume: bool           # --resume (continue the newest in-progress record)
    out: str | None        # --out PATH (also write the JSON report there)
    model: str | None      # --model NAME (one-run model override)


_VALUE_FLAGS = ("--store-dir", "--out", "--model")


def _flag_value(argv: list[str], flag: str) -> str | None:
    """Value of `flag <value>` in argv, or None when absent/missing."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
    return None


def parse_args(argv: list[str]) -> OneShotArgs:
    """Split one-shot CLI args.

    task=None means "run the REPL". A bare task is any positional text;
    --json switches the one-shot output from markdown to the structured JSON
    report; --resume continues the newest in-progress record from the store;
    --store-dir PATH overrides the persistence directory for this run; --out
    PATH additionally writes the JSON report to an exact path; --model NAME
    overrides the model for this run (highest model precedence). Example:
    `python main.py --json --out r.json "why is it down?"` ->
    ("why is it down?", True, None, False, "r.json", None).
    """
    as_json = "--json" in argv
    do_resume = "--resume" in argv
    store_dir = _flag_value(argv, "--store-dir")
    out = _flag_value(argv, "--out")
    model = _flag_value(argv, "--model")
    positionals: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_FLAGS:
            skip_next = True  # its value was captured by _flag_value
            continue
        if arg in ("--json", "--resume"):
            continue
        positionals.append(arg)
    text = " ".join(positionals).strip()
    if not positionals or not text:
        return OneShotArgs(None, as_json, store_dir, do_resume, out, model)
    return OneShotArgs(text, as_json, store_dir, do_resume, out, model)


def run_one_shot(
    task: str,
    as_json: bool = False,
    agent: DevOpsAgent | None = None,
    store_dir: str | None = None,
    resume: bool = False,
    out: str | None = None,
    model: str | None = None,
) -> int:
    """Non-interactive single run: send `task`, print the result, exit cleanly.

    Exit code 1 on setup/API errors. With as_json (or out), the printed /
    written output is the tracked investigation as JSON; if the model never
    opened an investigation this is a hard failure (exit 1) — a caller asked
    for a report and there is none to give. The record is auto-saved on every
    mutation regardless; store_dir points persistence somewhere else for this
    run, resume continues the newest in-progress record before asking, out
    additionally writes the JSON report to an exact path, and model overrides
    the model for this run. `agent` lets embedders reuse a configured agent
    (also the test seam); default builds a fresh one from the environment.
    """
    if agent is None:
        try:
            agent = DevOpsAgent(model=model)
        except ValueError as exc:
            print(f"[setup] {exc}", file=sys.stderr)
            return 1

    if store_dir is not None:
        agent.use_store_dir(store_dir)
    if resume:
        agent.resume_investigation()

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

    if as_json or out is not None:
        report = agent.investigation_report_json()
        if report is None:
            print(
                "[error] --json/--out requested but the run recorded no "
                "investigation",
                file=sys.stderr,
            )
            return 1
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if out is not None:
            try:
                Path(out).write_text(rendered + "\n", encoding="utf-8")
            except OSError as exc:
                print(f"[error] could not write --out {out}: {exc}",
                      file=sys.stderr)
                return 1
        if as_json:
            print(rendered)
            return 0
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

    # One-shot mode: `python main.py [flags] <problem or /command>`.
    args = parse_args(sys.argv[1:])
    if args.task is not None:
        return run_one_shot(
            args.task,
            as_json=args.as_json,
            store_dir=args.store_dir,
            resume=args.resume,
            out=args.out,
            model=args.model,
        )

    try:
        agent = DevOpsAgent(model=args.model)
    except ValueError as exc:
        print(f"[setup] {exc}", file=sys.stderr)
        return 1

    if agent.client is None:
        # Model-less mode: the REPL still starts — record commands (slash
        # commands) work, only questions to the model are unavailable.
        print(f"[setup] {agent.model_error}", file=sys.stderr)
        print("[setup] Starting without a model — slash commands still work; "
              "questions need OPENROUTER_API_KEY.", file=sys.stderr)

    tool_names = ", ".join(sorted(tool.name for tool in agent.tools)) or "none"

    print("DevOps AI Agent (Phase 9 — 58 read-only tools, persistent investigations)")
    print(f"Model:   {agent.model}")
    print(f"Backend: {agent.base_url}")
    print(f"Store:   {agent.store_dir or '(persistence off)'}")
    print(f"Tools:   {tool_names}")
    print("Commands: /investigate <problem>, /investigation, /investigations, "
          "/report, /endinvestigation, /model [<name>]")
    print("One-shot: python main.py [--json] [--resume] [--out report.json] "
          "[--store-dir DIR] [--model NAME] \"<problem>\"")
    print("Type 'exit' to quit.")
    print()

    # Phase 7: pick up the newest in-progress record so a previous session's
    # work is not lost (fresh investigations start with /investigate as usual).
    resumed = agent.resume_investigation()
    if resumed:
        print(resumed)
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