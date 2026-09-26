"""Read-only monitoring/logging tools (Phase 8).

Query Prometheus (instant PromQL), Loki (instant LogQL) and Grafana health —
via the system curl, with the endpoint URL coming from ENVIRONMENT
CONFIGURATION only. This module is the one deliberate safety extension of
Phase 8, so its invariants are stricter than elsewhere:

- The endpoint can never come from the model. It is read from PROMETHEUS_URL,
  LOKI_URL or GRAFANA_URL (set by the human running the agent); an unset
  endpoint is an honest ToolError naming the variable. The model supplies
  only the query text.
- The curl argv is fixed: `curl -fsS --max-time 10 --proto =https,http -H
  Accept:application/json <url>`. GET only; `--proto` makes file:// and
  other exotic protocols unreachable even in theory; there is no shell, so
  the URL is one literal argv element.
- Query strings are percent-encoded with urllib.parse.quote(safe="") before
  being appended, so `&`, spaces or shell metacharacters in a query become
  part of the query, never of the URL structure or of a command.
- Endpoint URLs themselves are validated to start with http:// or https://
  (a misconfigured PROMETHEUS_URL=file:///etc/passwd is refused, not run).

If no endpoint is configured, the tools fail with a clear message — nothing
is invented and no default host is ever contacted.
"""

import os
from urllib.parse import quote

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

_TIMEOUT_S = 10
_MAX_QUERY_CHARS = 500


def _checked_query(args: dict, label: str) -> str:
    query = args.get(label)
    if not isinstance(query, str) or not query.strip():
        raise ToolError(f"{label} must be a non-empty query string")
    if len(query) > _MAX_QUERY_CHARS:
        raise ToolError(f"{label} must be at most {_MAX_QUERY_CHARS} characters")
    return query


def _endpoint(env_var: str) -> str:
    base = os.environ.get(env_var, "").strip().rstrip("/")
    if not base:
        raise ToolError(
            f"no monitoring endpoint configured: set the {env_var} "
            "environment variable (e.g. http://prometheus:9090) and retry"
        )
    if not (base.startswith("http://") or base.startswith("https://")):
        raise ToolError(
            f"{env_var} must start with http:// or https:// (got {base!r})"
        )
    return base


def _curl(url: str) -> str:
    return read_command_output(
        (
            "curl", "-fsS", "--max-time", "10", "--proto", "=https,http",
            "-H", "Accept:application/json", url,
        ),
        timeout=_TIMEOUT_S,
    )


def _prom_query(args: dict) -> str:
    query = _checked_query(args, "query")
    url = f"{_endpoint('PROMETHEUS_URL')}/api/v1/query?query={quote(query, safe='')}"
    return _curl(url)


def _loki_query(args: dict) -> str:
    query = _checked_query(args, "query")
    try:
        limit = int(args.get("limit", 100))
    except (TypeError, ValueError):
        raise ToolError("limit must be an integer between 1 and 1000")
    if not 1 <= limit <= 1000:
        raise ToolError("limit must be between 1 and 1000")
    url = (
        f"{_endpoint('LOKI_URL')}/loki/api/v1/query"
        f"?query={quote(query, safe='')}&limit={limit}"
    )
    return _curl(url)


def _grafana_health(args: dict) -> str:
    return _curl(f"{_endpoint('GRAFANA_URL')}/api/health")


PROM_QUERY = Tool(
    name="prom_query",
    description=(
        "Run one instant PromQL query against the configured Prometheus "
        "(PROMETHEUS_URL env) and return its JSON result: labels, values, "
        "timestamps. Use for metrics evidence — error rate, latency, "
        "saturation, replica counts. Query text only; the endpoint is fixed "
        "by the operator's environment. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Instant PromQL query, e.g. "
                "'sum(rate(http_requests_total{status=~\"5..\"}[5m]))'.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    executor=_prom_query,
)

LOKI_QUERY = Tool(
    name="loki_query",
    description=(
        "Run one instant LogQL query against the configured Loki (LOKI_URL "
        "env) and return its JSON result: log streams and lines. Use for log "
        "evidence across many pods at once, e.g. "
        "'{app=\"api\"} |= \"error\"'. Query text plus a bounded result "
        "limit (1–1000); the endpoint is fixed by the environment. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Instant LogQL query (log or metric query).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 100,
                "description": "Max log entries to return (1–1000).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    executor=_loki_query,
)

GRAFANA_HEALTH = Tool(
    name="grafana_health",
    description=(
        "Check the configured Grafana's health endpoint (GRAFANA_URL env, "
        "/api/health): version and database status. Use to confirm whether "
        "the observability stack itself is up — dashboards empty because "
        "Grafana is down is its own incident. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_grafana_health,
)

register(PROM_QUERY)
register(LOKI_QUERY)
register(GRAFANA_HEALTH)
