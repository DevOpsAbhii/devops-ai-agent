"""Read-only Helm release tools (Phase 9).

Three tools over the helm CLI: list releases (helm list), one release's
status (helm status), and its revision history (helm history). All are
reads of release metadata Helm keeps in the cluster — nothing here installs,
upgrades, rolls back or uninstalls anything.

Safety model (same shape as tools/kubernetes.py):
- Only fixed argv templates with the list/status/history verbs exist. There
  is no install, upgrade, rollback, uninstall, delete or template path.
- Release and namespace names are validated against Kubernetes DNS naming
  rules before touching helm — blocks flag injection and garbage input.
- `--max` on history is a bounded integer (1–50).
- helm must be installed and pointed at a cluster (its own kubeconfig
  handling); missing/unreachable surfaces as the exact CLI error.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Helm release names follow Kubernetes naming: lowercase DNS-style.
_NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?")
_TIMEOUT_S = 15


def _check_name(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 253
        or not _NAME_RE.fullmatch(value)
    ):
        raise ToolError(
            f"invalid Helm {kind} name {value!r}: expected lowercase "
            "letters, digits, '-' or '.', max 253 characters"
        )
    return value


def _namespace(args: dict) -> str:
    return _check_name(args.get("namespace") or "default", "namespace")


def _checked_max(args: dict) -> int:
    try:
        maximum = int(args.get("max", 10))
    except (TypeError, ValueError):
        raise ToolError("max must be an integer between 1 and 50")
    if not 1 <= maximum <= 50:
        raise ToolError("max must be between 1 and 50")
    return maximum


def _helm_list(args: dict) -> str:
    if args.get("all_namespaces"):
        argv = ("helm", "list", "--all-namespaces")
    else:
        argv = ("helm", "list", "-n", _namespace(args))
    return read_command_output(argv, timeout=_TIMEOUT_S)


def _helm_status(args: dict) -> str:
    release = _check_name(args.get("release"), "release")
    namespace = _namespace(args)
    return read_command_output(
        ("helm", "status", release, "-n", namespace),
        timeout=_TIMEOUT_S,
    )


def _helm_history(args: dict) -> str:
    release = _check_name(args.get("release"), "release")
    namespace = _namespace(args)
    return read_command_output(
        ("helm", "history", release, "-n", namespace,
         "--max", str(_checked_max(args))),
        timeout=_TIMEOUT_S,
    )


HELM_LIST = Tool(
    name="helm_list",
    description=(
        "List Helm releases (helm list): name, namespace, revision, "
        "updated time, status (deployed/failed/pending-upgrade), chart "
        "version, app version. Use for 'which releases exist and are they "
        "healthy', and to find the release behind a broken workload. "
        "Requires helm + a configured cluster. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Namespace to list (default: \"default\").",
            },
            "all_namespaces": {
                "type": "boolean",
                "description": "List across all namespaces instead of one.",
            },
        },
        "additionalProperties": False,
    },
    executor=_helm_list,
)

HELM_STATUS = Tool(
    name="helm_status",
    description=(
        "One Helm release's status (helm status): revision, state, chart, "
        "and the release's last-deployed notes. Use to see why a release is "
        "failed or pending and which revision is live. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "release": {
                "type": "string",
                "description": "Release name.",
            },
            "namespace": {
                "type": "string",
                "description": "Namespace of the release (default: \"default\").",
            },
        },
        "required": ["release"],
        "additionalProperties": False,
    },
    executor=_helm_status,
)

HELM_HISTORY = Tool(
    name="helm_history",
    description=(
        "A Helm release's revision history (helm history --max): each "
        "revision with its status, chart version, and updated time. Use to "
        "correlate an incident start with an upgrade, or to find the last "
        "good revision. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "release": {
                "type": "string",
                "description": "Release name.",
            },
            "namespace": {
                "type": "string",
                "description": "Namespace of the release (default: \"default\").",
            },
            "max": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 10,
                "description": "How many revisions to show (1–50).",
            },
        },
        "required": ["release"],
        "additionalProperties": False,
    },
    executor=_helm_history,
)

register(HELM_LIST)
register(HELM_STATUS)
register(HELM_HISTORY)
