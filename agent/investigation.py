"""Investigation state for the DevOps agent (Phase 4).

A first-class, in-memory record of an ongoing incident investigation: the
problem statement, tracked hypotheses with verdicts, evidence notes, and —
once concluded — root cause, remediation, and verification.

The model drives this state through the investigation_* tools in
tools/investigation.py; the CLI exposes the same state via /investigate,
/investigation and /report. This module is PURE DATA — no model calls, no
I/O — so it is fully unit-testable.

Read-only guarantee: recording a hypothesis or a verdict mutates only this
agent's in-memory state. Nothing here touches a cluster, a file, or any
real system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HYPOTHESIS_STATUSES = ("proposed", "supported", "refuted", "confirmed")
CONFIDENCE_LEVELS = ("high", "medium", "low")


class InvestigationError(Exception):
    """Raised on invalid state transitions (e.g. unknown hypothesis id)."""


@dataclass
class Hypothesis:
    id: str
    statement: str
    status: str = "proposed"
    notes: list[str] = field(default_factory=list)

    def set_status(self, status: str) -> None:
        if status not in HYPOTHESIS_STATUSES:
            raise InvestigationError(
                f"invalid hypothesis status {status!r}; expected one of "
                f"{HYPOTHESIS_STATUSES}"
            )
        self.status = status


@dataclass
class EvidenceNote:
    id: str
    content: str
    hypothesis_id: str | None = None  # which tracked hypothesis this bears on


@dataclass
class Conclusion:
    summary: str
    root_cause: str
    remediation: list[str]
    verification: list[str]
    confidence: str


class Investigation:
    """Tracks one incident investigation from problem statement to report."""

    def __init__(
        self,
        problem: str,
        initial_hypotheses: list[str] | None = None,
    ) -> None:
        if not problem or not problem.strip():
            raise InvestigationError("problem statement must not be empty")
        self.problem = problem.strip()
        self.hypotheses: list[Hypothesis] = []
        self.evidence: list[EvidenceNote] = []
        self.conclusion: Conclusion | None = None
        self._next_h = 1
        self._next_e = 1
        for statement in initial_hypotheses or []:
            if statement and statement.strip():
                self.add_hypothesis(statement)

    # --- mutations; each returns a short confirmation for the tool result ---

    def add_hypothesis(self, statement: str) -> str:
        clean = (statement or "").strip()
        if not clean:
            raise InvestigationError("hypothesis statement must not be empty")
        h = Hypothesis(id=f"H{self._next_h}", statement=clean)
        self._next_h += 1
        self.hypotheses.append(h)
        return f"recorded hypothesis {h.id}: {clean}"

    def verify_hypothesis(
        self, hypothesis_id: str, status: str, note: str | None = None
    ) -> str:
        h = self._get_hypothesis(hypothesis_id)
        h.set_status(status)
        if note and note.strip():
            h.notes.append(note.strip())
        detail = f" — {note.strip()}" if note and note.strip() else ""
        return f"{h.id} is now [{h.status}]: {h.statement}{detail}"

    def record_evidence(self, content: str, hypothesis_id: str | None = None) -> str:
        clean = (content or "").strip()
        if not clean:
            raise InvestigationError("evidence note must not be empty")
        if hypothesis_id is not None:
            self._get_hypothesis(hypothesis_id)  # validates the link target
        note = EvidenceNote(
            id=f"E{self._next_e}", content=clean, hypothesis_id=hypothesis_id
        )
        self._next_e += 1
        self.evidence.append(note)
        link = f" (→ {hypothesis_id})" if hypothesis_id else ""
        return f"recorded evidence {note.id}: {clean}{link}"

    def conclude(
        self,
        *,
        summary: str,
        root_cause: str,
        remediation: str | list[str],
        verification: str | list[str],
        confidence: str = "medium",
    ) -> str:
        if self.conclusion is not None:
            return "this investigation is already concluded — /report shows it"
        if not (summary or "").strip() or not (root_cause or "").strip():
            raise InvestigationError("summary and root_cause are required")
        if confidence not in CONFIDENCE_LEVELS:
            raise InvestigationError(
                f"invalid confidence {confidence!r}; expected one of {CONFIDENCE_LEVELS}"
            )
        self.conclusion = Conclusion(
            summary=summary.strip(),
            root_cause=root_cause.strip(),
            remediation=_string_list(remediation, "remediation"),
            verification=_string_list(verification, "verification"),
            confidence=confidence,
        )
        return (
            "investigation concluded. End your answer with the structured "
            "report; it is also available via /report."
        )

    # --- read-only views for the model and the CLI ---

    def render_status(self) -> str:
        """Compact tracker appended to every investigation tool result."""
        lines = ["**Investigation tracker**", f"Problem: {self.problem}"]
        if self.conclusion is None:
            lines.append("Status: in progress")
        else:
            lines.append(f"Status: concluded (confidence {self.conclusion.confidence})")
        if self.hypotheses:
            lines.append("Hypotheses:")
            lines += [f"- {h.id} [{h.status}] {h.statement}" for h in self.hypotheses]
        else:
            lines.append("Hypotheses: none yet")
        if self.evidence:
            lines.append("Evidence:")
            lines += [
                f"- {e.id} {e.content}"
                + (f" (→ {e.hypothesis_id})" if e.hypothesis_id else "")
                for e in self.evidence
            ]
        else:
            lines.append("Evidence: none recorded yet")
        return "\n".join(lines)

    def render_report(self) -> str:
        """Canonical final report (deterministic — always rendered from state)."""
        if self.conclusion is None:
            return self.render_status()

        c = self.conclusion
        lines = [
            "# Investigation report",
            "",
            f"**Problem:** {self.problem}",
            "",
            "## Facts / evidence",
        ]
        if self.evidence:
            lines += [
                f"- {e.content}"
                + (f" (→ {e.hypothesis_id})" if e.hypothesis_id else "")
                for e in self.evidence
            ]
        else:
            lines.append("- (none recorded)")
        lines += ["", "## Hypotheses"]
        if self.hypotheses:
            lines += [
                f"- **{h.id}** [{h.status}] {h.statement}" for h in self.hypotheses
            ]
        else:
            lines.append("- (none)")
        lines += ["", "## Root cause", "", c.root_cause]
        lines += ["", "## Remediation (recommendations — nothing was executed)"]
        lines += [f"- {item}" for item in c.remediation] or ["- (none)"]
        lines += ["", "## Verification steps"]
        lines += [f"- {item}" for item in c.verification] or ["- (none)"]
        lines += [
            "",
            f"**Summary:** {c.summary}",
            f"**Confidence:** {c.confidence}",
        ]
        return "\n".join(lines)

    def render_report_json(self) -> dict:
        """Structured export of the investigation, for CI/automation tooling.

        Always returns the same shape whether or not the investigation is
        concluded: hypotheses and evidence are lists; `conclusion` is present
        only once concluded. No model text is trusted — everything is
        re-derived deterministically from the tracked record.
        """
        out: dict = {
            "problem": self.problem,
            "status": "concluded" if self.conclusion is not None else "in_progress",
            "hypotheses": [
                {
                    "id": h.id,
                    "statement": h.statement,
                    "status": h.status,
                    "notes": list(h.notes),
                }
                for h in self.hypotheses
            ],
            "evidence": [
                {
                    "id": e.id,
                    "content": e.content,
                    "hypothesis_id": e.hypothesis_id,
                }
                for e in self.evidence
            ],
        }
        if self.conclusion is not None:
            c = self.conclusion
            out["conclusion"] = {
                "summary": c.summary,
                "root_cause": c.root_cause,
                "remediation": list(c.remediation),
                "verification": list(c.verification),
                "confidence": c.confidence,
            }
        return out

    # --- persistence (Phase 7) — lossless round-trip for the store ------------

    def to_dict(self, *, saved_at: str | None = None) -> dict:
        """Full serializable state, for the store to write to disk.

        render_report_json() is already a lossless view of the record, so
        persistence reuses it and adds storage metadata: `schema` (format
        version, bumped only on breaking changes) and `saved_at` (ISO
        timestamp, set by the store). from_dict() round-trips this exactly.
        """
        out = self.render_report_json()
        out["schema"] = 1
        if saved_at is not None:
            out["saved_at"] = saved_at
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Investigation":
        """Rebuild an Investigation from to_dict() output.

        Tolerant of unknown keys (forward compatible) and strict about our
        own: a corrupt or truncated file raises InvestigationError (or
        KeyError for a missing problem), which the store turns into "skip
        this file" rather than a crash.
        """
        inv = cls(data["problem"])
        for h in data.get("hypotheses") or []:
            hyp = Hypothesis(
                id=str(h.get("id", "")),
                statement=str(h.get("statement", "")),
                status="proposed",
                notes=[str(n) for n in (h.get("notes") or [])],
            )
            hyp.set_status(str(h.get("status", "proposed")))
            number = _id_number(hyp.id, "H")
            if number is None:
                raise InvestigationError(f"malformed hypothesis id {hyp.id!r}")
            inv.hypotheses.append(hyp)
            if number >= inv._next_h:
                inv._next_h = number + 1
        for e in data.get("evidence") or []:
            hypothesis_id = e.get("hypothesis_id")
            note = EvidenceNote(
                id=str(e.get("id", "")),
                content=str(e.get("content", "")),
                hypothesis_id=str(hypothesis_id) if hypothesis_id else None,
            )
            number = _id_number(note.id, "E")
            if number is None:
                raise InvestigationError(f"malformed evidence id {note.id!r}")
            if note.hypothesis_id is not None:
                inv._get_hypothesis(note.hypothesis_id)  # validate the link
            inv.evidence.append(note)
            if number >= inv._next_e:
                inv._next_e = number + 1
        c = data.get("conclusion")
        if c is not None:
            inv.conclude(
                summary=str(c.get("summary", "")),
                root_cause=str(c.get("root_cause", "")),
                remediation=c.get("remediation") or [],
                verification=c.get("verification") or [],
                confidence=str(c.get("confidence", "medium")),
            )
        return inv

    def _get_hypothesis(self, hypothesis_id: str) -> Hypothesis:
        found = next((h for h in self.hypotheses if h.id == hypothesis_id), None)
        if found is None:
            raise InvestigationError(
                f"unknown hypothesis id {hypothesis_id!r}; known ids: "
                f"{', '.join(h.id for h in self.hypotheses) or 'none'}"
            )
        return found


def _string_list(value: str | list[str], label: str) -> list[str]:
    items = [value] if isinstance(value, str) else list(value or [])
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        raise InvestigationError(f"{label} must contain at least one item")
    return cleaned


def _id_number(value: str, prefix: str) -> int | None:
    """Numeric suffix of an H*/E* id (H12 -> 12), or None if malformed."""
    if not value.startswith(prefix):
        return None
    tail = value[len(prefix):]
    return int(tail) if tail.isdigit() else None