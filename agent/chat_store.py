"""Conversation persistence (Phase 11): the chat survives CLI exits.

The investigation record has been durable since Phase 7; this module makes
the conversation around it durable too. One JSON file per conversation,
written atomically (tmp file + rename) into a directory — by default
~/.devops-ai-agent/conversations/ (AGENT_CHAT_DIR overrides it) — so the
model's context (user turns, replies, tool exchanges) is restored on the
next run instead of being re-explained.

Each conversation file links to the investigation file that was active
while it was written, so the session auto-restore puts the pair back
together: the same chat, the same tracker.

Structure is preserved across turns: messages are pruned only at "user"
turn boundaries (an assistant tool-request and its tool results are never
split), so a restored history is always a valid OpenAI-compatible message
sequence.

Best-effort by design, exactly like the investigation store: an
unwritable directory or a corrupt file degrades to "persistence skipped"
and never interrupts a conversation. Pure stdlib — json, pathlib, datetime.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

# Default location; AGENT_CHAT_DIR overrides it.
DEFAULT_DIR = Path.home() / ".devops-ai-agent" / "conversations"

# History is pruned to at most this many user-started turns before saving,
# so a long-running session's file (and the replayed token count) stays
# bounded. The system prompt is always kept.
MAX_HISTORY_TURNS = 40

SCHEMA = 1


def _slug(text: str, limit: int = 40) -> str:
    """Filename-safe slug of the conversation's first user message."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "conversation"


def prune_messages(messages: list[dict], max_turns: int = MAX_HISTORY_TURNS) -> list[dict]:
    """Keep the system prompt plus the newest `max_turns` user-started turns.

    A turn starts at every {"role": "user"} message and spans everything
    after it (replies, tool exchanges) until the next user message — so
    pruning never separates an assistant tool-request from its tool
    results and the result always stays structurally valid.
    """
    system = [m for m in messages if m.get("role") == "system"][:1]
    body = [m for m in messages if m.get("role") != "system"]

    starts = [i for i, m in enumerate(body) if m.get("role") == "user"]
    if len(starts) > max_turns:
        body = body[starts[-max_turns]:]
    return system + body


class ChatStore:
    """Writes conversations to disk and reads them back."""

    def __init__(self, directory: str | os.PathLike) -> None:
        self.directory = Path(directory).expanduser()
        # File the active conversation is persisted to; fixed at first save
        # so every subsequent save updates the same file in place.
        self._current_path: Path | None = None

    # --- write path -----------------------------------------------------------

    @property
    def current_file(self) -> str | None:
        """Name of the file the active conversation is saved to, if any."""
        return self._current_path.name if self._current_path else None

    def save(
        self,
        messages: list[dict],
        investigation_file: str | None = None,
    ) -> Path | None:
        """Persist `messages`, creating the conversation's file on first save.

        Returns the file path, or None when the store is unusable. Never
        raises — persistence must not be able to break a conversation.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self._current_path is None:
                first_user = next(
                    (m.get("content", "") for m in messages
                     if m.get("role") == "user" and m.get("content")),
                    "conversation",
                )
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                self._current_path = self._collision_free(
                    f"{stamp}-{_slug(str(first_user))}"
                )
            payload = {
                "schema": SCHEMA,
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "status": "open",
                "investigation_file": investigation_file,
                "messages": prune_messages(messages),
            }
            tmp = self._current_path.with_name(self._current_path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._current_path)
            return self._current_path
        except OSError:
            return None

    def close_current(self) -> None:
        """Mark the active conversation closed (it will not auto-restore) and
        stop tracking it. The saved copy stays on disk as history."""
        if self._current_path is None:
            return
        try:
            data = self._read(self._current_path)
            if data is not None:
                data["status"] = "closed"
                data["saved_at"] = datetime.datetime.now().isoformat(
                    timespec="seconds"
                )
                tmp = self._current_path.with_name(
                    self._current_path.name + ".tmp"
                )
                tmp.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(self._current_path)
        except OSError:
            pass  # best-effort: worst case it auto-restores once more
        self._current_path = None

    def _collision_free(self, base: str) -> Path:
        path = self.directory / f"{base}.json"
        n = 2
        while path.exists():
            path = self.directory / f"{base}-{n}.json"
            n += 1
        return path

    # --- read path ------------------------------------------------------------

    def resume_latest(self) -> tuple[list[dict], str | None] | None:
        """Newest open conversation as (messages, investigation_file), or None.

        Closed and corrupt files are skipped. Remembers the file so
        subsequent saves update it in place.
        """
        for path in self._saved_files():
            data = self._read(path)
            if data is None or data.get("status") != "open":
                continue
            messages = data.get("messages")
            if not isinstance(messages, list) or not all(
                isinstance(m, dict) and isinstance(m.get("role"), str)
                for m in messages
            ):
                continue
            self._current_path = path
            investigation_file = data.get("investigation_file")
            return messages, (
                investigation_file if isinstance(investigation_file, str) else None
            )
        return None

    def list_saved(self) -> list[dict]:
        """Every saved conversation, newest first: file, first user message,
        turns, status, saved_at."""
        rows = []
        for path in self._saved_files():
            data = self._read(path)
            if data is None:
                continue
            messages = data.get("messages") or []
            first_user = next(
                (str(m.get("content", "")) for m in messages
                 if isinstance(m, dict) and m.get("role") == "user"),
                "(no user messages)",
            )
            rows.append(
                {
                    "file": path.name,
                    "first_message": first_user,
                    "turns": sum(
                        1 for m in messages
                        if isinstance(m, dict) and m.get("role") == "user"
                    ),
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


def default_chat_store() -> ChatStore:
    """Store at the default location; AGENT_CHAT_DIR overrides it."""
    override = os.getenv("AGENT_CHAT_DIR")
    return ChatStore(override or DEFAULT_DIR)


# Process-level store (single-threaded CLI), resolved lazily
# (explicit > AGENT_CHAT_DIR > the default home directory), disableable for
# tests. set_chat_store(None) turns persistence off — the same pattern the
# investigation store uses in tools/investigation.py.
_chat_store: ChatStore | None = None
_chat_store_disabled: bool = False


def set_chat_store(store: ChatStore | None) -> None:
    """Replace the persistence store (tests pass None to disable saving)."""
    global _chat_store, _chat_store_disabled
    _chat_store = store
    _chat_store_disabled = store is None


def _get_chat_store() -> ChatStore | None:
    """The process store, or None when persistence is off/unavailable."""
    global _chat_store
    if _chat_store_disabled:
        return None
    if _chat_store is None:
        try:
            _chat_store = default_chat_store()
        except Exception:  # noqa: BLE001 — persistence must never break the agent
            return None
    return _chat_store


# --- thin functions shared by the agent and the CLI --------------------------

def save_conversation(
    messages: list[dict],
    investigation_file: str | None = None,
) -> str:
    """Auto-save the conversation; returns a short note for the caller.

    Best-effort: an unavailable store returns "" (no note, no error).
    """
    store = _get_chat_store()
    if store is None:
        return ""
    path = store.save(messages, investigation_file)
    if path is None:
        return "\n(note: conversation persistence unavailable — not saved)"
    return f"\n(conversation saved to {path})"


def load_resumable_conversation() -> tuple[list[dict], str | None] | None:
    """The newest open conversation as (messages, investigation_file), or None."""
    store = _get_chat_store()
    if store is None:
        return None
    return store.resume_latest()


def close_conversation() -> None:
    """Mark the active conversation closed (so it will not auto-restore)."""
    store = _get_chat_store()
    if store is not None:
        store.close_current()


def list_conversations_text() -> str | None:
    """Rendered list of saved conversations, or None when there is nothing."""
    store = _get_chat_store()
    if store is None:
        return None
    rows = store.list_saved()
    if not rows:
        return None
    current = store.current_file
    lines = ["**Saved conversations** (newest first)"]
    for row in rows:
        marker = "  <- active" if row["file"] == current else ""
        first = row["first_message"]
        if len(first) > 60:
            first = first[:57] + "..."
        lines.append(
            f"- [{row['status']}] {row['file']}{marker} — {row['turns']} turn(s) "
            f"— {first}"
        )
    return "\n".join(lines)


def chat_directory_text() -> str | None:
    """Where conversations are being saved, or None when persistence is off."""
    store = _get_chat_store()
    return str(store.directory) if store is not None else None
