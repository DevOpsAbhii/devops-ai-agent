#!/usr/bin/env python3
"""Generate the DevOps AI Agent user guide PDF — install and run only.

A user-facing quickstart: the three install routes, credentials, model
choice, and how to actually run the agent. No maintenance or release
content (that lives in the Release & update playbook). Regenerate any
time:

    .venv/bin/python docs/generate_user_guide.py
"""

import datetime
import os
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Preformatted,
    PageBreak,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "DevOps_User_Guide.pdf")

INK = colors.HexColor("#1a2332")
ACCENT = colors.HexColor("#2563eb")
ACCENT_SOFT = colors.HexColor("#dbeafe")
CODE_BG = colors.HexColor("#f4f5f7")
CODE_BORDER = colors.HexColor("#d8dbe0")
MUTED = colors.HexColor("#5b6472")
RULE = colors.HexColor("#c9ced6")

S = {}
S["cover_title"] = ParagraphStyle("cover_title", fontName="Helvetica-Bold",
    fontSize=28, leading=34, textColor=INK, alignment=TA_CENTER)
S["cover_sub"] = ParagraphStyle("cover_sub", fontName="Helvetica",
    fontSize=13, leading=18, textColor=MUTED, alignment=TA_CENTER)
S["h1"] = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16,
    leading=20, textColor=INK, spaceBefore=6, spaceAfter=10)
S["h2"] = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5,
    leading=16, textColor=ACCENT, spaceBefore=12, spaceAfter=6)
S["body"] = ParagraphStyle("body", fontName="Helvetica", fontSize=10,
    leading=14.5, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=6)
S["bullet"] = ParagraphStyle("bullet", parent=S["body"], leftIndent=16,
    bulletIndent=4, spaceAfter=3)
S["code"] = ParagraphStyle("code", fontName="Courier", fontSize=8,
    leading=10, textColor=INK, backColor=CODE_BG, borderColor=CODE_BORDER,
    borderWidth=0.7, borderPadding=6, spaceAfter=8)
S["code_cap"] = ParagraphStyle("code_cap", fontName="Courier-Bold",
    fontSize=8.4, leading=12, textColor=ACCENT, spaceBefore=8, spaceAfter=3)
S["cell"] = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.6,
    leading=11.5, textColor=INK)
S["cell_mono"] = ParagraphStyle("cell_mono", parent=S["cell"],
    fontName="Courier", fontSize=8.2)
S["cell_head"] = ParagraphStyle("cell_head", fontName="Helvetica-Bold",
    fontSize=8.6, leading=11.5, textColor=colors.white)
S["cap"] = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=9,
    leading=12, textColor=MUTED, spaceAfter=8)


def wrap(text: str, width: int = 96) -> str:
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        while len(line) > width:
            cut = line.rfind(" ", 40, width)
            if cut <= 0:
                cut = width
            out.append(line[:cut])
            line = "    " + line[cut:].lstrip()
        out.append(line)
    return "\n".join(out)


def P(t): return Paragraph(escape(t), S["body"])
def H1(t): return Paragraph(escape(t), S["h1"])
def H2(t): return Paragraph(escape(t), S["h2"])


def code_text(text: str, cap: str | None = None) -> list:
    out = []
    if cap:
        out.append(Paragraph(escape(cap), S["code_cap"]))
    out.append(Preformatted(wrap(escape(text)), S["code"]))
    return out


def bullets(items: list[str]) -> list:
    return [Paragraph(escape(t), S["bullet"], bulletText="•") for t in items]


def table(headers, rows, widths, mono_cols=()) -> Table:
    data = [[Paragraph(escape(h), S["cell_head"]) for h in headers]]
    for row in rows:
        data.append([
            Paragraph(escape(c), S["cell_mono" if i in mono_cols else "cell"])
            for i, c in enumerate(row)
        ])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_SOFT]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


class Doc(BaseDocTemplate):
    pass


def on_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.6)
    canv.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canv.setFont("Helvetica", 8)
    canv.setFillColor(MUTED)
    canv.drawString(2 * cm, A4[1] - 1.25 * cm,
                    "devopsiq — install & run guide")
    canv.setFont("Helvetica-Bold", 8.5)
    canv.setFillColor(ACCENT)
    canv.drawCentredString(A4[0] / 2, 1.05 * cm, "Page %d" % doc.page)
    canv.restoreState()


story = []
TODAY = datetime.date.today().strftime("%d %B %Y")

# ---- cover ----------------------------------------------------------------- #
story += [
    Spacer(1, 6.0 * cm),
    Paragraph("Install &amp; run guide", S["cover_title"]),
    Spacer(1, 0.7 * cm),
    Paragraph("devopsiq — from zero to investigating real DevOps problems",
              S["cover_sub"]),
    Spacer(1, 1.6 * cm),
    table(["", ""], [
        ["Package", "devopsiq  (PyPI)  ·  console command: devopsiq"],
        ["Docker image", "ghcr.io/devopsabhii/devops-ai-agent  (public, "
                         "amd64 + arm64)"],
        ["Requires", "Python 3.10+ (or just Docker) · MIT license"],
        ["Key needed?", "No — the agent runs keyless for record commands "
                        "and the tool layer; only model questions need "
                        "an OpenRouter API key"],
        ["Generated", TODAY],
    ], [3.6 * cm, 12.9 * cm]),
    PageBreak(),
]

# ---- 1. install ------------------------------------------------------------ #
story += [
    H1("1. Install — pick one of three ways"),
    H2("1.1 From PyPI (fastest, no clone)"),
    *code_text("""
pipx install devopsiq          # recommended (isolated tool)
# or: pip install devopsiq

# check it works — no key needed for this:
devopsiq /report
#   → "(no investigation recorded)", exit 0
""", cap="Requirement: Python 3.10+. pipx: pip install pipx if you don't have it."),
    H2("1.2 Docker (everything bundled — CLIs included)"),
    *code_text("""
docker run --rm -it \\
  -e OPENROUTER_API_KEY=sk-or-... \\
  -v "$HOME/.kube:/home/agent/.kube:ro" \\
  -v agent-records:/data \\
  ghcr.io/devopsabhii/devops-ai-agent --json "check the cluster"
""", cap="The image bundles kubectl, helm, gh, trivy, git, curl, docker CLI."),
    *bullets([
        "The -v \"$HOME/.kube\" mount gives the agent your Kubernetes "
        "context (read-only). Drop it if you only use Docker tools.",
        "Add -v /var/run/docker.sock:/var/run/docker.sock to let the "
        "Docker/Compose tools talk to your local daemon.",
        "-v agent-records:/data keeps investigation records between runs "
        "(the image sets AGENT_STORE_DIR=/data).",
        "Investigations are read-only by construction: every tool is a "
        "fixed, allowlisted command template — nothing in the agent can "
        "mutate your cluster or files.",
    ]),
    H2("1.3 From source (development)"),
    *code_text("""
git clone https://github.com/DevOpsAbhii/devops-ai-agent.git
cd devops-ai-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python main.py /report     # same console as devopsiq
""", cap="Every devopsiq command below maps 1:1 to .venv/bin/python main.py."),
    H2("1.4 The CLIs of the domains you use"),
    P("The agent shells out to the real CLIs — install only the ones you "
      "need; each tool reports its exact error if its CLI is missing, so "
      "a partial install is fine: kubectl (Kubernetes), docker + docker "
      "compose (containers), terraform / helm / argocd / istioctl / "
      "trivy (infra & security), git and gh (repos & Actions), aws / "
      "gcloud / az (cloud identity), curl (monitoring endpoints), "
      "ansible-inventory / ansible-playbook (Ansible)."),
    PageBreak(),
]

# ---- 2. credentials --------------------------------------------------------- #
story += [
    H1("2. Set up credentials (or none at all)"),
    H2("2.1 With an OpenRouter API key (full agent)"),
    *code_text("""
# option A — a .env file next to the install (or in the repo for source installs):
cp .env.example .env 2>/dev/null || true
echo 'OPENROUTER_API_KEY=sk-or-v1-...' >> .env

# option B — your shell:
export OPENROUTER_API_KEY=sk-or-v1-...
""", cap="Get a key at openrouter.ai/keys. Never commit the key anywhere."),
    H2("2.2 No key? The agent still runs (model-less mode)"),
    *bullets([
        "The REPL starts without a key: it prints a [setup] notice and "
        "continues.",
        "Record commands work fully: /investigate, /investigation, "
        "/investigations, /report, /endinvestigation.",
        "The entire 58-tool library works (as a Python package or via "
        "the investigation records).",
        "Only questions to the model exit 1 with a loud setup message — "
        "you never get a silent failure or an invented answer.",
    ]),
    H2("2.3 No OpenRouter? Point it at anything OpenAI-compatible"),
    *code_text("""
# local Ollama — free and offline:
export OPENROUTER_BASE_URL=http://localhost:11434/v1
export OPENROUTER_MODEL=llama3.2        # any Ollama model that does tools
devopsiq "docker container checkout keeps exiting, investigate"
""", cap="Same client, same agent — only the endpoint changes."),
    PageBreak(),
]

# ---- 3. model choice --------------------------------------------------------- #
story += [
    H1("3. Choose your model"),
    P("The default is z-ai/glm-5.3 — a cheap, reliable tool-caller (the "
      "agent is a tool-use loop, so pick a model with solid function "
      "calling; an investigation makes several calls per run, so "
      "price-per-call multiplies). Four ways to change it — the first "
      "one set wins:"),
    table(["Priority", "How", "Scope"], [
        ["1", "--model NAME flag", "One run only"],
        ["2", "/model <name> (REPL command)", "Saves to "
         "~/.devops-ai-agent/config.json — every future run"],
        ["3", "OPENROUTER_MODEL env var (or .env)", "Every run on this "
         "machine"],
        ["4", "built-in default (z-ai/glm-5.3)", "Fallback"],
    ], [1.9 * cm, 6.6 * cm, 8.0 * cm]),
    *code_text("""
# per-run override:
devopsiq --model openai/gpt-5.2 "why is api-5d6f crash-looping?"

# persistent default (from the REPL):
You: /model openai/gpt-5.2
Model set to openai/gpt-5.2 (saved in /home/you/.devops-ai-agent/config.json).

# show the current model any time:
You: /model
Model: openai/gpt-5.2
Config file: /home/you/.devops-ai-agent/config.json (save a default with /model <name>)
""", cap="Transient failures (timeouts, 429s, 5xx) retry automatically with backoff."),
    PageBreak(),
]

# ---- 4. run it ---------------------------------------------------------------- #
story += [
    H1("4. Run it"),
    H2("4.1 Interactive REPL"),
    *code_text("""
devopsiq
""", cap="Banner shows the model, backend, store location, and 58 tools."),
    *code_text("""
DevOps AI Agent (Phase 9 — 58 read-only tools, persistent investigations)
Model:   z-ai/glm-5.3
Backend: https://openrouter.ai/api/v1
Store:   /home/you/.devops-ai-agent/investigations

You: The checkout service container keeps exiting in Docker. Investigate.
Agent: (docker_ps → docker_inspect → docker_logs, tracks hypotheses,
       ends with the structured report: crash command, exit code,
       remediation)

You: /report            ← canonical report from the record, any time
You: exit
""", cap="Slash commands are handled locally — they never reach the model."),
    table(["Command", "What it does"], [
        ["/investigate <problem>", "Open a formal investigation (same "
         "path the model uses)"],
        ["/investigation", "Show the live tracked state "
         "(hypotheses/evidence)  · alias /status"],
        ["/investigations", "List saved records on disk, newest first  "
         "· alias /history"],
        ["/report", "Show the canonical report (once concluded)"],
        ["/endinvestigation", "Clear the record (the saved copy stays as "
         "history)  · alias /end"],
        ["/model [<name>]", "Show the active model, or save a default "
         "and switch to it"],
    ], [4.9 * cm, 11.6 * cm], mono_cols=(0,)),
    H2("4.2 One-shot (cron / CI / scripts)"),
    *code_text("""
devopsiq "why is api-5d6f crash-looping?"            # investigate, print, exit
devopsiq --json "why is api-5d6f crash-looping?"     # structured JSON report
devopsiq --resume --json "any update?"               # continue a prior run
devopsiq --store-dir /tmp/runs --out report.json "…" # pipeline paths
devopsiq /report                                     # slash commands work one-shot
""", cap="Exit codes: 0 = completed, 1 = setup/API error — safe for pipelines."),
    *bullets([
        "--json prints one JSON document: problem, status, hypotheses, "
        "evidence, and conclusion (root_cause, remediation, verification, "
        "confidence) — a pipeline can act on the verdict.",
        "--out PATH writes that JSON to an exact file; --store-dir DIR "
        "redirects persistence for the run; --resume continues the newest "
        "in-progress record.",
        "Records auto-save to ~/.devops-ai-agent/investigations/ on every "
        "change — the REPL resumes the newest in-progress one at startup.",
    ]),
    H2("4.3 Verify your install in 30 seconds"),
    *code_text("""
devopsiq /report                                  # works with NO key → "(no investigation recorded)"
devopsiq /model                                   # shows the active model
devopsiq "what files changed in the last commit?" # needs the key + git installed
""", cap="If the first line works, the install is good."),
    PageBreak(),
]

# ---- 5. troubleshooting --------------------------------------------------------- #
story += [
    H1("5. When something doesn't work"),
    table(["Symptom", "Meaning", "Fix"], [
        ["[input] OPENROUTER_API_KEY is not set (exit 1 on a question)",
         "Model-less mode: you asked the model something with no key",
         "Add the key (section 2.1) or use /report-style commands, "
         "which work keyless"],
        ["[input] OPENROUTER_API_KEY still has the placeholder value",
         "The .env still says your_key_here",
         "Replace your_key_here with the real sk-or-v1-... key"],
        ["[error] The API key was rejected (HTTP 401)",
         "The key is wrong, expired, or revoked",
         "Re-check the key at openrouter.ai/keys; mind shell exports "
         "override .env"],
        ["[error] The OpenRouter API returned an error (HTTP 4xx/5xx) "
         "after several seconds",
         "Transient failures are retried 3× with backoff before this "
         "message appears",
         "Retry later; persistent 5xx = OpenRouter-side issue"],
        ["Tool error: k8s_get...: kubectl: command not found",
         "That domain's CLI isn't installed",
         "Install the CLI (section 1.4) — or ignore if you don't use "
         "that domain"],
        ["Every k8s tool errors with connection refused",
         "No cluster reachable from your kubeconfig",
         "Point ~/.kube/config at a cluster, or mount it in Docker"],
        ["pip installs an older version than the latest",
         "pip's local HTTP cache",
         "pip install --no-cache-dir --upgrade devopsiq"],
    ], [5.6 * cm, 4.8 * cm, 6.1 * cm]),
    Spacer(1, 0.4 * cm),
    P("What the agent will never do: it cannot mutate anything. All 58 "
      "tools are read-only by construction — fixed command templates, "
      "validated names, no shell, no writes to your cluster or files. "
      "Investigation records live only in ~/.devops-ai-agent/."),
    Paragraph("Install & run guide — generated from the repository on "
              + TODAY + ". Regenerate: .venv/bin/python "
              "docs/generate_user_guide.py", S["cap"]),
]

doc = Doc(OUT, pagesize=A4,
          leftMargin=2 * cm, rightMargin=2 * cm,
          topMargin=2 * cm, bottomMargin=2 * cm,
          title="devopsiq — Install & run guide",
          author="DevOpsAbhii")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
              id="main")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
doc.build(story)
print("WROTE", OUT)
