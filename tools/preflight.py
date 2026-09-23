"""Read-only host inspection tool — the first *real* tool.

This proves the whole tool loop (model requests a tool -> local executor
runs a real command -> real output is fed back as evidence) while staying
strictly read-only.

Safety model (defense in depth):
- The model may only choose among the static commands below; its parameters
  select an allowlisted command and can never carry arbitrary command text.
- The executor re-validates every argument against the allowlist before
  running anything. Never trust the model's arguments.
- All commands are read-only and harmless: date, uname, uptime, df, free.
  Mutating verbs cannot appear here by construction.
"""

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Static, allowlisted invocations. NEVER interpolate model-provided text here.
_COMMANDS: dict[str, tuple[str, ...]] = {
    "date_utc": ("date", "-u", "+%Y-%m-%dT%H:%M:%SZ"),
    "uname": ("uname", "-a"),
    "uptime": ("uptime",),
    "disk_usage": ("df", "-h", "-T"),
    "memory": ("free", "-h"),
}


def _run_allowlisted(args: dict) -> str:
    command_key = args.get("command")
    if not isinstance(command_key, str) or command_key not in _COMMANDS:
        allowed = ", ".join(sorted(_COMMANDS))
        raise ToolError(f"unknown command {command_key!r}; allowed commands: {allowed}")
    return read_command_output(_COMMANDS[command_key])


SYSTEM_INFO = Tool(
    name="system_info",
    description=(
        "Inspect the host machine the agent runs on. Returns one read-only "
        "fact: current UTC timestamp, OS/kernel info, uptime, disk usage, or "
        "memory usage."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": sorted(_COMMANDS),
                "description": "Which read-only fact to collect from the host.",
            }
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    executor=_run_allowlisted,
)

register(SYSTEM_INFO)