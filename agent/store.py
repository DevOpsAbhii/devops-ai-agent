"""Investigation persistence (Phase 7): the record survives CLI exits.

One JSON file per investigation, written atomically (tmp file + rename)
into a directory — by default ~/.devops-ai-agent/investigations/, kept out
of any working directory so records never pollute a repo. Every save
rewrites the active record's file in place, so the directory holds one
file per investigation (not per change) and a crash mid-investigation
loses nothing.

Best-effort by design: an unwritable directory, a full disk, or a corrupt
file degrades to "persistence unavailable / skipped" and never interrupts
an investigation. Pure stdlib — json, pathlib, datetime.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

from agent.investigation import Investigation, InvestigationError

# Default location; AGENT_STORE_DIR (or --store-dir) overrides it.
DEFAULT_DIR = Path.home() / ".devops-ai-agent" / "investigations"


def _slug(text: str, limit: int = 40) -> str:
    """Filename-safe slug of the problem statement."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "investigation"


class InvestigationStore:
    """Writes investigation records to disk and reads them back."""

    def __init__(self, directory: str | os.PathLike) -> None:
        self.directory = Path(directory).expanduser()
        # File the active record is persisted to; fixed at first save so
        # every subsequent save updates the same file in place.
        self._current_path: Path | None = None

    # --- write path -----------------------------------------------------------

    @property
    def current_file(self) -> str | None:
        """Name of the file the active record is saved to, if any."""
        return self._current_path.name if self._current_path else None

    def save(self, inv: Investigation) -> Path | None:
        """Persist `inv`, creating its file on first save.

        Returns the file path, or None when the store is unusable. Never
        raises — persistence must not be able to break an investigation.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self._current_path is None:
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                self._current_path = self._collision_free(
                    f"{stamp}-{_slug(inv.problem)}"
                )
            payload = inv.to_dict(
                saved_at=datetime.datetime.now().isoformat(timespec="seconds")
            )
            tmp = self._current_path.with_name(self._current_path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._current_path)
            return self._current_path
        except OSError:
            return None

    def forget(self) -> None:
        """Stop tracking the active file (the saved copy remains as history)."""
        self._current_path = None

    def _collision_free(self, base: str) -> Path:
        path = self.directory / f"{base}.json"
        n = 2
        while path.exists():
            path = self.directory / f"{base}-{n}.json"
            n += 1
        return path

    # --- read path ------------------------------------------------------------

    def resume_latest(self) -> Investigation | None:
        """Newest in-progress record, or None. Concluded and corrupt files
        are skipped. Remembers the file so subsequent saves update it."""
        for path in self._saved_files():
            data = self._read(path)
            if data is None or data.get("status") != "in_progress":
                continue
            inv = self._parse(data)
            if inv is not None:
                self._current_path = path
                return inv
        return None

    def list_saved(self) -> list[dict]:
        """Every saved record, newest first: file, problem, status, saved_at."""
        rows = []
        for path in self._saved_files():
            data = self._read(path)
            if data is None:
                continue
            rows.append(
                {
                    "file": path.name,
                    "problem": str(data.get("problem", "(unknown)")),
                    "status": str(data.get("status", "unknown")),
                    "saved_at": str(data.get("saved_at", "")),
                }
            )
        return rows

    def _saved_files(self) -> list[Path]:
        try:
            files = [p for p in self.directory.glob("*.json") if p.is_file()]
        except OSError:
            return []
        # Timestamp-prefixed names: lexical order == chronological order.
        return sorted(files, reverse=True)

    def _read(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _parse(self, data: dict) -> Investigation | None:
        try:
            return Investigation.from_dict(data)
        except (InvestigationError, KeyError, TypeError, ValueError,
                AttributeError):
            return None


def default_store() -> InvestigationStore:
    """Store at the default location; AGENT_STORE_DIR overrides it."""
    override = os.getenv("AGENT_STORE_DIR")
    return InvestigationStore(override or DEFAULT_DIR)
