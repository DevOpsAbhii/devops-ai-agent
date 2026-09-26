"""Read-only Docker tools (Phases 5, 8, 9).

Ten tools for container problems on the host: list containers (docker ps),
inspect one (JSON), tail logs, live resource stats (docker stats --no-stream),
the local image list, networks, volumes, disk usage (Phase 8), and (Phase 9)
Docker Compose project listing + a project's services. Same contract/safety
model as the other modules.

Safety model:
- Only fixed argv templates exist with the read-only docker verbs ps, inspect,
  logs, stats, images, network ls, volume ls, system df, compose ls, compose
  ps. There is no run, start, stop, restart, rm, rmi, pull, push, exec, build,
  create, prune or compose-up/down path.
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

# --- Phase 8: Docker depth — networks, volumes, disk usage -------------------

def _docker_networks(args: dict) -> str:
    return read_command_output(("docker", "network", "ls"), timeout=_TIMEOUT_S)


def _docker_volumes(args: dict) -> str:
    return read_command_output(("docker", "volume", "ls"), timeout=_TIMEOUT_S)


def _docker_disk_usage(args: dict) -> str:
    return read_command_output(("docker", "system", "df"), timeout=_TIMEOUT_S)


DOCKER_NETWORKS = Tool(
    name="docker_networks",
    description=(
        "List Docker networks on the host (docker network ls): name, driver, "
        "scope. Use for 'which network does my container use', connectivity "
        "and bridge/overlay questions. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_docker_networks,
)

DOCKER_VOLUMES = Tool(
    name="docker_volumes",
    description=(
        "List Docker volumes on the host (docker volume ls): volume names and "
        "drivers. Use for 'does the volume my data lives in exist', dangling "
        "volume checks. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_docker_volumes,
)

DOCKER_DISK_USAGE = Tool(
    name="docker_disk_usage",
    description=(
        "Docker disk usage on the host (docker system df): how much space "
        "images, containers, volumes and the build cache consume, with "
        "reclaimable amounts. Use for 'is the disk full because of Docker'. "
        "Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_docker_disk_usage,
)

# --- Phase 9: Docker Compose — compose project listing and one project's
# services. Same contract: fixed argv, validated project name, ps/ls only. ---

def _docker_compose_ls(args: dict) -> str:
    return read_command_output(("docker", "compose", "ls"), timeout=_TIMEOUT_S)


def _docker_compose_ps(args: dict) -> str:
    project = args.get("project")
    if project is not None:
        _check_name(project, "compose project")
        argv = ("docker", "compose", "-p", project, "ps", "-a")
    else:
        # No -p: reads the compose project of the current working directory.
        argv = ("docker", "compose", "ps", "-a")
    return read_command_output(argv, timeout=_TIMEOUT_S)


DOCKER_COMPOSE_LS = Tool(
    name="docker_compose_ls",
    description=(
        "List running Docker Compose projects on the host (docker compose "
        "ls): project name, status, config files. Use to see which compose "
        "stacks exist before looking at one's services. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_docker_compose_ls,
)

DOCKER_COMPOSE_PS = Tool(
    name="docker_compose_ps",
    description=(
        "List the containers of a Docker Compose project (docker compose "
        "ps -a): service, state, ports — running AND stopped. Use with "
        "docker_compose_ls to see what a stack is made of, or which service "
        "inside a project exited. Without 'project', uses the compose file "
        "in the current working directory. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Optional compose project name (from "
                "docker_compose_ls).",
            }
        },
        "additionalProperties": False,
    },
    executor=_docker_compose_ps,
)

register(DOCKER_PS)
register(DOCKER_INSPECT)
register(DOCKER_LOGS)
register(DOCKER_STATS)
register(DOCKER_IMAGES)
register(DOCKER_NETWORKS)
register(DOCKER_VOLUMES)
register(DOCKER_DISK_USAGE)
register(DOCKER_COMPOSE_LS)
register(DOCKER_COMPOSE_PS)