# DevOps AI Agent

An AI agent that investigates real DevOps problems. The end goal: ask it
something like *"Why is my Kubernetes pod in CrashLoopBackOff?"* and have it
gather evidence, reason about the evidence, identify the likely root cause,
recommend remediation, and give verification steps.

**Phase 5 (what is in this repository right now)** broadens the agent from
Kubernetes-only to the wider DevOps surface: Linux systemd services and
journals, Docker containers, Terraform state/plan, and git/GitHub pull
requests — every tool still read-only, still a fixed allowlisted argv
template. **Phase 6 adds the automation surface:** a one-shot CLI mode
(`python main.py "problem"` — exit-code driven, cron/CI-friendly) and a
structured JSON export of the investigation report, so pipelines can act on
the verdict instead of parsing markdown. The repository is now git-tracked.
Every phase still built from scratch — no LangChain, LangGraph,
AutoGen, CrewAI, or MCP.

---

## 1. What this project is

The agent is built intentionally: we own the core architecture — how the
model is called, how conversation history flows, how tool selection +
execution + evidence feedback work — instead of depending on a framework
for it.

In Phase 5 the agent:
- holds a conversation with **GLM 5.3** through **OpenRouter**;
- has **26 real, read-only tools** across six domains: host facts,
  Kubernetes (6 tools), Linux system (4), Docker (5), Terraform (3),
  git/GitHub (4), plus the 3 investigation tools;
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
| `main.py`                   | REPL loop, one-shot CLI, environment loading, `/investigate` commands, error messages |
| `agent/agent.py`            | `DevOpsAgent` — client, history, `ask()`, `_complete()` loop |
| `agent/prompts.py`          | The system prompt (versioned/tested separately)              |
| `agent/investigation.py`    | First-class investigation record: hypotheses, verdicts, evidence, report renderer (pure data) |
| `tools/base.py`             | Tool contract: `Tool`, `ToolError`, `read_command_output()`  |
| `tools/registry.py`         | `register/get_tools/execute_tool` — tools declared & executed here |
| `tools/preflight.py`        | `system_info` — host facts (allowlisted read-only commands)  |
| `tools/kubernetes.py`       | 6 kubectl tools: pod status/logs, deployment, events, nodes, services |
| `tools/system.py`           | systemd/journal/ss/ps tools — services, journals, ports, top processes |
| `tools/docker.py`           | read-only docker tools — ps, inspect, logs, stats, images    |
| `tools/terraform.py`        | `tf_show` / `tf_state_list` / `tf_plan` (working directory)  |
| `tools/git_ci.py`           | git status/log/diff + `gh_prs` (working directory)           |
| `tools/investigation.py`    | `investigation_begin` / `investigation_record` / `investigation_conclude` — meta-tools for the investigation record |
| `tests/test_phase2.py`      | Offline suite: contract, safety, loop (stdlib `unittest`)     |
| `tests/test_phase3.py`      | Offline suite: k8s command lines + verb-allowlist (fake kubectl) |
| `tests/test_phase4.py`      | Offline suite: investigation state, meta-tools, loop-driven investigation |
| `tests/test_phase5.py`      | Offline suite: argv templates + name validation for all new domains (fake CLIs) |

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
| `/report`                | Show the canonical report (once concluded)          |
| `/endinvestigation`      | Clear the record (memory only — no system changes)  |

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

### The tools (Phase 5)

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
| Linux system     | `sys_service_status`  | `systemctl status <unit> --no-pager`                 |
|                  | `sys_service_logs`    | `journalctl -u <unit> --no-pager -n <n>`             |
|                  | `sys_open_ports`      | `ss -tlnp`                                           |
|                  | `sys_top_processes`   | `ps aux --sort=-%cpu --no-headers`                   |
| Docker           | `docker_ps`           | `docker ps -a`                                       |
|                  | `docker_inspect`      | `docker inspect <name>`                              |
|                  | `docker_logs`         | `docker logs --tail <n> <name>`                      |
|                  | `docker_stats`        | `docker stats --no-stream` (the flag is pinned — see below) |
|                  | `docker_images`       | `docker images`                                      |
| Terraform        | `tf_show`             | `terraform show -no-color`                           |
|                  | `tf_state_list`       | `terraform state list`                               |
|                  | `tf_plan`             | `terraform plan -no-color -input=false`              |
| git / GitHub     | `git_repo_status`     | `git status --short --branch`                        |
|                  | `git_log`             | `git log --oneline -n <n>`                           |
|                  | `git_diff`            | `git diff --stat HEAD`                               |
|                  | `gh_prs`              | `gh pr list --limit <n> --json number,title,state,...` |
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
- Log tails (`--tail`, `-n`, `--limit`) are bounded integers, validated
  1–500 (git log 1–100, gh 1–50).
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
- Only read-only verbs exist per domain — `get`/`logs` (kubectl), `status`/
  `-u`/`ss`/`ps` (system), `ps`/`inspect`/`logs`/`stats`/`images`
  (docker), `show`/`state list`/`plan` (terraform), `status`/`log`/`diff`/
  `pr list` (git/gh). No delete, restart, edit, apply, scale, exec, run, rm,
  pull, push, commit, reset, merge, destroy — by construction.
- Names are validated per domain before reaching any CLI: Kubernetes object
  names (DNS style), systemd unit names (no `/`, no leading `-`), Docker
  names (no `/`), and no path parameters at all for terraform/git/gh tools.
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

## 5. Installation

Requires **Python 3.10+** (built-in `venv`) and the CLIs of the domains you
use — each tool reports its exact error if the CLI is missing, so the agent
runs with whatever subset you have. The tool layer itself uses only the
standard library; the OpenAI SDK and python-dotenv are the only Python
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
| Kubernetes   | `kubectl` (configured cluster context)           |
| Linux system | `systemctl`, `journalctl`, `ss`, `ps` (systemd host) |
| Docker       | `docker` (daemon running)                        |
| Terraform    | `terraform` (initialized working directory)      |
| git / GitHub | `git`; `gh` (authenticated, for PRs)             |

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
```

`.env` is gitignored; the API key is never hard-coded in Python, printed, or
logged. If `OPENROUTER_API_KEY` is already set in your shell, the shell value
wins and `.env` is not consulted. Kubernetes tools use kubectl's own config
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
```

With `--json` the stdout is one JSON document (see `render_report_json` in
`agent/investigation.py`): `problem`, `status`, `hypotheses`, `evidence`,
and — once concluded — `conclusion` with `root_cause`, `remediation`,
`verification`, `confidence`. If the model never opened an investigation,
`--json` fails with exit 1 rather than printing a malformed report. Slash
commands also work one-shot: `python main.py /report`.

Example session:

```
DevOps AI Agent (Phase 6 — one-shot CLI, JSON reports, git-tracked)
Model:   z-ai/glm-5.3
Backend: https://openrouter.ai/api/v1
Tools:   docker_images, docker_inspect, docker_logs, docker_ps,
         docker_stats, gh_prs, git_diff, git_log, git_repo_status,
         investigation_begin, investigation_conclude, investigation_record,
         k8s_deployment_status, k8s_events, k8s_nodes, k8s_pod_logs,
         k8s_pod_status, k8s_services, sys_open_ports, sys_service_logs,
         sys_service_status, sys_top_processes, system_info, tf_plan,
         tf_show, tf_state_list
Commands: /investigate <problem>, /investigation, /report, /endinvestigation
One-shot: python main.py [--json] "<problem>"   (cron/CI-friendly)
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

## 8. Current limitations (Phase 5)

- **Each domain needs its CLI installed and reachable.** Missing CLIs,
  unauthenticated `gh`, a dead docker daemon, an uninitialized terraform
  directory, or an unreachable cluster all return the exact error honestly —
  nothing is invented, but a tool can't produce data without its backend.
- **terraform/git/gh tools are working-directory scoped.** They read the
  directory the agent was launched from — no path arguments by design (keeps
  traversal out). To investigate another repo/module, launch the agent there.
- **Cloud provider CLIs (AWS/GCP/Azure), monitoring/log aggregation, and
  generic CI/CD platforms are not integrated yet.** The agent says so rather
  than pretending.
- **No `kubectl top` (resource usage) yet** — minikube lacks metrics-server
  by default, so it would fail honestly on this cluster; it's on the roadmap.
- **The model can only select from the registered tools.** It can never run
  an arbitrary verb of any CLI, or a mutating one — by construction.
- **Raw CLI output to the model.** Python does not re-parse pod/docs/state;
  the model interprets real output, truncated at 8,000 characters per result.
- **Short-term memory only.** History *and the investigation record* live in
  the process and are lost when the CLI exits.
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
  *Pending:* `kubectl top` (needs metrics-server), `kubectl get hpa`/
  `pvc`, node resource usage, and a `kubectl` context selector.
- **Phase 6 — automation surface. ✅ Done.** One-shot CLI mode
  (`python main.py [--json] "<problem>"`) with exit codes for cron/CI, and
  a structured JSON export of the investigation report (`render_report_json`)
  so pipelines can act on the verdict. Repository is git-tracked with a
  clean `.gitignore` (secrets and the venv never ride along).
- **Later — cloud, monitoring/logging, CI/CD-platform tooling;**
  streaming; persistence (the investigation record survives CLI exits); and
  a human-approval gate before any mutating action is ever allowed.