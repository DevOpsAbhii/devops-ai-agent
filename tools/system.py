"""Read-only Linux system tools (Phase 5).

Four tools for on-host operational problems: service status (systemctl),
service journal logs (journalctl), open TCP ports (ss), and the top CPU
consumers (ps). Same contract and safety model as the other modules.

Safety model:
- Only fixed argv templates are ever built: `systemctl status <unit>
  --no-pager`, `journalctl -u <unit> --no-pager -n <lines>`, `ss -tlnp`,
  `ps aux --sort=-%cpu --no-headers`. No free-form command text, no shell.
- The unit name is validated against systemd's allowed character set
  (letters, digits, '.', '-', '_', '@', ':') with no leading dash — this
  blocks path separators ('/'), flag injection ("-l"), and garbage.
- Every command is read-only: status/log inspection and listing, nothing
  that starts, stops, edits, or reloads a unit.
- systemctl/journalctl/ss/ps must be installed on the host; if missing the
  exact error is returned — nothing is invented.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# systemd unit names: letters, digits, and '.', '-', '_', '@', ':' — no '/',
# no leading dash, max 255 chars.
_UNIT_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._@:\-]{0,253})?")
_UNIT_LIMIT = 255

# journalctl can sit waiting on a busy journal; bound every call.
_TIMEOUT_S = 10


def _check_unit(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _UNIT_LIMIT
        or not _UNIT_RE.fullmatch(value)
    ):
        raise ToolError(
            f"invalid systemd unit name {value!r}: expected letters, digits, "
            "'.', '-', '_', '@' or ':', max 255 chars (e.g. 'sshd', "
            "'docker.service', 'ssh@0.0.0.0:22')"
        )
    return value


def _sys_service_status(args: dict) -> str:
    unit = _check_unit(args.get("unit"), "unit")
    return read_command_output(
        ("systemctl", "status", unit, "--no-pager"), timeout=_TIMEOUT_S
    )


def _sys_service_logs(args: dict) -> str:
    unit = _check_unit(args.get("unit"), "unit")
    try:
        lines = int(args.get("lines", 100))
    except (TypeError, ValueError):
        raise ToolError("lines must be an integer between 1 and 500")
    if not 1 <= lines <= 500:
        raise ToolError("lines must be between 1 and 500")
    return read_command_output(
        ("journalctl", "-u", unit, "--no-pager", "-n", str(lines)),
        timeout=_TIMEOUT_S,
    )


def _sys_open_ports(args: dict) -> str:
    return read_command_output(("ss", "-tlnp"), timeout=_TIMEOUT_S)


def _sys_top_processes(args: dict) -> str:
    return read_command_output(
        ("ps", "aux", "--sort=-%cpu", "--no-headers"), timeout=_TIMEOUT_S
    )


SYS_SERVICE_STATUS = Tool(
    name="sys_service_status",
    description=(
        "Fetch the status of one systemd unit (service, socket, target, ...): "
        "loaded/active state, Main PID, and the most recent journal lines. The "
        "primary tool for 'why is this service down / restarting'. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "unit": {
                "type": "string",
                "description": "Unit name, e.g. 'sshd', 'docker.service', "
                "'multi-user.target', 'ssh@0.0.0.0:22'.",
            }
        },
        "required": ["unit"],
        "additionalProperties": False,
    },
    executor=_sys_service_status,
)

SYS_SERVICE_LOGS = Tool(
    name="sys_service_logs",
    description=(
        "Fetch the tail of a systemd unit's journal logs via journalctl. Use "
        "with sys_service_status to see the actual error lines a service wrote "
        "before failing/restarting. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "unit": {
                "type": "string",
                "description": "Unit name, e.g. 'sshd', 'docker.service'.",
            },
            "lines": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 100,
                "description": "How many lines to tail (1–500).",
            },
        },
        "required": ["unit"],
        "additionalProperties": False,
    },
    executor=_sys_service_logs,
)

SYS_OPEN_PORTS = Tool(
    name="sys_open_ports",
    description=(
        "List TCP ports currently listening on the host (ss -tlnp), with the "
        "process that owns each socket. Use for 'is port X in use', 'what is "
        "bound to this port', port conflicts. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_sys_open_ports,
)

SYS_TOP_PROCESSES = Tool(
    name="sys_top_processes",
    description=(
        "List the processes consuming the most CPU on the host (ps aux sorted "
        "by %cpu, no header). Use for 'what is eating CPU', runaway processes. "
        "Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_sys_top_processes,
)

register(SYS_SERVICE_STATUS)
register(SYS_SERVICE_LOGS)
register(SYS_OPEN_PORTS)
register(SYS_TOP_PROCESSES)