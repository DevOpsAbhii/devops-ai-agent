"""Tool contract for the DevOps investigation agent.

All tools are READ-ONLY by construction: an executor inspects the system and
returns text evidence; nothing in this module can mutate state, and tools
never accept arbitrary commands (they select from hard-coded, allowlisted
invocations).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

# Ceiling for how much of a tool result is fed back to the model in one turn.
MAX_TOOL_OUTPUT_CHARS = 8_000


class ToolError(Exception):
    """Raised by an executor when a tool could not produce its result."""


def truncate_output(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Cut very long output so the TOTAL returned length stays <= limit.

    Head and tail of the original are kept; a short digest line connects
    them. 64 characters are reserved for that line, which is enough for any
    realistic input size.
    """
    if len(text) <= limit:
        return text

    body = max(2, limit - 64)  # budget left for actual content
    head_len = body // 2
    tail_len = body - head_len

    omitted = len(text) - body
    marker = f"\n… [{omitted} characters omitted] …\n"
    if len(marker) > limit - body:
        marker = "\n… (output truncated) …\n"

    return text[:head_len] + marker + text[-tail_len:]


def read_command_output(argv: Sequence[str], timeout: int = 10) -> str:
    """Run an allowlisted read-only command and return its output as evidence.

    Raises ToolError (so the caller never feeds unvalidated input to a
    shell) when the binary is missing, the command times out, or it exits
    non-zero — in the failure cases, the captured output is embedded in the
    error so the model sees real diagnostics rather than a generic message.

    Successful output is prefixed with the literal command line (so the
    model can tell it is real captured output, not a canned string) and
    truncated to MAX_TOOL_OUTPUT_CHARS.
    """
    binary = argv[0]
    if shutil.which(binary) is None:
        raise ToolError(
            f"required executable {binary!r} is not installed on this host"
        )
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command {binary} timed out after {timeout}s") from exc

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise ToolError(
            f"command {binary} exited with code {proc.returncode}:\n"
            f"{output or '(no output)'}"
        )
    if not output:
        output = f"(command {' '.join(argv)} returned no output, exit code 0)"
    return truncate_output(f"$ {' '.join(argv)}\n{output}")


@dataclass(frozen=True)
class Tool:
    """A read-only capability the model can call while investigating.

    Attributes:
        name: stable identifier the model uses to request this tool.
        description: when/how to use it; sent to the model alongside the schema.
        parameters: JSON Schema describing the arguments the tool accepts.
        executor: local callable(args: dict) -> str. It receives the *parsed*
            JSON arguments and returns the text fed back to the model as
            evidence. Must be read-only and must never fabricate output.
    """

    name: str
    description: str
    parameters: dict
    executor: Callable[[dict], str]

    def schema(self) -> dict:
        """Render this tool in the OpenAI-compatible `tools` request format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }