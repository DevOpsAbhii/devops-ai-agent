"""Read-only Docker tools (Phase 5).

Five tools for container problems on the host: list containers (docker ps),
inspect one (JSON), tail logs, live resource stats (docker stats --no-stream),
and the local image list. Same contract/safety model as the other modules.

Safety model:
- Only fixed argv templates exist with the docker verbs ps, inspect, logs,
  stats, images — all read-only. There is no run, start, stop, restart,
  rm, rmi, pull, push, exec, build or create path.
- `docker stats` is hard-coded with `--no-stream`: without it the command
  follows forever and would hang a turn.
- Container/image names are validated (letters, digits, '.', '-', '_', no
  leading dash) — blocks flag injection and path traversal.
- Docker must be installed and the daemon running; if not, the exact error
  is returned — nothing is invented. A dangling or dead daemon surfaces as
  a real ToolError, which the model must report honestly.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Docker names: letters, digits, '.', '-', '_'; must start/end alphanumeric.
_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._\-]{0,127}")
_TIMEOUT_S = 10


def _check_name(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not _NAME_RE.fullmatch(value)
    ):
        raise ToolError(
            f"invalid Docker {kind} name {value!r}: expected letters, digits, "
            "'.', '-' or '_', max 128 chars"
        )
    return value


def _checked_lines(args: dict) -> int:
    try:
        lines = int(args.get("lines", 100))
    except (TypeError, ValueError):
        raise ToolError("lines must be an integer between 1 and 500")
    if not 1 <= lines <= 500:
        raise ToolError("lines must be between 1 and 500")
    return lines


def _docker_ps(args: dict) -> str:
    return read_command_output(("docker", "ps", "-a"), timeout=_TIMEOUT_S)


def _docker_inspect(args: dict) -> str:
    name = _check_name(args.get("name"), "container or image")
    return read_command_output(("docker", "inspect", name), timeout=_TIMEOUT_S)


def _docker_logs(args: dict) -> str:
    name = _check_name(args.get("container"), "container")
    return read_command_output(
        ("docker", "logs", "--tail", str(_checked_lines(args)), name),
        timeout=_TIMEOUT_S,
    )


def _docker_stats(args: dict) -> str:
    return read_command_output(("docker", "stats", "--no-stream"), timeout=_TIMEOUT_S)


def _docker_images(args: dict) -> str:
    return read_command_output(("docker", "images"), timeout=_TIMEOUT_S)


DOCKER_PS = Tool(
    name="docker_ps",
    description=(
        "List all containers (running and stopped) with status: container id, "
        "image, command, status (Up/X minutes, Exited (code) ...), names. The "
        "first tool for 'is my container running / why did it stop'. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_docker_ps,
)

DOCKER_INSPECT = Tool(
    name="docker_inspect",
    description=(
        "Inspect one container or image by name as JSON — state, exit code, "
        "restart count, mounts, env, image id. Use with docker_ps to see the "
        "details behind a container's state. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Container or image name/id to inspect.",
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    executor=_docker_inspect,
)

DOCKER_LOGS = Tool(
    name="docker_logs",
    description=(
        "Fetch the tail of a container's stdout/stderr logs as plain text. Use "
        "with docker_ps/docker_inspect to see the error that made a container "
        "exit or crash-loop. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name/id."},
            "lines": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 100,
                "description": "How many lines to tail (1–500).",
            },
        },
        "required": ["container"],
        "additionalProperties": False,
    },
    executor=_docker_logs,
)

DOCKER_STATS = Tool(
    name="docker_stats",
    description=(
        "One snapshot of live resource usage for running containers: CPU %, "
        "memory used/limit, net/block I/O. Use for 'which container burns CPU "
        "or RAM'. Read-only; never blocks (always --no-stream)."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_docker_stats,
)

DOCKER_IMAGES = Tool(
    name="docker_images",
    description=(
        "List local container images: repository, tag, image id, size. Use to "
        "check whether an image/tag exists locally or is dangling. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_docker_images,
)

register(DOCKER_PS)
register(DOCKER_INSPECT)
register(DOCKER_LOGS)
register(DOCKER_STATS)
register(DOCKER_IMAGES)