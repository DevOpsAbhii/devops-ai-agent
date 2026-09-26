"""Read-only Istio tools (Phase 9).

One tool: `istioctl proxy-status` — the service mesh's control-plane view of
every connected Envoy proxy: which proxies exist, their cluster, their sync
version with istiod, and which are STALE (not receiving config — the mesh
version of a node NotReady).

Safety model:
- A single fixed argv template, no arguments at all — the model cannot
  inject anything. istioctl's mutating verbs (proxy-config with write
  paths, install, upgrade, webhook apply, x) are unreachable.
- istioctl must be installed and pointed at a mesh; missing/unreachable
  surfaces as the exact CLI error.
"""

from tools.base import Tool, read_command_output
from tools.registry import register

_TIMEOUT_S = 15


def _istioctl_proxy_status(args: dict) -> str:
    return read_command_output(
        ("istioctl", "proxy-status"),
        timeout=_TIMEOUT_S,
    )


ISTIOCTL_PROXY_STATUS = Tool(
    name="istioctl_proxy_status",
    description=(
        "Istio mesh proxy status (istioctl proxy-status): every Envoy "
        "proxy (CLUSTER/CDS/LDS/RDS/ECDS out-of-sync columns) and which "
        "ones are STALE — out of sync with istiod. Use for mesh problems: "
        "'traffic isn't following the new config', 'a sidecar stopped "
        "receiving updates'. Requires istioctl + a reachable mesh. "
        "Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_istioctl_proxy_status,
)

register(ISTIOCTL_PROXY_STATUS)
