"""Investigation meta-tools (Phase 4).

The model uses these three tools to maintain a first-class investigation
record (agent/investigation.py) while it works a reported problem: open the
investigation, record hypotheses / evidence / verdicts, and conclude with
root cause + remediation + verification.

These are the only "stateful" tools — and they mutate NOTHING outside the
agent's own memory: no cluster, no files, no infrastructure. The read-only
guarantee of the project is unaffected.
"""

from agent.investigation import (
    CONFIDENCE_LEVELS,
    HYPOTHESIS_STATUSES,
    Investigation,
    InvestigationError,
)
from tools.base import Tool, ToolError
from tools.registry import register

# The single active investigation for this agent process (single-threaded CLI).
_active: Investigation | None = None


# --- thin functions shared by the CLI and the tool executors ---

def start_investigation(problem: str, hypotheses: list[str] | None = None) -> str:
    """Open an investigation (tool executor and /investigate both route here)."""
    global _active
    if _active is not None:
        return "an investigation is already active:\n" + _active.render_status()
    try:
        _active = Investigation(problem, hypotheses)
    except InvestigationError as exc:
        raise ToolError(str(exc)) from exc
    return (
        "Investigation started.\n"
        + _active.render_status()
        + "\n\nTrack hypotheses and evidence with investigation_record, and "
          "finish with investigation_conclude."
    )


def record(
    kind: str,
    content: str,
    hypothesis_id: str | None = None,
    status: str | None = None,
) -> str:
    inv = _require_active()
    try:
        kind = (kind or "").strip()
        if kind == "hypothesis":
            result = inv.add_hypothesis(content)
        elif kind == "evidence":
            result = inv.record_evidence(content, hypothesis_id)
        elif kind == "verdict":
            if not hypothesis_id or not status:
                raise InvestigationError(
                    "a verdict requires both hypothesis_id and status"
                )
            result = inv.verify_hypothesis(hypothesis_id, status, content)
        else:
            raise InvestigationError(
                f"unknown kind {kind!r}; expected hypothesis | evidence | verdict"
            )
    except InvestigationError as exc:
        raise ToolError(str(exc)) from exc
    return result + "\n" + inv.render_status()


def conclude_investigation(
    *,
    summary: str,
    root_cause: str,
    remediation: str | list[str],
    verification: str | list[str],
    confidence: str = "medium",
) -> str:
    inv = _require_active()
    try:
        result = inv.conclude(
            summary=summary,
            root_cause=root_cause,
            remediation=remediation,
            verification=verification,
            confidence=confidence,
        )
    except InvestigationError as exc:
        raise ToolError(str(exc)) from exc
    return result


def status_text() -> str | None:
    return _active.render_status() if _active is not None else None


def report_text() -> str | None:
    """Current tracker, or the canonical report once concluded."""
    return _active.render_report() if _active is not None else None


def report_json() -> dict | None:
    """Structured JSON export of the active investigation (CI/automation)."""
    return _active.render_report_json() if _active is not None else None


def finish_investigation() -> str:
    global _active
    if _active is None:
        return "no active investigation"
    _active = None
    return "investigation cleared"


def _require_active() -> Investigation:
    if _active is None:
        raise ToolError(
            "no active investigation. Call investigation_begin first (the "
            "user must be reporting a concrete problem)."
        )
    return _active


# --- tool executors (adapter from parsed args dict to the functions above) ---


def _begin_executor(args: dict) -> str:
    return start_investigation(
        args.get("problem"),
        args.get("initial_hypotheses"),
    )


def _record_executor(args: dict) -> str:
    return record(
        kind=args.get("kind"),
        content=args.get("content"),
        hypothesis_id=args.get("hypothesis_id"),
        status=args.get("status"),
    )


def _conclude_executor(args: dict) -> str:
    return conclude_investigation(
        summary=args.get("summary"),
        root_cause=args.get("root_cause"),
        remediation=args.get("remediation"),
        verification=args.get("verification"),
        confidence=args.get("confidence", "medium"),
    )


INVESTIGATION_BEGIN = Tool(
    name="investigation_begin",
    description=(
        "Start a formal incident investigation for a problem the user just "
        "reported (a failing pod, broken rollout, alert, degradation — NOT a "
        "general question). Call this BEFORE gathering evidence, listing your "
        "initial hypotheses. Returns the live investigation tracker."
    ),
    parameters={
        "type": "object",
        "properties": {
            "problem": {
                "type": "string",
                "description": "One-line statement of the problem to investigate.",
            },
            "initial_hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 plausible causes to test (will become H1, H2, ...).",
            },
        },
        "required": ["problem"],
        "additionalProperties": False,
    },
    executor=_begin_executor,
)

INVESTIGATION_RECORD = Tool(
    name="investigation_record",
    description=(
        "Record something into the ACTIVE investigation: a new hypothesis "
        "(kind=hypothesis), an evidence note linked to a hypothesis "
        "(kind=evidence, optional hypothesis_id), or a verdict updating a "
        "hypothesis (kind=verdict with hypothesis_id and status). Returns the "
        "updated tracker. Requires an active investigation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["hypothesis", "evidence", "verdict"],
                "description": "What to record.",
            },
            "content": {
                "type": "string",
                "description": "The hypothesis statement, evidence note, or "
                "verdict justification.",
            },
            "hypothesis_id": {
                "type": "string",
                "description": "Hypothesis id (H1, H2, ...) to link evidence to "
                "or to give a verdict.",
            },
            "status": {
                "type": "string",
                "enum": list(HYPOTHESIS_STATUSES),
                "description": "For kind=verdict: new status of the hypothesis.",
            },
        },
        "required": ["kind", "content"],
        "additionalProperties": False,
    },
    executor=_record_executor,
)

INVESTIGATION_CONCLUDE = Tool(
    name="investigation_conclude",
    description=(
        "Finish the ACTIVE investigation once evidence is sufficient: name the "
        "root cause, remediation RECOMMENDATIONS (you never execute anything), "
        "verification steps, and your confidence. Requires an active "
        "investigation run by investigation_begin."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One-paragraph summary of the investigation.",
            },
            "root_cause": {
                "type": "string",
                "description": "The confirmed/likeliest root cause.",
            },
            "remediation": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Recommended fixes (read-only agent: these are "
                "proposals, never executed).",
            },
            "verification": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Steps to confirm the fix worked.",
            },
            "confidence": {
                "type": "string",
                "enum": list(CONFIDENCE_LEVELS),
                "description": "Confidence in the root cause.",
            },
        },
        "required": ["summary", "root_cause", "remediation", "verification"],
        "additionalProperties": False,
    },
    executor=_conclude_executor,
)

register(INVESTIGATION_BEGIN)
register(INVESTIGATION_RECORD)
register(INVESTIGATION_CONCLUDE)