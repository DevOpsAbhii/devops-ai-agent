"""Human-approval gate for mutating tools (Phase 14).

The project is read-only by construction; this module is the chokepoint a
FUTURE mutating capability must pass through before anything runs. Nothing
in the repo uses it yet — it exists so that the day a mutating tool is
added, "bypassing approval" is not a tool-author decision: registering a
tool with mutating=True forces every call through request_approval().

How a call flows once mutating tools exist:

    model calls tool  ->  execute_tool() sees tool.mutating
                      ->  request_approval(tool.name, argv summary)
                      ->  the REPL asks the human at the terminal
                      ->  approved: the executor runs, once
                      ->  denied:  the model gets a plain "denied by the
                                   human operator" error and the loop lives on

Design points:
- Default-deny: an approver that cannot ask (one-shot mode, tests, pipes)
  denies everything — mutating actions are never silently allowed just
  because nobody was watching.
- Session memory: one yes covers identical (tool, action) pairs for the
  session; a different action re-asks. /approvals resets the memory.
- One-shot mode can pre-approve a single named action with --approve NAME
  (recorded in the run's audit note); it can never pre-approve "all".
- Audit trail: every request — approved, denied, or auto-denied — is
  recorded (in-memory ring + best-effort JSONL append under the store dir)
  so an investigation can show who allowed what.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from tools.base import ToolError

# How the terminal asks the human. Module-level so tests (and the one-shot
# mode's default-deny) can replace it; the REPL keeps the real prompt.
_asker = None  # type: Callable[[str], bool] | None

# Audit ring: the last N approval events of this process.
_audit: list[dict] = []
_AUDIT_LIMIT = 100

# Session approvals: {(tool_name, action_key): True} — a "yes" here means
# the human approved exactly this action once and identical repeats ride
# the same decision for this session.
_approved: set[tuple[str, str]] = set()


def set_asker(fn) -> None:
    """Install the function used to ask the human (None = nobody can ask)."""
    global _asker
    _asker = fn


def reset_approvals() -> int:
    """Forget every session approval; returns how many were held."""
    n = len(_approved)
    _approved.clear()
    return n


def reset_audit() -> None:
    """Clear the in-memory audit ring (the JSONL file on disk stays)."""
    global _audit
    _audit = []


def _audit_path() -> Path | None:
    """JSONL audit file next to the investigation store, best-effort."""
    override = os.getenv("AGENT_STORE_DIR")
    base = Path(override) if override else (
        Path.home() / ".devops-ai-agent" / "investigations"
    )
    return base / "approvals.jsonl"


def _record(event: dict) -> None:
    event = {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        **event,
    }
    _audit.append(event)
    del _audit[:-_AUDIT_LIMIT]
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # audit is best-effort; it must never break the loop


def audit_text() -> str | None:
    """Rendered approval audit (this session), or None when empty."""
    if not _audit:
        return None
    lines = ["**Approval audit** (this session, newest last)"]
    for e in _audit:
        lines.append(
            f"- {e['at']} {e['decision'].upper():8s} {e['tool']}"
            f" — {e['action']}"
            + (" (auto: no human to ask)" if e.get("auto") else "")
        )
    return "\n".join(lines)


def request_approval(tool_name: str, action: str, *, _session_only: bool = False) -> str:
    """Gate one mutating call. Returns "approved" or raises ToolError("denied").

    `action` is the human-readable summary of what will run (the exact
    argv for CLI tools). The REPL's asker prints it and waits for y/n;
    with no asker installed (one-shot, tests, non-interactive pipes) the
    request is auto-denied — default-deny is the whole point of the gate.
    """
    key = (tool_name, action)
    if key in _approved or _session_only:
        if key not in _approved:
            _approved.add(key)
            _record({"tool": tool_name, "action": action,
                     "decision": "approved"})
        return "approved"

    decision = None
    if _asker is not None:
        try:
            decision = bool(_asker(f"{tool_name}: {action}"))
        except (EOFError, KeyboardInterrupt):
            decision = False

    if decision:
        _approved.add(key)
        _record({"tool": tool_name, "action": action, "decision": "approved"})
        return "approved"

    _record({"tool": tool_name, "action": action,
             "decision": "denied", "auto": _asker is None})
    raise ToolError(
        f"denied by the human operator: {tool_name} — {action}. "
        "The agent never retries a mutating action on its own; ask the "
        "operator what to do instead."
    )
