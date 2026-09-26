"""Read-only Argo CD tools (Phase 9).

Two tools over the argocd CLI: list Applications (argocd app list) and one
Application's full status (argocd app get). GitOps health questions — "is
the cluster in sync with git", "why is my app degraded/out-of-sync" — start
here.

Safety model:
- Only fixed argv templates with the list/get verbs exist. There is no app
  create, sync, rollback, terminate-op, delete, or repo path — argocd's
  mutating side is unreachable by construction.
- Application names are validated (DNS-style, like Kubernetes objects)
  before reaching argocd — blocks flag injection.
- The CLI must be installed AND logged in (`argocd login`); otherwise the
  exact CLI error is returned — nothing is invented.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

_NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?")
_TIMEOUT_S = 15


def _check_name(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 253
        or not _NAME_RE.fullmatch(value)
    ):
        raise ToolError(
            f"invalid Argo CD {kind} name {value!r}: expected lowercase "
            "letters, digits, '-' or '.', max 253 characters"
        )
    return value


def _argocd_apps(args: dict) -> str:
    return read_command_output(
        ("argocd", "app", "list", "--output", "json"),
        timeout=_TIMEOUT_S,
    )


def _argocd_app_status(args: dict) -> str:
    app = _check_name(args.get("app"), "application")
    return read_command_output(
        ("argocd", "app", "get", app),
        timeout=_TIMEOUT_S,
    )


ARGOCD_APPS = Tool(
    name="argocd_apps",
    description=(
        "List Argo CD Applications as JSON (argocd app list): name, sync "
        "status (Synced/OutOfSync), health (Healthy/Degraded/Progressing), "
        "target/destination, git revision. Use for GitOps questions — 'is "
        "the cluster in sync with git', 'which apps are degraded'. "
        "Requires the argocd CLI installed and logged in. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_argocd_apps,
)

ARGOCD_APP_STATUS = Tool(
    name="argocd_app_status",
    description=(
        "One Argo CD Application's detail (argocd app get): sync and health "
        "status per resource, the git revision deployed, conditions, and "
        "recent operations. Use with argocd_apps to explain 'why is this "
        "app OutOfSync/Degraded'. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "Application name.",
            }
        },
        "required": ["app"],
        "additionalProperties": False,
    },
    executor=_argocd_app_status,
)

register(ARGOCD_APPS)
register(ARGOCD_APP_STATUS)
