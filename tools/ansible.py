"""Read-only Ansible tools (Phase 8).

Two inventory/playbook inspection tools: `ansible-inventory --list` (see the
hosts and groups an inventory resolves to) and `ansible-playbook --list-tasks
--list-hosts` (see what a playbook WOULD do, without doing it). Both are pure
listing modes — they connect to no managed host and change nothing.

Safety model:
- Only fixed argv templates with the --list / --list-tasks / --list-hosts
  modes exist. There is no playbook-execution path: no run, no syntax-check
  with extra vars, no ad-hoc `ansible` module invocations.
- Arguments are path-shaped, so they are validated as RELATIVE paths: no
  leading '/', no leading '-', no '..' segment (no traversal), no '/'. (a
  slash could smuggle a second path element; inventory/playbook names are
  meant to resolve against the working directory or ansible.cfg).
- ansible / ansible-inventory must be installed; if absent, the exact error
  is returned — nothing is invented.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

_TIMEOUT_S = 15

# Relative, dash-free, traversal-free path fragment the CLIs receive.
_SAFE_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,200}")


def _checked_path(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_PATH_RE.fullmatch(value)
        or ".." in value
    ):
        raise ToolError(
            f"invalid {kind} {value!r}: expected a relative path fragment "
            "(no '/', no leading '-', no '..') resolving in the working "
            "directory or ansible.cfg"
        )
    return value


def _ansible_inventory(args: dict) -> str:
    inventory = args.get("inventory")
    argv = ["ansible-inventory"]
    if inventory is not None:
        argv += ["--inventory", _checked_path(inventory, "inventory")]
    argv += ["--list"]
    return read_command_output(tuple(argv), timeout=_TIMEOUT_S)


def _ansible_playbook_tasks(args: dict) -> str:
    playbook = _checked_path(args.get("playbook"), "playbook")
    return read_command_output(
        ("ansible-playbook", "--list-tasks", "--list-hosts", playbook),
        timeout=_TIMEOUT_S,
    )


ANSIBLE_INVENTORY = Tool(
    name="ansible_inventory",
    description=(
        "Dump the resolved Ansible inventory as JSON (ansible-inventory "
        "--list): groups, hosts, hostvars. Use to answer 'which hosts does "
        "this inventory actually target' before/during an incident, or to "
        "find the right host for a hypothesis. Without 'inventory' it uses "
        "the ansible.cfg / default inventory of the working directory. "
        "Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "inventory": {
                "type": "string",
                "description": "Optional inventory source (file or group "
                "name relative to the working directory).",
            }
        },
        "additionalProperties": False,
    },
    executor=_ansible_inventory,
)

ANSIBLE_PLAYBOOK_TASKS = Tool(
    name="ansible_playbook_tasks",
    description=(
        "List the tasks and target hosts of a playbook (ansible-playbook "
        "--list-tasks --list-hosts) WITHOUT running it. Use to see what a "
        "deploy playbook would change, or to map a failing host back to the "
        "task that touches it. Read-only; connects to no host."
    ),
    parameters={
        "type": "object",
        "properties": {
            "playbook": {
                "type": "string",
                "description": "Playbook file, relative to the working "
                "directory (e.g. site.yml).",
            }
        },
        "required": ["playbook"],
        "additionalProperties": False,
    },
    executor=_ansible_playbook_tasks,
)

register(ANSIBLE_INVENTORY)
register(ANSIBLE_PLAYBOOK_TASKS)
