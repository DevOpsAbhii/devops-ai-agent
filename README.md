# DevOps AI Agent

[![PyPI](https://img.shields.io/pypi/v/devopsiq)](https://pypi.org/project/devopsiq/)
[![Python](https://img.shields.io/pypi/pyversions/devopsiq)](https://pypi.org/project/devopsiq/)
[![Release](https://github.com/DevOpsAbhii/devops-ai-agent/actions/workflows/release.yml/badge.svg)](https://github.com/DevOpsAbhii/devops-ai-agent/actions/workflows/release.yml)
[![Docker](https://img.shields.io/badge/ghcr-devops--ai--agent-2496ED?logo=docker&logoColor=white)](https://github.com/DevOpsAbhii/devops-ai-agent/pkgs/container/devops-ai-agent)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-169%20offline-brightgreen)](https://github.com/DevOpsAbhii/devops-ai-agent/actions/workflows/release.yml)

An AI agent that investigates real DevOps problems. The end goal: ask it
something like *"Why is my Kubernetes pod in CrashLoopBackOff?"* and have it
gather evidence, reason about the evidence, identify the likely root cause,
recommend remediation, and give verification steps.

**Phase 5** broadens the agent from
Kubernetes-only to the wider DevOps surface: Linux systemd services and
journals, Docker containers, Terraform state/plan, and git/GitHub pull
requests — every tool still read-only, still a fixed allowlisted argv
template. **Phase 6 adds the automation surface:** a one-shot CLI mode
(`python main.py "problem"` — exit-code driven, cron/CI-friendly) and a
structured JSON export of the investigation report, so pipelines can act on
the verdict instead of parsing markdown. **Phase 7 adds persistence:** the
investigation record is auto-saved on every change to
`~/.devops-ai-agent/investigations/` (overridable with `--store-dir` or
`AGENT_STORE_DIR`), survives CLI exits, and the REPL resumes the newest
in-progress record at startup. **Phase 8 broadens the tool surface to 47
read-only tools:** Kubernetes depth (pod listing, `kubectl top` resource
usage, HPAs, PVCs, contexts), Docker depth (networks, volumes, disk usage),
GitHub Actions via `gh` (runs, run jobs, workflows), cloud identity
(AWS/GCP/Azure), monitoring/logging (Prometheus, Loki, Grafana — endpoints
from environment config), and Ansible listing (inventory, playbook tasks).
**Phase 9 adds 11 trending-market tools (58 total):** New Relic (NRQL +
open alerts over NerdGraph — credentials from env), Trivy image
vulnerability scanning, Helm releases (list/status/history), Argo CD
(GitOps app sync/health), Istio mesh proxy status, and Docker Compose
(project and service listing). **Phase 10 ships it as a product:** the
[`devopsiq` package on PyPI](https://pypi.org/project/devopsiq/) and a
prebuilt multi-arch Docker image (`ghcr.io/devopsabhii/devops-ai-agent`) —
both cut automatically by pushing a `v*` tag (test gate → PyPI via Trusted
Publishing + GHCR in parallel). **No API key? The agent still runs:** it
starts in model-less mode — record commands (`/report`, `/investigations`)
and the whole 58-tool layer work without a key; only questions to the model
need one. The repository is git-tracked.
Every phase still built from scratch — no LangChain, LangGraph,
AutoGen, CrewAI, or MCP.

> **Want to use this in your own project?** See [INTEGRATION.md](INTEGRATION.md)
> for the three integration levels: drive it as a CLI from cron/CI (exit
> codes + `--json`), embed it as a Python library, or extend it with your
> own read-only tools.

---

## 1. What this project is

The agent is built intentionally: we own the core architecture — how the
model is called, how conversation history flows, how tool selection +
execution + evidence feedback work — instead of depending on a framework
for it.

Today the agent:
- holds a conversation with **GLM 5.3** through **OpenRouter**;
- has **58 real, read-only tools** across fifteen domains: host facts,
  Kubernetes (12 tools), Linux system (4), Docker + Compose (10),
  Terraform (3), Helm (3), Argo CD (2), Istio (1), security/Trivy (1),
  git/GitHub + Actions (7), cloud identity (4), monitoring/logging (3),
  New Relic (2), Ansible (2), plus the 3 investigation tools;
- runs a **tool-use loop**: when the model decides a question needs evidence,
  it requests the tool, the application executes it locally, and the real
  output is fed back to the model, which then answers from it;
- runs an **investigation loop**: for a reported problem it plans a multi-step
  investigation — open a record with initial hypotheses, gather evidence with
  the right domain tools, update each hypothesis's verdict as evidence
  builds, conclude with root cause + remediation + verification, and end with
  a structured report. The tracked state lives in the application, so
  `/investigation` and `/report` show it directly.

It is **read-only by design**: every tool is a static, allowlisted command
template — the model can never pass arbitrary command text, can never select
a mutating verb (no delete/restart/edit/apply/scale/exec/run/rm/reset/
destroy anywhere), and no mutating capability exists. Object and unit names
are validated before reaching any CLI; flags are injected only by fixed
templates, never by model text. The investigation tools mutate only the
agent's in-memory record. Any future mutating capability will only ever
arrive behind an explicit human-approval gate.

## 2. Current architecture

```
You (terminal)
   │  plain text
   ▼
main.py ......................... CLI REPL, .env loading, error handling
   │
   ▼
agent/agent.py (DevOpsAgent) .... system prompt + conversation history
   │
   ▼  the tool-use loop, inside DevOpsAgent._complete():
   │
   │   attach tool schemas -> call model
   │        │
   │        ├─ model requests tool(s)? ── yes ─▶ tools/registry.execute_tool()
   │        │                                 │   per call, in order
   │        │                                 │      └─ allowlisted read-only
   │        │                                 │         command runs for real
   │        │                                 │      └─ result echoed back as
   │        │                                 │         a "tool" message
   │        │                                 ◀── loop calls the model again
   │        └─ model answers in plain text? ── yes ─▶ done
   │              (safety cap: max 10 tool-use turns, then abort)
   ▼
OpenRouter (https://openrouter.ai/api/v1)
   ▼
GLM 5.3 (z-ai/glm-5.3)
```

Module map:

| Path                        | Responsibility                                              |
| --------------------------- | ------------------------------------------------------------ |
| `main.py`                   | REPL loop, one-shot CLI, environment loading, `/investigate` commands, error messages, model-less start |
| `agent/agent.py`            | `DevOpsAgent` — client (`None` = model-less mode), history, `ask()`, `_complete()` loop |
| `agent/prompts.py`          | The system prompt (versioned/tested separately)              |
| `agent/investigation.py`    | First-class investigation record: hypotheses, verdicts, evidence, report renderer (pure data) |
| `agent/store.py`            | `InvestigationStore` — one JSON file per record, atomic writes, resume/list (Phase 7) |
| `tools/base.py`             | Tool contract: `Tool`, `ToolError`, `read_command_output()`  |
| `tools/registry.py`         | `register/get_tools/execute_tool` — tools declared & executed here |
| `tools/preflight.py`        | `system_info` — host facts (allowlisted read-only commands)  |
| `tools/kubernetes.py`       | 12 kubectl tools: pods, pod status/logs, deployments, events, nodes, top (cpu/mem), hpa, pvc, services, contexts |
| `tools/system.py`           | systemd/journal/ss/ps tools — services, journals, ports, top processes |
| `tools/docker.py`           | read-only docker tools — ps, inspect, logs, stats, images, networks, volumes, disk usage, compose ls/ps |
| `tools/terraform.py`        | `tf_show` / `tf_state_list` / `tf_plan` (working directory)  |
| `tools/helm.py`             | `helm_list` / `helm_status` / `helm_history` — release reads only (Phase 9) |
| `tools/argocd.py`           | `argocd_apps` / `argocd_app_status` — GitOps app reads (Phase 9) |
| `tools/istio.py`            | `istioctl_proxy_status` — mesh sync view, no arguments (Phase 9) |
| `tools/trivy.py`            | `trivy_image_scan` — vulnerability report for one image (Phase 9) |
| `tools/newrelic.py`         | `newrelic_nrql` / `newrelic_alerts` — NerdGraph over curl, credentials from env only (Phase 9) |
| `tools/git_ci.py`           | git status/log/diff + `gh_prs`, `gh_runs`, `gh_run_view`, `gh_workflows` (working directory) |
| `tools/cloud.py`            | read-only cloud identity/listing: `aws_identity`, `gcloud_identity`, `az_account`, `az_groups` |
| `tools/monitoring.py`       | `prom_query`, `loki_query`, `grafana_health` — endpoints from env config only |
| `tools/ansible.py`          | `ansible_inventory`, `ansible_playbook_tasks` — listing modes only |
| `tools/investigation.py`    | `investigation_begin` / `investigation_record` / `investigation_conclude` — meta-tools for the investigation record |
| `tests/test_phase2.py`      | Offline suite: contract, safety, loop (stdlib `unittest`)     |
| `tests/test_phase3.py`      | Offline suite: k8s command lines + verb-allowlist (fake kubectl) |
| `tests/test_phase4.py`      | Offline suite: investigation state, meta-tools, loop-driven investigation |
| `tests/test_phase5.py`      | Offline suite: argv templates + name validation for all new domains (fake CLIs) |
| `tests/test_automation.py`  | Offline suite: JSON reports + one-shot CLI (Phase 6)                        |
| `tests/test_phase7.py`      | Offline suite: round-trip serialization, store files, auto-save, resume, CLI flags (Phase 7) |
| `tests/test_phase8.py`      | Offline suite: argv templates + validation for the 21 Phase 8 tools (fake CLIs, env-based monitoring) |
| `tests/test_phase9.py`      | Offline suite: New Relic env-credential + payload tests, trivy/helm/argocd/istio/compose argv templates (Phase 9) |
| `pyproject.toml`            | Package `devopsiq`: metadata, MIT, console script `devopsiq = main:main` (Phase 10) |
| `Dockerfile`                | Prebuilt image: slim base + kubectl/helm/trivy/gh + app, non-root, `/data` record store (Phase 10) |
| `.github/workflows/release.yml` | Tag-driven release: test gate → PyPI (Trusted Publishing) + GHCR multi-arch (Phase 10) |
| `docs/generate_pdf.py`      | Builds the project documentation PDF from live source |
| `docs/generate_release_guide.py` | Builds the release & update playbook PDF |

### The tool-use loop

All model calls funnel through `DevOpsAgent._complete()`. Each turn:

1. The full history is sent with every tool's schema attached (`tools=`).
2. If the reply contains tool calls, the assistant tool-request turn is
   echoed into history verbatim, and each call is executed locally via
   `tools/registry.execute_tool(name, arguments)`.
3. Every real result is appended as a sibling `{"role": "tool"}` message
   pinned to its `tool_call_id`.
4. The loop calls the model again — giving it the evidence to reflect on —
   and repeats until it answers in plain text.
5. `MAX_TOOL_ITERATIONS = 10` aborts runaway loops.

### The investigation loop (Phase 4)

For a reported problem (a pod in CrashLoopBackOff, a broken rollout) the
same loop carries a *plan* as well as evidence:

1. The model opens a record with `investigation_begin` (one-line problem +
   2–4 initial hypotheses, which become H1, H2, …).
2. It plans what it needs, then calls the read-only tools one deliberate
   step at a time.
3. Every finding is recorded with `investigation_record`: evidence notes
   (linked to a hypothesis when they bear on one) and verdicts
   (supported / refuted / confirmed).
4. Each record call returns the **live tracker** (`Problem`, status,
   hypotheses with verdicts, evidence), so the model always knows where it
   stands without inspecting all of history.
5. When evidence is sufficient the model calls `investigation_conclude`
   with root cause, remediation *recommendations* (nothing is ever
   executed), verification steps, and confidence — then ends its answer
   with the structured report.

The record lives in the **application**, not just the conversation: the
report is rendered deterministically from it (agent/investigation.py), and
the CLI exposes it directly:

| Command                  | What it does                                        |
| ------------------------ | --------------------------------------------------- |
| `/investigate <problem>` | Open a formal investigation (same path the model uses) |
| `/investigation`         | Show the live tracked state (hypotheses/evidence)   |
| `/investigations`        | List saved records on disk (newest first; `← active` marks the live one) |
| `/report`                | Show the canonical report (once concluded)          |
| `/endinvestigation`      | Clear the record (memory only — the saved copy stays as history) |

The report the agent ends with and `/report` render are kept consistent by
construction: `tool` results confirm each record call and the tracker, and
`render_report()` is the single report format.

Example (live, against a real cluster):

```
You: /investigate Pod crashloop-6f8c… is in CrashLoopBackOff in default ns.
     (…) investigate.
Agent: (investigation_begin → k8s_pod_status → k8s_pod_logs →
       k8s_deployment_status → verdicts on H1/H2 → investigation_conclude)
       ends with: Facts → Hypotheses → Root cause → Remediation (recommended)
       → Verification steps.

You: /report
Agent: # Investigation report  … (canonical, rendered from the record)
```

### The tools (Phases 5, 8 and 9)

Every tool runs a fixed, allowlisted command — the model only picks
arguments (names, counts, namespaces), never command text.

| Domain           | Tool                  | Backing command (read-only)                          |
| ---------------- | --------------------- | ---------------------------------------------------- |
| Host             | `system_info`         | `date`/`uname`/`uptime`/`df`/`free`                  |
| Kubernetes       | `k8s_pod_status`      | `kubectl get pod <pod> -n <ns> -o json`              |
|                  | `k8s_pod_logs`        | `kubectl logs <pod> -n <ns> --tail=<n>`              |
|                  | `k8s_deployment_status` | `kubectl get deployment <dep> -n <ns> -o json`     |
|                  | `k8s_events`          | `kubectl get events -n <ns> --sort-by=.lastTimestamp -o wide [--field-selector involvedObject.name=<obj>]` |
|                  | `k8s_nodes`           | `kubectl get nodes -o json`                          |
|                  | `k8s_services`        | `kubectl get services -n <ns> -o json`               |
|                  | `k8s_pods`            | `kubectl get pods -n <ns> -o wide`                   |
|                  | `k8s_top_pods`        | `kubectl top pods -n <ns> [--sort-by=cpu\|memory]`   |
|                  | `k8s_top_nodes`       | `kubectl top nodes`                                  |
|                  | `k8s_hpa`             | `kubectl get hpa [<name>] -n <ns> -o json`           |
|                  | `k8s_pvc`             | `kubectl get pvc [<name>] -n <ns> -o json`           |
|                  | `k8s_contexts`        | `kubectl config get-contexts` (listing only — never `use-context`) |
| Linux system     | `sys_service_status`  | `systemctl status <unit> --no-pager`                 |
|                  | `sys_service_logs`    | `journalctl -u <unit> --no-pager -n <n>`             |
|                  | `sys_open_ports`      | `ss -tlnp`                                           |
|                  | `sys_top_processes`   | `ps aux --sort=-%cpu --no-headers`                   |
| Docker           | `docker_ps`           | `docker ps -a`                                       |
|                  | `docker_inspect`      | `docker inspect <name>`                              |
|                  | `docker_logs`         | `docker logs --tail <n> <name>`                      |
|                  | `docker_stats`        | `docker stats --no-stream` (the flag is pinned — see below) |
|                  | `docker_images`       | `docker images`                                      |
|                  | `docker_networks`     | `docker network ls`                                  |
|                  | `docker_volumes`      | `docker volume ls`                                   |
|                  | `docker_disk_usage`   | `docker system df`                                   |
|                  | `docker_compose_ls`   | `docker compose ls`                                  |
|                  | `docker_compose_ps`   | `docker compose [-p <project>] ps -a`                |
| Helm            | `helm_list`           | `helm list -n <ns>` / `helm list --all-namespaces`   |
|                  | `helm_status`         | `helm status <release> -n <ns>`                      |
|                  | `helm_history`        | `helm history <release> -n <ns> --max <n>`           |
| Argo CD         | `argocd_apps`         | `argocd app list --output json`                      |
|                  | `argocd_app_status`   | `argocd app get <app>`                               |
| Istio           | `istioctl_proxy_status` | `istioctl proxy-status` (no arguments)             |
| Security        | `trivy_image_scan`    | `trivy image --scanners vuln --format table <image>` |
| New Relic       | `newrelic_nrql`       | `curl -H "API-Key: …" -d <json payload> https://api.newrelic.com/graphql` |
|                  | `newrelic_alerts`     | same pinned curl + payload (no model input)          |
| Terraform        | `tf_show`             | `terraform show -no-color`                           |
|                  | `tf_state_list`       | `terraform state list`                               |
|                  | `tf_plan`             | `terraform plan -no-color -input=false`              |
| git / GitHub     | `git_repo_status`     | `git status --short --branch`                        |
|                  | `git_log`             | `git log --oneline -n <n>`                           |
|                  | `git_diff`            | `git diff --stat HEAD`                               |
|                  | `gh_prs`              | `gh pr list --limit <n> --json number,title,state,...` |
|                  | `gh_runs`             | `gh run list --limit <n> --json databaseId,displayTitle,status,...` |
|                  | `gh_run_view`         | `gh run view <id> --json status,conclusion,jobs` (id digits-only) |
|                  | `gh_workflows`        | `gh workflow list --limit <n> --json id,name,state`  |
| Cloud identity   | `aws_identity`        | `aws sts get-caller-identity --output json`          |
|                  | `gcloud_identity`     | `gcloud config list --format=json`                   |
|                  | `az_account`          | `az account show`                                    |
|                  | `az_groups`           | `az group list`                                      |
| Monitoring       | `prom_query`          | `curl <PROMETHEUS_URL>/api/v1/query?query=<urlencoded PromQL>` |
|                  | `loki_query`          | `curl <LOKI_URL>/loki/api/v1/query?query=<urlencoded LogQL>&limit=<n>` |
|                  | `grafana_health`      | `curl <GRAFANA_URL>/api/health`                      |
| Ansible          | `ansible_inventory`   | `ansible-inventory [--inventory <source>] --list`    |
|                  | `ansible_playbook_tasks` | `ansible-playbook --list-tasks --list-hosts <playbook>` |
| Investigation    | `investigation_begin` / `investigation_record` / `investigation_conclude` | record only — memory, no external command |

Notes:

- Output is the **real** CLI output — Python does not re-parse it; the model
  reads exactly what an engineer would see. Verbatim quoting is a hard
  prompt rule.
- `docker stats` is **always** `--no-stream` (the pinned flag is what keeps
  it from following forever and hanging the turn).
- `terraform plan` is a **dry run** — it computes the diff, mutates nothing;
  `-input=false` keeps it from ever prompting. Requires an initialized
  directory (`terraform init`); on a fresh dir the model reports terraform's
  own error, honestly.
- Terraform and git/gh tools operate on the **current working directory** the
  agent was launched from (no path parameters — that keeps traversal out).
- `gh_prs` needs the `gh` CLI authenticated and a GitHub remote; otherwise
  the exact CLI error is returned.
- `kubectl top` needs **metrics-server** in the cluster; where it is absent,
  kubectl's exact error is returned (that is honest behavior, not a bug).
- `k8s_contexts` is a listing of kubeconfig contexts only — the agent can
  never run `config use-context` and change which cluster is in use.
- **Monitoring endpoints come from the environment, never the model:**
  `prom_query`/`loki_query`/`grafana_health` read `PROMETHEUS_URL` /
  `LOKI_URL` / `GRAFANA_URL`; unset or non-http(s) values are honest
  ToolErrors naming the variable. The model supplies only the PromQL/LogQL
  text, which is percent-encoded into the query string; the pinned curl argv
  (`--proto =https,http`, GET only) blocks `file://` and everything but the
  configured host.
- Cloud tools are identity/account level only and take no arguments at all;
  Ansible tools are listing modes only (`--list`, `--list-tasks`) with
  relative-path validation (no `/`, no leading `-`, no `..`).
- **Helm tools only read** (list/status/history — never install/upgrade/
  rollback/uninstall); **Argo CD tools only list/get** (never sync/rollback/
  delete); `istioctl_proxy_status` takes no arguments at all;
  `trivy_image_scan` validates the image reference (no leading `-`, no
  spaces) and warns its first run may take minutes (CVE DB download).
- **New Relic credentials are environment-configured, never model-chosen:**
  `NEW_RELIC_API_KEY` (passed only as a curl header value) and
  `NEW_RELIC_ACCOUNT_ID` (digits only). The NRQL text travels inside a
  `json.dumps`-built payload as a GraphQL *variable*, so it can never
  escape its string slot; only NerdGraph queries are ever sent, never
  mutations.
- Log tails (`--tail`, `-n`, `--limit`) are bounded integers, validated
  1–500 (git log 1–100, gh 1–50, Loki limit 1–1000, helm history 1–50).
- Any missing CLI / unreachable target returns the exact error — nothing is
  invented (verified live for kubectl, systemctl, journalctl, docker,
  terraform, git).

### How read-only is enforced (defense in depth)

- The tool schemas only allow picking names/counts/namespaces from validated
  arguments — there is no way to pass command text to any CLI.
- Every tool is a fixed argv template. No `sh -c` anywhere, so nothing is
  ever parsed by a shell; flags the model might abuse (e.g. `--no-stream`
  for docker stats, `-input=false` for terraform plan) are hard-coded into
  the template and cannot be removed or added.
- Only read-only verbs exist per domain — `get`/`logs`/`top` and
  `config get-contexts` (kubectl), `status`/`-u`/`ss`/`ps` (system),
  `ps`/`inspect`/`logs`/`stats`/`images`/`network ls`/`volume ls`/
  `system df`/`compose ls`/`compose ps` (docker), `show`/`state list`/
  `plan` (terraform), `list`/`status`/`history` (helm), `app list`/
  `app get` (argocd), `proxy-status` (istioctl), `image --scanners vuln`
  (trivy), `status`/`log`/`diff`/`pr list`/`run list`/`run view`/
  `workflow list` (git/gh), `--list`/`--list-tasks` (ansible), GET-only
  curl with a pinned argv (monitoring), query-only NerdGraph with a pinned
  curl (New Relic). No delete, restart, edit, apply, scale, exec, run, rm,
  pull, push, commit, reset, merge, use-context, playbook-run, install,
  upgrade, rollback, uninstall, sync, destroy — by construction.
- Names are validated per domain before reaching any CLI: Kubernetes object
  names (DNS style), systemd unit names (no `/`, no leading `-`), Docker
  names (no `/`), GitHub run ids (digits only), Ansible sources (relative
  paths, no `..`), and no path parameters at all for terraform/git/gh tools.
  This blocks flag and path injection.
- The executor re-validates every argument. Never trust the model.
- `--request-timeout`/timeouts bound slow or hanging commands, and logs are
  tail-bounded.
- Unrecognized tools/arguments return `Tool error: ...` to the model instead
  of executing.
- Tool output is truncated at 8,000 characters per result.

## 3. Why GLM 5.3

- GLM 5.3 (`z-ai/glm-5.3` on OpenRouter) is a capable, cost-effective
  general model — with strong instruction-following and **function-calling**
  support, which the tool loop has demonstrated live in every phase.
- Served by Zhipu AI through a single OpenRouter endpoint, so there is no
  separate vendor API to manage.
- An investigation loop sends many tokens (system prompt, tool schemas, tool
  output, history); GLM 5.3 keeps that cost sustainable.

## 4. How OpenRouter fits

[OpenRouter](https://openrouter.ai) is a model gateway: one API key, one
OpenAI-compatible endpoint, access to many models. We call

```
POST https://openrouter.ai/api/v1/chat/completions
```

with model `z-ai/glm-5.3` and standard `tools` / `tool` messages. The
official `openai` Python SDK works as our client with two config lines:

```python
OpenAI(api_key=..., base_url="https://openrouter.ai/api/v1")
```

Swapping to another OpenRouter model later is a one-line change (an env var
today); moving to any other OpenAI-compatible provider changes only
`agent/agent.py` configuration.

**Your model, your choice.** The default is baked in as a fallback, never a
restriction — set `OPENROUTER_MODEL` (shell or `.env`) to any model on
OpenRouter:

```bash
export OPENROUTER_MODEL=anthropic/claude-sonnet-5   # or openai/gpt-5.2, google/gemini-2.5-pro, ...
```

Two things to weigh when picking: the agent is a tool-use loop, so choose a
model with solid function-calling (a chat-only model will answer from
imagination instead of gathering evidence); and an investigation makes
several model calls per run, so price-per-call multiplies — that is why the
default is a cheap, reliable tool-caller rather than the biggest model.

**No OpenRouter at all?** `OPENROUTER_BASE_URL` points the same client at
any OpenAI-compatible endpoint — including a local one. Ollama, free and
offline:

```bash
export OPENROUTER_BASE_URL=http://localhost:11434/v1
export OPENROUTER_MODEL=llama3.2          # any Ollama model that does tools
devopsiq "docker container checkout keeps exiting, investigate"
```

## 5. Installation

Three ways — pick one. Whatever you choose, the agent also needs the CLIs of
the domains you use (kubectl, docker, gh, … — each tool reports its exact
error if its CLI is missing, so a partial install is fine).

**From PyPI (no clone):**

```bash
pipx install devopsiq        # or: pip install devopsiq
export OPENROUTER_API_KEY=sk-or-...
devopsiq --json "why is api-5d6f crash-looping?"
```

The console command is `devopsiq`; the importable package is
`agent` / `tools` / `main` (see INTEGRATION.md for library use).

**Prebuilt Docker image (bundles kubectl, helm, gh, trivy, git, curl,
docker CLI):**

```bash
docker run --rm \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v "$HOME/.kube:/home/agent/.kube:ro" \
  -v agent-records:/data \
  ghcr.io/devopsabhii/devops-ai-agent --json "why is api-5d6f crash-looping?"
```

Images are multi-arch (amd64 + arm64), published on every `v*` tag
(`:latest` tracks the newest release). Add
`-v /var/run/docker.sock:/var/run/docker.sock` for the Docker/Compose tools.

**From source (development):**

Requires **Python 3.10+** (built-in `venv`). The tool layer itself uses only
the standard library; the OpenAI SDK and python-dotenv are the only Python
dependencies.

```bash
cd ~/devops-ai-agent
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Recommended CLIs, by domain:

| Domain       | CLIs needed                                      |
| ------------ | ------------------------------------------------ |
| Kubernetes   | `kubectl` (configured cluster context; metrics-server for `top`) |
| Linux system | `systemctl`, `journalctl`, `ss`, `ps` (systemd host) |
| Docker       | `docker` (daemon running); `docker compose` for the compose tools |
| Terraform    | `terraform` (initialized working directory)      |
| Helm         | `helm` (kubeconfig)                              |
| Argo CD      | `argocd` (installed + `argocd login`)            |
| Istio        | `istioctl` (reachable mesh)                      |
| Security     | `trivy` (first scan downloads the CVE DB)        |
| git / GitHub | `git`; `gh` (authenticated, for PRs and Actions) |
| Cloud        | `aws` / `gcloud` / `az` (only the ones you use)  |
| Monitoring   | `curl` + endpoint env vars (see below)           |
| New Relic    | `curl` + `NEW_RELIC_API_KEY` / `NEW_RELIC_ACCOUNT_ID` env vars |
| Ansible      | `ansible-inventory`, `ansible-playbook`          |

### No API key? You still have the tools

The model is the only part that needs a key — the agent builds without one
(model-less mode), and two things keep working:

- **Record commands**: `devopsiq /report`, `devopsiq /investigations`, and
  the same commands inside the REPL, all work with no key configured. Only
  actual questions exit 1 with the setup message naming `OPENROUTER_API_KEY`.
- **The whole 58-tool layer** via the Python library, with no model and no
  key (see INTEGRATION.md):

```python
import agent.agent                            # registers every tool
from tools.registry import execute_tool

print(execute_tool("k8s_pods", '{"namespace": "prod"}'))
```

And the fully key-free *agent* path is a local model (Ollama example in
section 4 above) — no cloud account needed at all.

## 6. Environment setup

```bash
cp .env.example .env     # then edit it
```

`.env` must contain your real key — get one at <https://openrouter.ai/keys>:

```
OPENROUTER_API_KEY=sk-or-...
```

Optional overrides (defaults shown):

```
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=z-ai/glm-5.3
AGENT_STORE_DIR=~/.devops-ai-agent/investigations   # (Phase 7) where records are saved
PROMETHEUS_URL=http://prometheus:9090               # (Phase 8) enables prom_query
LOKI_URL=http://loki:3100                           # (Phase 8) enables loki_query
GRAFANA_URL=http://grafana:3000                     # (Phase 8) enables grafana_health
NEW_RELIC_API_KEY=NRAK-...                          # (Phase 9) NerdGraph user key
NEW_RELIC_ACCOUNT_ID=1234567                        # (Phase 9) numeric account id
```

`.env` is gitignored; the API key is never hard-coded in Python, printed, or
logged. If `OPENROUTER_API_KEY` is already set in your shell, the shell value
wins and `.env` is not consulted. Without any key the agent still starts in
model-less mode (record commands + the tool layer — see "No API key?" in
section 5). Kubernetes tools use kubectl's own config
(`~/.kube/config` or `KUBECONFIG`); no agent-side config is needed.

## 7. How to run the agent

**REPL (interactive):**

```bash
cd ~/devops-ai-agent
.venv/bin/python main.py
```

**One-shot (cron / CI / scripts):** pass the problem as the first argument.
The agent runs once, prints its answer, and exits 0 on success, 1 on
setup/API errors — so it drops straight into a pipeline:

```bash
.venv/bin/python main.py "why is api-5d6f crash-looping?"
.venv/bin/python main.py --json "why is api-5d6f crash-looping?"   # structured report
.venv/bin/python main.py --resume --json "any update?"             # continue a prior run
.venv/bin/python main.py --store-dir /tmp/runs --out report.json "..."  # pipeline paths
```

With `--json` the stdout is one JSON document (see `render_report_json` in
`agent/investigation.py`): `problem`, `status`, `hypotheses`, `evidence`,
and — once concluded — `conclusion` with `root_cause`, `remediation`,
`verification`, `confidence`. If the model never opened an investigation,
`--json`/`--out` fail with exit 1 rather than printing a malformed report.
`--out PATH` additionally writes that JSON to an exact path for pipelines
that want a known location; `--store-dir DIR` points persistence somewhere
else for the run; `--resume` continues the newest in-progress record from
the store before asking. Slash commands also work one-shot:
`python main.py /report`.

**Persistence (Phase 7):** every record mutation is auto-saved to
`~/.devops-ai-agent/investigations/` — one JSON file per investigation,
written atomically on every begin/record/conclude, so a crash mid-run
loses nothing. The REPL resumes the newest *in-progress* record at startup
(concluded records stay as history); `/investigations` lists everything on
disk; `/endinvestigation` clears memory but keeps the saved file. A broken
store (permissions, full disk) degrades to a warning in the tool result —
it never interrupts an investigation.

Example session:

```
DevOps AI Agent (Phase 9 — 58 read-only tools, persistent investigations)
Model:   z-ai/glm-5.3
Backend: https://openrouter.ai/api/v1
Store:   /home/you/.devops-ai-agent/investigations
Tools:   ansible_inventory, ansible_playbook_tasks, aws_identity,
         az_account, az_groups, docker_disk_usage, docker_images,
         docker_inspect, docker_logs, docker_networks, docker_ps,
         docker_stats, docker_volumes, gcloud_identity, gh_prs,
         gh_run_view, gh_runs, gh_workflows, git_diff, git_log,
         git_repo_status, grafana_health, investigation_begin,
         investigation_conclude, investigation_record, k8s_contexts,
         k8s_deployment_status, k8s_events, k8s_hpa, k8s_nodes,
         k8s_pod_logs, k8s_pod_status, k8s_pods, k8s_pvc, k8s_services,
         k8s_top_nodes, k8s_top_pods, loki_query, prom_query,
         sys_open_ports, sys_service_logs, sys_service_status,
         sys_top_processes, system_info, tf_plan, tf_show, tf_state_list
Commands: /investigate <problem>, /investigation, /investigations, /report, /endinvestigation
One-shot: python main.py [--json] [--resume] [--out report.json] [--store-dir DIR] "<problem>"
Type 'exit' to quit.

You: The checkout service container keeps exiting in Docker. Investigate.
Agent: (docker_ps → docker_inspect → docker_logs, tracks hypotheses, and
       ends with the structured report: the crash command, exit code, and
       the remediation recommendation)

You: /report
Agent: # Investigation report … (the canonical record, rendered from state)

You: exit
```

Type `exit` / `quit`, or press Ctrl-D / Ctrl-C to leave. Slash commands are
handled locally and never reach the model.

## 8. Current limitations

- **Each domain needs its CLI installed and reachable.** Missing CLIs,
  unauthenticated `gh`, a dead docker daemon, an uninitialized terraform
  directory, or an unreachable cluster all return the exact error honestly —
  nothing is invented, but a tool can't produce data without its backend.
- **terraform/git/gh/ansible tools are working-directory scoped.** They read
  the directory the agent was launched from — no path arguments by design
  (keeps traversal out). To investigate another repo/module, launch the
  agent there.
- **Monitoring endpoints are environment-configured by design.** Unless the
  operator sets `PROMETHEUS_URL` / `LOKI_URL` / `GRAFANA_URL`, those tools
  fail with an honest message naming the variable; the agent never invents
  a URL.
- **`kubectl top` needs metrics-server.** Clusters without it return
  kubectl's exact error — honest, but no usage data.
- **Cloud tools are identity-level only.** `aws_identity`,
  `gcloud_identity`, `az_account`, `az_groups` answer "which account am I
  looking at" but do not sweep region-scoped resources (ec2 describe-*,
  compute instances list, ...) yet.
- **Phase 9 tools need their CLIs.** `helm`, `argocd` (plus `argocd
  login`), `istioctl` and `trivy` are not bundled; without them those
  tools return the exact "not found" error. New Relic tools need
  `NEW_RELIC_API_KEY` + `NEW_RELIC_ACCOUNT_ID` in the environment; without
  them they name the missing variable — nothing is invented.
- **Trivy's first scan downloads the CVE database** and can take a couple
  of minutes; subsequent scans are fast.
- **The model can only select from the registered tools.** It can never run
  an arbitrary verb of any CLI, or a mutating one — by construction.
- **Raw CLI output to the model.** Python does not re-parse pod/docs/state;
  the model interprets real output, truncated at 8,000 characters per result.
- **Conversation history is short-term only.** The investigation record
  persists across CLI exits (Phase 7), but chat history still lives in the
  process and is lost when the CLI exits.
- **Hypothesis tracking is model-driven.** The record is what the model
  chose to record through the investigation tools; the live tracker returned
  on every record call is designed to keep that complete, but it is still
  the model's discipline.
- **No streaming, no retries/backoff** yet.
- **Read-only is enforced by construction today.** Mutating capabilities
  will only be added behind an explicit human-approval gate, much later.

## 9. Planned future phases

- **Phase 2 — tool architecture. ✅ Done.** Tool contract, registry,
  tool-use loop, first read-only tool, offline + live verification.
- **Phase 3 — Kubernetes tooling. ✅ Done.** Read-only `kubectl`-backed
  tools (pod status/logs, deployment status), name validation, verb
  allowlist, offline + live verification.
- **Phase 4 — investigation loop. ✅ Done.** The agent plans a multi-step
  investigation, tracks hypotheses and evidence in a first-class in-memory
  record, and produces a structured report (facts → observations →
  hypotheses → conclusion → remediation → verification).
- **Phase 5 — multi-domain tooling. ✅ Done.** Linux system (systemd/
  journal/ports/processes), Docker (ps/inspect/logs/stats/images),
  Kubernetes depth (events/nodes/services), Terraform (show/state/plan),
  git/GitHub (status/log/diff/PRs) — all read-only, offline + live verified.
- **Phase 6 — automation surface. ✅ Done.** One-shot CLI mode
  (`python main.py [--json] "<problem>"`) with exit codes for cron/CI, and
  a structured JSON export of the investigation report (`render_report_json`)
  so pipelines can act on the verdict. Repository is git-tracked with a
  clean `.gitignore` (secrets and the venv never ride along).
- **Phase 7 — persistence. ✅ Done.** The investigation record survives CLI
  exits: auto-saved on every mutation to
  `~/.devops-ai-agent/investigations/` (`--store-dir`/`AGENT_STORE_DIR` to
  override), atomic in-place file updates, REPL auto-resume of the newest
  in-progress record, `/investigations` listing, one-shot `--resume` /
  `--out`, and lossless `to_dict`/`from_dict` round-tripping — all offline
  tested.
- **Phase 8 — tool expansion. ✅ Done.** 21 more read-only tools (26 → 47):
  Kubernetes depth (`k8s_pods`, `k8s_top_pods`, `k8s_top_nodes`, `k8s_hpa`,
  `k8s_pvc`, `k8s_contexts`), Docker depth (`docker_networks`,
  `docker_volumes`, `docker_disk_usage`), GitHub Actions (`gh_runs`,
  `gh_run_view`, `gh_workflows`), cloud identity (`aws_identity`,
  `gcloud_identity`, `az_account`, `az_groups`), monitoring/logging
  (`prom_query`, `loki_query`, `grafana_health` — endpoints from env only),
  and Ansible listing (`ansible_inventory`, `ansible_playbook_tasks`) —
  offline tested, live-verified where the host has the CLI.
- **Phase 9 — trending-market tools. ✅ Done.** 11 more read-only tools
  (47 → 58): New Relic (`newrelic_nrql`, `newrelic_alerts` — NerdGraph over
  curl, credentials env-only, GraphQL variables so query text can't escape),
  Trivy (`trivy_image_scan`), Helm (`helm_list`, `helm_status`,
  `helm_history` — reads only), Argo CD (`argocd_apps`,
  `argocd_app_status`), Istio (`istioctl_proxy_status`), Docker Compose
  (`docker_compose_ls`, `docker_compose_ps` — live-verified on this host).
- **Phase 10 — distribution. ✅ Done.** The `devopsiq` package on PyPI
  (console command `devopsiq`, MIT) and the prebuilt multi-arch GHCR image,
  cut by a tag-driven release workflow: an offline test gate, then PyPI
  (Trusted Publishing — no token in the repo) and GHCR (amd64 + arm64) in
  parallel. **`v0.1.1` added model-less mode:** with no API key the agent
  still constructs — record commands (`/report`, `/investigations`) and the
  58-tool layer work; only model questions exit 1 with the setup message.
  Verified end-to-end against the published package.
- **Later — region-scoped cloud resources** (ec2 describe-*, compute
  instances list, ...) behind the same template pattern; more observability
  depth (New Relic dashboards/entities, Prometheus range queries); streaming;
  conversation-history persistence; a `--model` flag plus a per-user config
  file (flag > config > env > baked-in default); and a human-approval gate
  before any mutating action is ever allowed.