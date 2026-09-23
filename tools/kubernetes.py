"""Read-only Kubernetes investigation tools (Phase 3).

Three kubectl-backed tools: pod status (the CrashLoopBackOff evidence
source), pod logs, and deployment/rollout status. They follow the same
contract and safety model as tools/preflight.py but talk to a cluster via
`kubectl` — no extra Python dependency, and parity with what ops teams
actually run.

Safety model (defense in depth):
- Only the `get` and `logs` kubectl verbs exist, hard-coded in the argv
  templates below. There is no delete, restart, edit, apply, scale, exec or
  create path — and never a `sh -c`, so nothing is ever parsed by a shell.
- Object names (pod / deployment / namespace) are validated against the
  Kubernetes naming rules before touching kubectl; this blocks flag
  injection (names starting with "-") and garbage input. Never trust the
  model's arguments.
- `--request-timeout` plus a subprocess timeout bound slow/hung clusters.
- Output is real kubectl JSON/text, truncated to the shared cap. Python does
  NOT parse the pod/deployment spec (stable across kubectl versions and all
  cluster states); the model reads the raw output, which is exactly the
  evidence an engineer would see.
- kubectl must be installed and configured (KUBECONFIG / default context)
  on the host. If it is missing or the cluster is unreachable, the exact
  error is returned — nothing is ever invented.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Kubernetes object names: lowercase letters, digits, '-' or '.', DNS-style,
# at most 253 characters, starting and ending with an alphanumeric.
_NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?")

# Bound cluster queries so a hanging API server (or `kubectl logs`
# following a stream) can never stall a turn.
_TIMEOUT_S = 15


def _check_name(value, kind: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 253
        or not _NAME_RE.fullmatch(value)
    ):
        raise ToolError(
            f"invalid Kubernetes {kind} name {value!r}: expected lowercase "
            "letters, digits, '-' or '.', max 253 characters"
        )
    return value


def _namespace(args: dict) -> str:
    return _check_name(args.get("namespace") or "default", "namespace")


def _k8s_pod_status(args: dict) -> str:
    pod = _check_name(args.get("pod"), "pod")
    namespace = _namespace(args)
    return read_command_output(
        ("kubectl", "get", "pod", pod, "-n", namespace, "-o", "json",
         "--request-timeout=10"),
        timeout=_TIMEOUT_S,
    )


def _k8s_pod_logs(args: dict) -> str:
    pod = _check_name(args.get("pod"), "pod")
    namespace = _namespace(args)
    try:
        lines = int(args.get("lines", 100))
    except (TypeError, ValueError):
        raise ToolError("lines must be an integer between 1 and 500")
    if not 1 <= lines <= 500:
        raise ToolError("lines must be between 1 and 500")
    return read_command_output(
        ("kubectl", "logs", pod, "-n", namespace, "--tail", str(lines),
         "--request-timeout=10"),
        timeout=_TIMEOUT_S,
    )


def _k8s_deployment_status(args: dict) -> str:
    deployment = _check_name(args.get("deployment"), "deployment")
    namespace = _namespace(args)
    return read_command_output(
        ("kubectl", "get", "deployment", deployment, "-n", namespace, "-o",
         "json", "--request-timeout=10"),
        timeout=_TIMEOUT_S,
    )


# Human-readable hint that is NOT part of the docs — helps readme readers —
# but the schema `description` is what the model actually sees.
K8S_POD_STATUS = Tool(
    name="k8s_pod_status",
    description=(
        "Fetch a Kubernetes pod (by name, in a namespace) as JSON, using "
        "kubectl's pod liveness API. Key fields: 'status.phase' (Running/..."
        "), 'status.containerStatuses[].restartCount' (climbing count on "
        "repeated crashes), and 'status.conditions[]' diagnostics (e.g. "
        "reason 'ContainersNotReady' with a message naming unready "
        "containers) — the evidence for CrashLoopBackOff investigations. "
        "Requires kubectl configured against a cluster. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pod": {"type": "string", "description": "Name of the pod."},
            "namespace": {
                "type": "string",
                "description": "Namespace of the pod (default: \"default\").",
            },
        },
        "required": ["pod"],
        "additionalProperties": False,
    },
    executor=_k8s_pod_status,
)

K8S_POD_LOGS = Tool(
    name="k8s_pod_logs",
    description=(
        "Fetch the tail of a pod's logs as plain text. Use with k8s_pod_status "
        "to see the crash/backoff error messages. Requires kubectl configured "
        "against a cluster. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pod": {"type": "string", "description": "Name of the pod."},
            "namespace": {
                "type": "string",
                "description": "Namespace of the pod (default: \"default\").",
            },
            "lines": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 100,
                "description": "How many lines to tail (1–500).",
            },
        },
        "required": ["pod"],
        "additionalProperties": False,
    },
    executor=_k8s_pod_logs,
)

K8S_DEPLOYMENT_STATUS = Tool(
    name="k8s_deployment_status",
    description=(
        "Fetch a Kubernetes Deployment (by name, in a namespace) as JSON, "
        "including metadata and rollout status. Use to assess whether a "
        "rollout completed, is degraded, or failed. Requires kubectl "
        "configured against a cluster. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "deployment": {"type": "string", "description": "Name of the Deployment."},
            "namespace": {
                "type": "string",
                "description": "Namespace of the Deployment (default: \"default\").",
            },
        },
        "required": ["deployment"],
        "additionalProperties": False,
    },
    executor=_k8s_deployment_status,
)

def _k8s_events(args: dict) -> str:
    namespace = _namespace(args)
    argv = [
        "kubectl", "get", "events",
        "-n", namespace,
        "--sort-by=.lastTimestamp",
        "-o", "wide",
    ]
    # Optional: filter to events about one object (validated name only).
    involving = args.get("involving")
    if involving is not None:
        argv += ["--field-selector", f"involvedObject.name={_check_name(involving, 'object')}"]
    argv += ["--request-timeout=10"]
    return read_command_output(tuple(argv), timeout=_TIMEOUT_S)


def _k8s_nodes(args: dict) -> str:
    return read_command_output(
        ("kubectl", "get", "nodes", "-o", "json", "--request-timeout=10"),
        timeout=_TIMEOUT_S,
    )


def _k8s_services(args: dict) -> str:
    namespace = _namespace(args)
    return read_command_output(
        ("kubectl", "get", "services", "-n", namespace, "-o", "json",
         "--request-timeout=10"),
        timeout=_TIMEOUT_S,
    )


K8S_EVENTS = Tool(
    name="k8s_events",
    description=(
        "Fetch recent cluster Events in a namespace, newest last (kubectl get "
        "events, wide): Warning/type, reason, message, object, and timestamps "
        "for pods, deployments etc. The record of WHAT happened — use it when "
        "pod/deployment conditions don't explain a failure. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Namespace to read events from (default: \"default\").",
            },
            "involving": {
                "type": "string",
                "description": "Optional object name to filter events to "
                "(e.g. a pod name).",
            },
        },
        "additionalProperties": False,
    },
    executor=_k8s_events,
)

K8S_NODES = Tool(
    name="k8s_nodes",
    description=(
        "Fetch all cluster nodes as JSON: status conditions (Ready/MemoryPressure/"
        "DiskPressure), roles, kubelet version, taints. Use for node-level "
        "problems — a node NotReady, scheduling issues, capacity. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    executor=_k8s_nodes,
)

K8S_SERVICES = Tool(
    name="k8s_services",
    description=(
        "Fetch Services in a namespace as JSON: type (ClusterIP/LoadBalancer/"
        "NodePort), cluster IP, ports, selectors. Use for 'why can't I reach "
        "this service' / exposure problems. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Namespace of the Services (default: \"default\").",
            },
        },
        "additionalProperties": False,
    },
    executor=_k8s_services,
)

register(K8S_POD_STATUS)
register(K8S_POD_LOGS)
register(K8S_DEPLOYMENT_STATUS)
register(K8S_EVENTS)
register(K8S_NODES)
register(K8S_SERVICES)