# Integrating the DevOps AI Agent into your project

Three levels, from easiest to deepest. Pick the one that matches how much
you want to own:

1. **CLI integration** — the agent is a process with exit codes and JSON
   output; drive it from cron, CI, scripts or a chat bot. *(This is the
   designed integration surface — start here.)*
2. **Python library** — import `DevOpsAgent` and call it in-process, or
   reuse just the tool layer without any model.
3. **Extend it** — add your own read-only domain tools to the registry.

The agent is read-only by construction: no mutating verb exists anywhere
(fixed argv templates, validated names, no shell), so it is safe to point
at production with a real kubeconfig — the worst it can do is read.

---

## 1. CLI integration

### One-time setup

**Fastest — install from PyPI (no clone):**

```bash
pipx install devopsiq        # or: pip install devopsiq
export OPENROUTER_API_KEY=sk-or-...    # or put it in a .env next to your cwd
devopsiq --json "why is api-5d6f crash-looping?"
```

**No-Python — prebuilt Docker image** (bundles kubectl, helm, gh, trivy,
git, curl, docker CLI):

```bash
docker run --rm \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v "$HOME/.kube:/home/agent/.kube:ro" \
  -v agent-records:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/devopsabhii/devops-ai-agent --json "check the cluster"
```

**From source (development / contributing):**

```bash
git clone https://github.com/DevOpsAbhii/devops-ai-agent.git
cd devops-ai-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then edit: OPENROUTER_API_KEY=sk-or-...
```

Install only the CLIs for the domains you will investigate with (each tool
reports its exact error if its CLI is missing, so a partial install is
fine): `kubectl`, `docker`, `gh` (+ `gh auth login`), `terraform`, `helm`,
`argocd` (+ `argocd login`), `istioctl`, `trivy`, `aws`/`gcloud`/`az`,
`ansible-inventory`/`ansible-playbook`, `curl`.

**Run the agent on a machine that has the access you want it to
investigate with** — a bastion, a CI runner with a kubeconfig, an ops
workstation. The tools execute locally.

### The contract

```bash
# plain answer (markdown to stdout)
.venv/bin/python main.py "why is api-5d6f crash-looping?"

# machine-readable: stdout is ONE valid JSON document
.venv/bin/python main.py --json "checkout pod is crash-looping, investigate"

# pipeline-grade: JSON also written to an exact path, persistence redirected
.venv/bin/python main.py --json --out report.json --store-dir /var/lib/agent "..."

# continue a prior run (picks up the newest in-progress record)
.venv/bin/python main.py --resume --json --out update.json "any progress?"

# per-run model override (any OpenRouter model)
.venv/bin/python main.py --model openai/gpt-5.2 --json "..."
```

| Property | Behavior |
| --- | --- |
| Exit code | `0` = completed, `1` = setup/API error (including "no investigation was opened") |
| `--json` stdout | One JSON document: `problem`, `status` (`in_progress`/`concluded`), `hypotheses[]`, `evidence[]`, and once concluded `conclusion` with `root_cause`, `remediation[]`, `verification[]`, `confidence` |
| `--out PATH` | Writes that same JSON to an exact file (for pipelines that want a known location); stdout stays the human-readable report |
| `--store-dir DIR` | Where investigation records auto-save for this run (env: `AGENT_STORE_DIR`; default `~/.devops-ai-agent/investigations/`) |
| `--resume` | Load the newest in-progress record from the store before asking |
| `--model NAME` | Override the model for this run (highest model precedence; then `~/.devops-ai-agent/config.json`, then `OPENROUTER_MODEL`, then the built-in default) |
| Slash commands | Work one-shot too: `python main.py /report`, `/investigations`, `/model`, … |
| Retries | Transient model-call failures (timeouts, connection errors, 429s honoring `Retry-After`, 5xx) retry up to 3× with exponential backoff 2s→4s→8s + jitter before surfacing; client 4xx (a rejected key, most notably) fail immediately. Budget for ~15s of retry delay in your subprocess `timeout=` |

The JSON shape is `render_report_json()` in `agent/investigation.py` —
deterministic, no model text is trusted, so your pipeline can act on
`conclusion.root_cause` and `conclusion.confidence` instead of parsing
prose.

### Cron

```cron
# every 15 minutes, investigate anomalies and keep the last report
*/15 * * * * cd /opt/devops-ai-agent && .venv/bin/python main.py --json \
  --out /var/reports/agent.json "check for anomalies" >> /var/log/agent.log 2>&1
```

### GitHub Actions (worked example)

```yaml
# .github/workflows/triage.yml
name: Incident triage
on:
  workflow_dispatch:
    inputs:
      problem:
        description: "What went wrong?"
        required: true
  schedule:
    - cron: "17 6 * * 1-5"   # weekdays, off the :00 mark

jobs:
  triage:
    # prebuilt image — no checkout, no pip; the image bundles kubectl, helm,
    # gh, trivy, git, curl and the docker CLI
    runs-on: [self-hosted, ops]   # needs cluster access — see notes
    container:
      image: ghcr.io/devopsabhii/devops-ai-agent:latest
      volumes:
        - ${{ github.workspace }}:/w
      options: --user root   # needed only to write the report into $GITHUB_WORKSPACE
    env:
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
      # optional tool enablement, per runner:
      # PROMETHEUS_URL / LOKI_URL / GRAFANA_URL / NEW_RELIC_API_KEY / NEW_RELIC_ACCOUNT_ID
    steps:
      - name: Investigate
        run: |
          devopsiq --json --out /w/report.json \
            "${{ inputs.problem || 'check the cluster for anomalies' }}"
      - uses: actions/upload-artifact@v4
        with: { name: report, path: report.json }
      # example: branch on the verdict — fail the job when the agent could
      # not conclude confidently, so the escalation path is human review
      - name: Fail on low-confidence conclusions
        run: |
          python - <<'EOF'
          import json, sys
          r = json.load(open("/w/report.json"))
          c = r.get("conclusion")
          if not c or c["confidence"] == "low":
              sys.exit("low-confidence conclusion — escalate to a human")
          print("ROOT CAUSE:", c["root_cause"])
          EOF
```

Notes:
- **Cluster access**: the `ubuntu-latest` GitHub runner has no access to
  *your* cluster. Run on a self-hosted runner that has a kubeconfig (mounted
  or baked at `$HOME/.kube/config` for the container's `agent` user), or
  scope one to a read-only ServiceAccount — the agent only reads, but your
  kubeconfig should still be least-privilege. For docker/compose tools,
  mount `/var/run/docker.sock`.
- **Secrets**: only `OPENROUTER_API_KEY` is needed for the model.
  Monitoring/New Relic tools are enabled per-runner via the env vars above.
- **Version pinning**: pin `:latest` to a release tag like
  `ghcr.io/devopsabhii/devops-ai-agent:0.1.0` in production workflows.
- The schedule cron here is off the `:00` mark on purpose (the agent
  itself recommends the same for its own scheduled jobs).

### Jenkins / GitLab CI / anything else

Same shape: a step that runs `main.py --json --out report.json "<problem>"`,
archives `report.json`, and exits non-zero when the command does. Because
the contract is process + exit code + JSON, nothing about your CI matters.

### Slack / Teams / Telegram bot

Keep a long-running process that shells out per message, or go to level 2:

```python
import subprocess, json

def investigate(problem: str) -> dict:
    p = subprocess.run(
        [".venv/bin/python", "main.py", "--json", problem],
        capture_output=True, text=True, timeout=300,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)
    return json.loads(p.stdout)   # feed conclusion.root_cause to your channel
```

### Docker

The repo ships a prebuilt image at
`ghcr.io/devopsabhii/devops-ai-agent` (multi-arch amd64+arm64, published on
every `v*` release). It bundles kubectl, helm, gh, trivy, git, curl and the
docker CLI, runs as a non-root `agent` user, and keeps investigation records
in `/data` (`AGENT_STORE_DIR`) so they survive restarts — mount a volume
there, plus your kubeconfig:

```bash
docker run --rm \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v "$HOME/.kube:/home/agent/.kube:ro" \
  -v agent-records:/data \
  ghcr.io/devopsabhii/devops-ai-agent --json "why is api-5d6f crash-looping?"
```

Building your own layer on top (to add CLIs the image doesn't bundle —
terraform, argocd, istioctl, aws/gcloud/az, ansible):

```dockerfile
FROM ghcr.io/devopsabhii/devops-ai-agent:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ansible \
    && rm -rf /var/lib/apt/lists/*
USER agent
```

The Dockerfile itself is in the repo if you want to build from source.

---

## 2. Python library

The agent is importable — no subprocess, no CLI:

```python
from agent.agent import DevOpsAgent

agent = DevOpsAgent()          # reads OPENROUTER_API_KEY etc. from the env
answer = agent.ask("docker container checkout keeps exiting, investigate")
print(answer)                  # the agent's report (markdown)

# the structured record, programmatically:
report = agent.investigation_report_json()
if report and report["status"] == "concluded":
    print(report["conclusion"]["root_cause"])
    for step in report["conclusion"]["remediation"]:
        print("-", step)
```

One instance per conversation; `ask()` keeps history. Build your own bot
around it (Slack/Teams/Telegram) by keeping the instance per channel/thread.

### Just the tool layer (no model, no API key)

All 58 read-only tools work standalone — useful for dashboards, health
checks, or as a toolkit inside your own automation:

```python
import agent.agent                            # side effect: registers every tool
from tools.registry import execute_tool, get_tools

print(execute_tool("k8s_pods", '{"namespace": "prod"}'))
print(execute_tool("helm_list", '{"all_namespaces": true}'))

names = [t.name for t in get_tools()]        # what exists
print(len(names), "tools")
```

`execute_tool` never raises — failures come back as `"Tool error: ..."`
strings — and tool output is truncated at 8,000 characters.

---

## 3. Extend it with your own tools

Add a domain tool in ~20 lines. The rule that keeps the agent safe is
**read-only by construction**: a fixed argv template (never `sh -c`),
validated arguments, read-only verbs only.

```python
# my_tools.py
from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

def _my_check(args: dict) -> str:
    service = args.get("service")
    if not isinstance(service, str) or not service.replace("-", "").isalnum():
        raise ToolError("service must be a plain name")
    return read_command_output(("my-cli", "status", service), timeout=10)

MY_CHECK = Tool(
    name="my_check",
    description="Check my custom service status: name, state, last error. Read-only.",
    parameters={
        "type": "object",
        "properties": {"service": {"type": "string",
                                   "description": "Service name."}},
        "required": ["service"],
        "additionalProperties": False,
    },
    executor=_my_check,
)
register(MY_CHECK)
```

Then import it next to the others in `agent/agent.py` — registration
happens at import, and the model picks the tool up automatically via its
schema:

```python
from tools import (  # noqa: F401
    ...
    my_tools,   # <- yours
)
```

The full pattern (name validators, bounded counts, pinned flags, honest
errors) is `tools/helm.py` or `tools/istio.py` — short files worth copying
from. For an HTTP-backed tool, copy `tools/monitoring.py`: endpoint from
environment config only, pinned curl argv, percent-encoded queries.

---

## Credentials & configuration reference

| Variable | Enables | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | the model itself | required; `.env` or shell (shell wins) |
| `OPENROUTER_MODEL` | model choice | default `z-ai/glm-5.3`; any OpenRouter model, one line |
| `AGENT_CONFIG_FILE` | model-preference file | override for `~/.devops-ai-agent/config.json` (the `/model` command's save target); tests use tmp paths |
| `AGENT_STORE_DIR` | record persistence | default `~/.devops-ai-agent/investigations/` |
| `PROMETHEUS_URL` | `prom_query` | http(s) endpoint |
| `LOKI_URL` | `loki_query` | http(s) endpoint |
| `GRAFANA_URL` | `grafana_health` | http(s) endpoint |
| `NEW_RELIC_API_KEY` | `newrelic_nrql`, `newrelic_alerts` | NerdGraph user key |
| `NEW_RELIC_ACCOUNT_ID` | ditto | digits only |

Everything else (kubectl, docker, gh, argocd, …) uses the CLIs' own config
on the host.

## What integrators should NOT do

- Don't point the agent at a kubeconfig with write rights "just in case" —
  it only reads, so give it least-privilege reads.
- Don't parse the markdown answer in automation — use `--json`.
- Don't pipe untrusted output into the problem string expecting the agent
  to act on it — it is an investigator, not an executor; it cannot mutate
  anything by design, and that is the guarantee.
