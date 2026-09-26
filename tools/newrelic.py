"""Read-only New Relic tools (Phase 9).

Query New Relic's NerdGraph GraphQL API over curl: NRQL queries
(newrelic_nrql) and the account's open alert incidents (newrelic_alerts).
This extends the tools/monitoring.py pattern from GET to POST — the argv is
still fixed, but here curl carries a `-d` payload built by json.dumps, so
quoting is safe and the NRQL text can never break out of its JSON string.

Credentials come from ENVIRONMENT CONFIGURATION only, never the model:
- NEW_RELIC_API_KEY   — a NerdGraph (user) API key; unset → honest ToolError
  naming the variable. It is passed to curl as a header value only.
- NEW_RELIC_ACCOUNT_ID — the numeric account id; must be digits (it is
  interpolated into the GraphQL variables as an integer, so a non-digit
  value is refused rather than smuggled in).

The model supplies ONLY the NRQL text (bounded length). newrelic_alerts
takes no model input at all — its payload is byte-identical every call.
Nothing here can create, acknowledge or close an incident; NerdGraph
mutations are never sent (the GraphQL documents below are queries only).
"""

import json
import os

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

_TIMEOUT_S = 20
_MAX_QUERY_CHARS = 500
_NERDGRAPH_URL = "https://api.newrelic.com/graphql"

# Queries use GraphQL variables ($account, $nrql) — the payload is built by
# json.dumps, so no NRQL text can escape its string slot.
_NRQL_QUERY = (
    "query ($accountId: Int!, $nrql: Nrql!) {"
    "  actor {"
    "    account(id: $accountId) {"
    "      nrql(query: $nrql) {"
    "        results"
    "        metadata { facets queries}"
    "      }"
    "    }"
    "  }"
    "}"
)

_ALERTS_QUERY = (
    "query ($accountId: Int!) {"
    "  actor {"
    "    account(id: $accountId) {"
    "      alerts {"
    "        incidents(filter: {states: [ACTIVE, ACKNOWLEDGED]}) {"
    "          incidentId title priority state startedAt"
    "          labels { key value }"
    "        }"
    "      }"
    "    }"
    "  }"
    "}"
)


def _checked_query(args: dict, label: str) -> str:
    query = args.get(label)
    if not isinstance(query, str) or not query.strip():
        raise ToolError(f"{label} must be a non-empty NRQL query string")
    if len(query) > _MAX_QUERY_CHARS:
        raise ToolError(f"{label} must be at most {_MAX_QUERY_CHARS} characters")
    return query


def _credentials() -> tuple[str, int]:
    api_key = os.environ.get("NEW_RELIC_API_KEY", "").strip()
    if not api_key:
        raise ToolError(
            "no New Relic credentials configured: set the NEW_RELIC_API_KEY "
            "environment variable (a NerdGraph user key) and retry"
        )
    account_id = os.environ.get("NEW_RELIC_ACCOUNT_ID", "").strip()
    if not account_id:
        raise ToolError(
            "no New Relic account configured: set the "
            "NEW_RELIC_ACCOUNT_ID environment variable (digits only) and retry"
        )
    if not account_id.isdigit():
        raise ToolError(
            "NEW_RELIC_ACCOUNT_ID must be the numeric account id "
            f"(got {account_id!r})"
        )
    return api_key, int(account_id)


def _nerdgraph(api_key: str, payload: str) -> str:
    return read_command_output(
        (
            "curl", "-sS", "--max-time", "15",
            "-H", f"API-Key: {api_key}",
            "-H", "content-type: application/json",
            "-d", payload,
            _NERDGRAPH_URL,
        ),
        timeout=_TIMEOUT_S,
    )


def _newrelic_nrql(args: dict) -> str:
    nrql = _checked_query(args, "query")
    api_key, account_id = _credentials()
    payload = json.dumps({
        "query": _NRQL_QUERY,
        "variables": {"accountId": account_id, "nrql": nrql},
    })
    return _nerdgraph(api_key, payload)


def _newrelic_alerts(args: dict) -> str:
    # No model input reaches the payload — args are accepted and ignored.
    api_key, account_id = _credentials()
    payload = json.dumps({
        "query": _ALERTS_QUERY,
        "variables": {"accountId": account_id},
    })
    return _nerdgraph(api_key, payload)


NEWRELIC_NRQL = Tool(
    name="newrelic_nrql",
    description=(
        "Run one NRQL query against the configured New Relic account "
        "(NEW_RELIC_API_KEY + NEW_RELIC_ACCOUNT_ID env) via the NerdGraph "
        "API and return the JSON results. Use for APM/infra evidence: "
        "error rates, response times, throughput, host resource metrics, "
        "e.g. 'SELECT average(duration) FROM Transaction WHERE "
        "appName = 'api' TIMESERIES SINCE 30 minutes ago'. Query text "
        "only; credentials and account are fixed by the operator's "
        "environment. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "NRQL query text, e.g. 'SELECT count(*) "
                "FROM Transaction SINCE 1 hour ago'.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    executor=_newrelic_nrql,
)

NEWRELIC_ALERTS = Tool(
    name="newrelic_alerts",
    description=(
        "List the New Relic account's OPEN alert incidents (ACTIVE or "
        "ACKNOWLEDGED) as JSON via NerdGraph: incident id, title, priority, "
        "state, start time, entity labels. Use as the first step when an "
        "alert fires — 'what is alerting right now'. No parameters; "
        "credentials come from the environment. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_newrelic_alerts,
)

register(NEWRELIC_NRQL)
register(NEWRELIC_ALERTS)
