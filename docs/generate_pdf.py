#!/usr/bin/env python3
"""Generate the DevOps AI Agent project documentation PDF.

Reads the real source files from the repository so the code in the PDF is
always the code that ships. Run from anywhere:

    .venv/bin/python docs/generate_pdf.py
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
    KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = "/home/abhishek/devops-ai-agent"
OUT = os.path.join(ROOT, "DevOps_AI_Agent_Documentation.pdf")

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
INK = colors.HexColor("#1a2332")          # near-black blue
ACCENT = colors.HexColor("#2563eb")       # blue
ACCENT_SOFT = colors.HexColor("#dbeafe")
CODE_BG = colors.HexColor("#f4f5f7")
CODE_BORDER = colors.HexColor("#d8dbe0")
MUTED = colors.HexColor("#5b6472")
RULE = colors.HexColor("#c9ced6")

# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #
S = {}
S["cover_title"] = ParagraphStyle("cover_title", fontName="Helvetica-Bold",
    fontSize=30, leading=36, textColor=INK, alignment=TA_CENTER)
S["cover_sub"] = ParagraphStyle("cover_sub", fontName="Helvetica",
    fontSize=13.5, leading=19, textColor=MUTED, alignment=TA_CENTER)
S["cover_meta"] = ParagraphStyle("cover_meta", fontName="Helvetica",
    fontSize=11, leading=16, textColor=INK, alignment=TA_CENTER)
S["h1"] = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17,
    leading=21, textColor=INK, spaceBefore=6, spaceAfter=10, keepWithNext=1)
S["h2"] = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
    leading=17, textColor=ACCENT, spaceBefore=12, spaceAfter=6, keepWithNext=1)
S["h3"] = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11,
    leading=15, textColor=INK, spaceBefore=10, spaceAfter=4, keepWithNext=1)
S["body"] = ParagraphStyle("body", fontName="Helvetica", fontSize=10,
    leading=14.5, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=6)
S["bullet"] = ParagraphStyle("bullet", parent=S["body"], leftIndent=16,
    bulletIndent=4, spaceAfter=3)
S["code"] = ParagraphStyle("code", fontName="Courier", fontSize=7.6,
    leading=9.4, textColor=INK, backColor=CODE_BG, borderColor=CODE_BORDER,
    borderWidth=0.7, borderPadding=6, spaceAfter=8)
S["code_cap"] = ParagraphStyle("code_cap", fontName="Courier-Bold", fontSize=8.4,
    leading=12, textColor=ACCENT, spaceBefore=8, spaceAfter=3, keepWithNext=1)
S["cap"] = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=9,
    leading=12, textColor=MUTED, spaceAfter=8)
S["cell"] = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.6,
    leading=11.5, textColor=INK)
S["cell_mono"] = ParagraphStyle("cell_mono", parent=S["cell"],
    fontName="Courier", fontSize=8.2)
S["cell_head"] = ParagraphStyle("cell_head", fontName="Helvetica-Bold",
    fontSize=8.6, leading=11.5, textColor=colors.white)
S["toc_title"] = ParagraphStyle("toc_title", parent=S["h1"], spaceAfter=14)


def wrap_code(text: str, width: int = 96) -> str:
    """Hard-wrap over-long source lines so nothing overflows the frame."""
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


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read().rstrip()


def code(file: str, lang: str = "python") -> list:
    """A captioned, escaped code block built from a real repository file."""
    src = wrap_code(escape(read(file)))
    return [Paragraph(file + "   (" + lang + ")", S["code_cap"]),
            Preformatted(src, S["code"])]


def code_text(text: str, cap: str | None = None) -> list:
    src = wrap_code(escape(text))
    out = []
    if cap:
        out.append(Paragraph(cap, S["code_cap"]))
    out.append(Preformatted(src, S["code"]))
    return out


def bullets(items: list[str]) -> list:
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def table(headers: list[str], rows: list[list[str]], widths: list,
          mono_cols: tuple = ()) -> Table:
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


# --------------------------------------------------------------------------- #
# Document template with running header/footer + TOC capture
# --------------------------------------------------------------------------- #
class Doc(BaseDocTemplate):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.section = ""

    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph):
            style = fl.style.name
            if style in ("h1", "h2"):
                text = fl.getPlainText()
                level = 0 if style == "h1" else 1
                key = "h-%s-%d" % (style, abs(hash((text, self.page))))
                self.canv.bookmarkPage(key)
                self.notify("TOCEntry", (level, text, self.page, key))
                if style == "h1":
                    self.section = text
                self.canv.addOutlineEntry(text, key, level=level, closed=False)


def on_page(canv, doc):
    canv.saveState()
    if doc.page > 1:  # skip cover
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.6)
        canv.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(MUTED)
        canv.drawString(2 * cm, A4[1] - 1.25 * cm, "DevOps AI Agent — Project Documentation")
        sec = getattr(doc, "section", "")
        if sec:
            canv.drawRightString(A4[0] - 2 * cm, A4[1] - 1.25 * cm, sec[:70])
        canv.setFont("Helvetica-Bold", 8.5)
        canv.setFillColor(ACCENT)
        canv.drawCentredString(A4[0] / 2, 1.05 * cm, "Page %d" % doc.page)
    canv.restoreState()


# --------------------------------------------------------------------------- #
# Story
# --------------------------------------------------------------------------- #
story = []
TODAY = datetime.date.today().strftime("%d %B %Y")


def H1(t): return Paragraph(escape(t), S["h1"])
def H2(t): return Paragraph(escape(t), S["h2"])
def H3(t): return Paragraph(escape(t), S["h3"])
def P(t): return Paragraph(escape(t), S["body"])


# ---- cover ---------------------------------------------------------------- #
story += [
    Spacer(1, 5.2 * cm),
    Paragraph("DevOps AI Agent", S["cover_title"]),
    Spacer(1, 0.7 * cm),
    Paragraph("A from-scratch, read-only AI agent that investigates real "
              "infrastructure problems — with the full code walkthrough",
              S["cover_sub"]),
    Spacer(1, 1.6 * cm),
    table(["", ""], [
        ["Project", "devops-ai-agent  (~/devops-ai-agent)"],
        ["Model", "GLM 5.3  (z-ai/glm-5.3) via OpenRouter"],
        ["Language", "Python 3.10+ (stdlib tools + openai SDK + python-dotenv)"],
        ["Phases complete", "1 – 10  (Phase 10: Distribution — PyPI package + prebuilt Docker image)"],
        ["Tools", "58 real, read-only tools across 15 domains"],
        ["Latest release", "v0.1.1 — devopsiq on PyPI + GHCR image "
                           "(multi-arch), model-less mode included"],
        ["Generated", TODAY],
    ], [4.2 * cm, 12.3 * cm]),
    Spacer(1, 2.2 * cm),
    Paragraph("Built without LangChain, LangGraph, AutoGen, CrewAI or MCP — "
              "every layer owned, every command allowlisted.", S["cover_meta"]),
    PageBreak(),
]

# ---- TOC ------------------------------------------------------------------ #
toc = TableOfContents()
toc.levelStyles = [
    ParagraphStyle("toc1", fontName="Helvetica-Bold", fontSize=11, leading=16,
                   leftIndent=4, textColor=INK),
    ParagraphStyle("toc2", fontName="Helvetica", fontSize=9.5, leading=13.5,
                   leftIndent=18, textColor=INK),
]
story += [H1("Contents"), toc, PageBreak()]

# ---- 1. overview ----------------------------------------------------------- #
story += [
    H1("1. Project overview"),
    P("DevOps AI Agent is an AI agent that investigates real DevOps problems. "
      "The end goal: ask it something like “Why is my Kubernetes pod in "
      "CrashLoopBackOff?” and have it gather evidence, reason about that "
      "evidence, identify the likely root cause, recommend remediation, and "
      "give verification steps."),
    P("The agent is built intentionally: the project owns the core "
      "architecture — how the model is called, how conversation history "
      "flows, how tool selection + execution + evidence feedback work — "
      "instead of depending on a framework for it. No LangChain, LangGraph, "
      "AutoGen, CrewAI or MCP anywhere."),
    H2("What the agent does today (Phases 1–10)"),
    *bullets([
        "Holds a conversation with GLM 5.3 through OpenRouter's "
        "OpenAI-compatible endpoint.",
        "Has 58 real, read-only tools across fifteen domains: host facts, "
        "Kubernetes (12), Linux system (4), Docker + Compose (10), "
        "Terraform (3), Helm (3), Argo CD (2), Istio (1), Trivy (1), "
        "git/GitHub + Actions (7), cloud identity (4), monitoring/logging "
        "(3), New Relic (2), Ansible (2), plus the 3 investigation "
        "meta-tools.",
        "Runs a tool-use loop: when the model decides a question needs "
        "evidence, it requests the tool, the application executes it locally, "
        "and the real output is fed back to the model, which then answers "
        "from it.",
        "Runs an investigation loop: for a reported problem it opens a "
        "record with initial hypotheses, gathers evidence with the right "
        "domain tools, updates each hypothesis's verdict, concludes with "
        "root cause + remediation + verification, and ends with a structured "
        "report.",
        "Exposes a one-shot CLI (python main.py “problem”) with "
        "exit codes for cron/CI, plus a structured --json export of the "
        "investigation report so pipelines can act on the verdict.",
        "Installs without cloning the repo: the devopsiq package on PyPI "
        "(console command devopsiq) and a prebuilt multi-arch Docker image "
        "(ghcr.io/devopsabhii/devops-ai-agent) — both cut automatically by "
        "a tag-driven release workflow.",
        "Runs without an API key (model-less mode): the agent constructs "
        "with client=None, record commands (/report, /investigations) and "
        "the whole tool layer work, and only the chat path raises — loudly "
        "naming OPENROUTER_API_KEY. Any OpenAI-compatible endpoint works "
        "instead of OpenRouter, including a local Ollama (OPENROUTER_BASE_URL "
        "+ OPENROUTER_MODEL).",
    ]),
    H2("Read-only by design"),
    P("Every tool is a static, allowlisted command template — the model can "
      "never pass arbitrary command text, can never select a mutating verb "
      "(no delete/restart/edit/apply/scale/exec/run/rm/reset/destroy "
      "anywhere), and no mutating capability exists. Object and unit names "
      "are validated before reaching any CLI; flags are injected only by "
      "fixed templates, never by model text. Any future mutating capability "
      "will only ever arrive behind an explicit human-approval gate."),
]

story += [
    H2("Phase summary"),
    table(["Phase", "Scope", "Status"], [
        ["1", "Foundation: repo skeleton, venv, .env, OpenAI client through "
              "OpenRouter.", "Done"],
        ["2", "Tool architecture: Tool contract, registry, tool-use loop, "
              "first real tool (system_info), offline + live tests.", "Done"],
        ["3", "Kubernetes tooling: read-only kubectl-backed tools (pod "
              "status/logs, deployment status), name validation, verb "
              "allowlist.", "Done"],
        ["4", "Investigation loop: first-class in-memory record (hypotheses, "
              "evidence, verdicts), meta-tools, structured report.", "Done"],
        ["5", "Multi-domain tooling: Linux system, Docker, k8s depth "
              "(events/nodes/services), Terraform, git/GitHub — all "
              "read-only.", "Done"],
        ["6", "Automation surface: one-shot CLI with exit codes, structured "
              "JSON report export, repository git-tracked.", "Done"],
        ["7", "Persistence: the investigation record survives CLI exits — "
              "auto-saved on every mutation, REPL auto-resume, "
              "/investigations, one-shot --resume/--out/--store-dir.", "Done"],
        ["8", "Tool expansion: 21 more read-only tools (26 → 47) — k8s depth "
              "(pods/top/hpa/pvc/contexts), Docker depth (networks/volumes/"
              "disk usage), GitHub Actions (runs/run view/workflows), cloud "
              "identity (AWS/GCP/Azure), monitoring (Prometheus/Loki/Grafana, "
              "env-configured endpoints), Ansible listing.", "Done"],
        ["9", "Trending-market tools: 11 more read-only tools (47 → 58) — "
              "New Relic (NRQL + alerts over NerdGraph, env credentials), "
              "Trivy image scanning, Helm releases, Argo CD GitOps, Istio "
              "mesh status, Docker Compose.", "Done"],
        ["10", "Distribution: the devopsiq package on PyPI (console "
               "command, MIT) and a prebuilt GHCR Docker image "
               "(multi-arch, non-root, bundled CLIs), cut by a tag-driven "
               "release workflow with a test gate and Trusted "
               "Publishing.", "Done"],
    ], [1.6 * cm, 11.4 * cm, 1.5 * cm]),
    PageBreak(),
]

# ---- 2. architecture ------------------------------------------------------- #
story += [
    H1("2. Architecture"),
    H2("Request flow"),
    *code_text("""
You (terminal)
   |  plain text
   v
main.py ......................... CLI REPL / one-shot, .env loading, errors
   |
   v
agent/agent.py (DevOpsAgent) .... system prompt + conversation history
   |
   v  the tool-use loop, inside DevOpsAgent._complete():
   |
   |   attach tool schemas -> call model
   |        |
   |        +- model requests tool(s)? -- yes --> tools/registry.execute_tool()
   |        |                                    |   per call, in order
   |        |                                    |     -> allowlisted read-only
   |        |                                    |        command runs for real
   |        |                                    |     -> result echoed back as
   |        |                                    |        a "tool" message
   |        |                                    <-- loop calls the model again
   |        +- model answers in plain text? -- yes --> done
   |              (safety cap: max 10 tool-use turns, then abort)
   v
OpenRouter (https://openrouter.ai/api/v1)
   v
GLM 5.3 (z-ai/glm-5.3)
""", cap="The full request flow, from the terminal to the model and back."),
    H2("Module map"),
    table(["Path", "Responsibility"], [
        ["main.py", "REPL loop, one-shot CLI, environment loading, slash "
                    "commands, error messages"],
        ["agent/agent.py", "DevOpsAgent — client, history, ask(), _complete() "
                           "loop"],
        ["agent/prompts.py", "The system prompt (versioned/tested separately)"],
        ["agent/investigation.py", "Investigation record: hypotheses, "
                                   "verdicts, evidence, report renderer "
                                   "(pure data)"],
        ["agent/store.py", "InvestigationStore — one JSON file per record, "
                           "atomic in-place writes, resume/list (Phase 7)"],
        ["tools/base.py", "Tool contract: Tool, ToolError, "
                          "read_command_output()"],
        ["tools/registry.py", "register/get_tools/execute_tool — tools are "
                              "declared and executed here"],
        ["tools/preflight.py", "system_info — host facts (allowlisted "
                               "read-only commands)"],
        ["tools/kubernetes.py", "12 kubectl tools: pods, pod status/logs, "
                                "deployments, events, nodes, top (cpu/mem), "
                                "hpa, pvc, services, contexts"],
        ["tools/system.py", "systemd/journal/ss/ps tools"],
        ["tools/docker.py", "docker ps/inspect/logs/stats/images + "
                            "networks/volumes/disk usage + compose ls/ps"],
        ["tools/terraform.py", "tf_show / tf_state_list / tf_plan"],
        ["tools/helm.py", "helm_list / helm_status / helm_history (Phase 9)"],
        ["tools/argocd.py", "argocd_apps / argocd_app_status (Phase 9)"],
        ["tools/istio.py", "istioctl_proxy_status (Phase 9)"],
        ["tools/trivy.py", "trivy_image_scan (Phase 9)"],
        ["tools/newrelic.py", "newrelic_nrql / newrelic_alerts — NerdGraph "
                              "over curl, env credentials (Phase 9)"],
        ["tools/git_ci.py", "git status/log/diff + gh_prs + gh Actions "
                            "(runs / run view / workflows)"],
        ["tools/cloud.py", "cloud identity: aws_identity, gcloud_identity, "
                           "az_account, az_groups (Phase 8)"],
        ["tools/monitoring.py", "prom_query, loki_query, grafana_health — "
                                "endpoints from env config only (Phase 8)"],
        ["tools/ansible.py", "ansible_inventory, ansible_playbook_tasks — "
                             "listing modes only (Phase 8)"],
        ["tools/investigation.py", "investigation_begin / _record / _conclude "
                                   "meta-tools"],
        ["tests/test_phase2.py", "Offline suite: contract, safety, loop"],
        ["tests/test_phase3.py", "Offline suite: k8s command lines + verb "
                                 "allowlist (fake kubectl)"],
        ["tests/test_phase4.py", "Offline suite: investigation state, "
                                 "meta-tools, loop-driven investigation"],
        ["tests/test_phase5.py", "Offline suite: argv templates + name "
                                 "validation for all new domains"],
        ["tests/test_automation.py", "Offline suite: JSON reports + one-shot "
                                     "CLI (Phase 6)"],
        ["tests/test_phase7.py", "Offline suite: round-trip serialization, "
                                 "store files, auto-save, resume, CLI flags "
                                 "(Phase 7)"],
        ["tests/test_phase8.py", "Offline suite: argv templates + validation "
                                 "for the 21 Phase 8 tools (fake CLIs, "
                                 "env-based monitoring)"],
        ["tests/test_phase9.py", "Offline suite: New Relic credentials/"
                                 "payload, trivy/helm/argocd/istio/compose "
                                 "argv templates (Phase 9)"],
    ], [5.4 * cm, 11.1 * cm], mono_cols=(0,)),
    PageBreak(),
]

# ---- 3. phase 1 ------------------------------------------------------------ #
story += [
    H1("3. Phase 1 — Foundation"),
    P("Phase 1 lays the ground the rest builds on: a clean virtual "
      "environment, a deliberately minimal dependency list, secret handling "
      "from the first day, and one chokepoint where the model is called."),
    H2("Dependencies"),
    P("The dependency list is two packages. OpenRouter exposes an "
      "OpenAI-compatible API, so the official OpenAI SDK is the only client "
      "library needed; python-dotenv loads .env without touching shell "
      "state."),
    *code("requirements.txt", "config"),
    *code(".env.example", "config"),
    H2("Secrets and configuration rules"),
    *bullets([
        ".env is gitignored; the API key is never hard-coded, printed or "
        "logged.",
        "Configuration resolution order is explicit argument > environment "
        "> default (in DevOpsAgent.__init__).",
        "A placeholder key is rejected with a clear message, so a copied "
        ".env.example cannot silently fail at the API.",
        "If OPENROUTER_API_KEY is already set in the shell, the shell value "
        "wins and .env is not consulted.",
    ]),
    H2("Pointing the OpenAI SDK at OpenRouter"),
    *code_text("""
from openai import OpenAI

# OpenRouter exposes an OpenAI-compatible API, so the official OpenAI
# SDK is a drop-in client — just pointed at OpenRouter's base URL.
self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

# defaults (agent/agent.py)
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "z-ai/glm-5.3"
""", cap="The two config lines that make the openai SDK speak to OpenRouter."),
    P("Swapping to another OpenRouter model later is a one-line change (an "
      "env var today); moving to any other OpenAI-compatible provider "
      "changes only agent/agent.py configuration."),
    PageBreak(),
]

# ---- 4. phase 2 ------------------------------------------------------------ #
story += [
    H1("4. Phase 2 — Tool architecture"),
    P("Phase 2 builds the machinery every later phase reuses: a Tool "
      "contract, a registry, a safe command executor, and the tool-use loop "
      "that lets the model request tools and receive real output."),
    H2("The Tool contract (tools/base.py)"),
    P("A Tool bundles four things: a stable name the model calls, a "
      "description (which is what the model actually reads), a JSON Schema "
      "for its arguments, and a local executor that receives parsed "
      "arguments and returns evidence text."),
    *code("tools/base.py"),
    H2("The registry (tools/registry.py)"),
    P("Tools self-register at import time. execute_tool() never raises: "
      "every failure — unknown tool, unparseable JSON, executor error — "
      "becomes a “Tool error: ...” string the model can read and "
      "adapt to, keeping the conversation loop alive."),
    *code("tools/registry.py"),
    H2("The first real tool (tools/preflight.py)"),
    P("system_info proves the whole loop while staying strictly read-only: "
      "the model may only choose among static allowlisted commands; its "
      "parameter can never carry arbitrary command text."),
    *code("tools/preflight.py"),
    H2("The tool-use loop (agent/agent.py)"),
    P("All model calls funnel through DevOpsAgent._complete(). Each turn: "
      "(1) the full history is sent with every tool's schema attached; "
      "(2) if the reply contains tool calls, the assistant tool-request turn "
      "is echoed into history verbatim and each call is executed locally; "
      "(3) every real result is appended as a sibling “tool” "
      "message pinned to its tool_call_id; (4) the loop calls the model "
      "again — giving it the evidence to reflect on — and repeats until it "
      "answers in plain text. MAX_TOOL_ITERATIONS = 10 aborts runaway loops."),
    *code_text("""
MAX_TOOL_ITERATIONS = 10

def _complete(self) -> str:
    \"\"\"The tool-use loop — the single chokepoint where the backend is called.\"\"\"
    for _ in range(MAX_TOOL_ITERATIONS):
        request: dict = {"model": self.model, "messages": self.messages}
        if self.tools:
            request["tools"] = [tool.schema() for tool in self.tools]

        response = self.client.chat.completions.create(**request)
        message = response.choices[0].message

        if not message.tool_calls:
            content = message.content
            if content is None:
                raise RuntimeError("The model returned an empty response.")
            return content

        # Echo the assistant tool-request turn verbatim, then answer each
        # call with a sibling "tool" message referencing its call id.
        self.messages.append(_echo_tool_request(message))
        for call in message.tool_calls:
            result = execute_tool(call.function.name, call.function.arguments)
            self.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    raise RuntimeError(
        f"The model did not finish after {MAX_TOOL_ITERATIONS} tool-use turns."
    )
""", cap="agent/agent.py — the loop every later phase reuses."),
    H2("Phase 2 tests (offline)"),
    P("tests/test_phase2.py swaps the real OpenAI client for a fake one so "
      "the loop logic is exercised deterministically. The system_info tool "
      "still runs for real (it executes only allowlisted read-only "
      "commands), and a security test proves the model cannot smuggle "
      "arbitrary commands through arguments:"),
    *code_text("""
def test_execute_rejects_non_allowlisted_command(self):
    # Proof the model cannot smuggle arbitrary commands through arguments:
    # the call must fail with an error, never run anything.
    result = execute_tool("system_info", '{"command": "rm -rf /"}')
    self.assertTrue(result.startswith("Tool error"))
    self.assertIn("unknown command", result)
    self.assertEqual(result.count("\\n"), 0)  # single-line error, no output

def test_loop_executes_tool_and_returns_final_answer(self):
    responses = FakeResponses([_tool_call_response(), _text_response("Reboot buddy.")])
    agent = self.make_agent(responses)
    answer = agent.ask("What OS is this host running? Use your tool.")
    self.assertEqual(answer, "Reboot buddy.")
    roles = [m["role"] for m in agent.messages]
    self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
    tool_msg = agent.messages[3]
    self.assertIn("$ uname -a", tool_msg["content"])  # real output was used
""", cap="tests/test_phase2.py — the safety proof and the loop proof."),
    PageBreak(),
]

# ---- 5. phase 3 ------------------------------------------------------------ #
story += [
    H1("5. Phase 3 — Kubernetes tooling"),
    P("Phase 3 adds the first domain tools: kubectl-backed, read-only. The "
      "safety model is defense in depth — only get/logs verbs exist, "
      "hard-coded in argv templates; there is no sh -c anywhere, so nothing "
      "is ever parsed by a shell; object names are validated against "
      "Kubernetes naming rules before touching kubectl, blocking flag "
      "injection (names starting with “-”) and garbage input; "
      "--request-timeout plus a subprocess timeout bound slow or hung "
      "clusters."),
    *code("tools/kubernetes.py"),
    P("Output is real kubectl JSON/text — Python does not re-parse it, so "
      "the model reads exactly what an engineer would see. Verbatim quoting "
      "is a hard prompt rule."),
    H2("Phase 3 tests — fake kubectl on PATH"),
    P("tests/test_phase3.py places a stub kubectl (a shell script that "
      "echoes its arguments) first on PATH, then asserts the EXACT command "
      "lines the agent builds — and that invalid names are rejected without "
      "kubectl ever running:"),
    *code_text("""
def test_pod_status_command(self):
    result = execute_tool("k8s_pod_status", '{"pod": "web-1", "namespace": "prod"}')
    self.assertIn("ARGS: get pod web-1 -n prod -o json --request-timeout=10", result)

def test_only_read_only_verbs_are_possible(self):
    # Walk every generated command line: the verb must be get or logs only.
    invocations = [
        ("k8s_pod_status", '{"pod": "x"}'),
        ("k8s_pod_logs", '{"pod": "x"}'),
        ("k8s_deployment_status", '{"deployment": "x"}'),
    ]
    for tool, args in invocations:
        result = execute_tool(tool, args)
        line = next(l for l in result.splitlines() if l.startswith("ARGS: "))
        verb = line.split()[1]
        self.assertIn(verb, {"get", "logs"}, f"{tool} used a non-read-only verb")

def test_invalid_pod_name_rejected_without_invoking_kubectl(self):
    for bad in ["--flag", "UPPER", "has space", "x" * 300, "..", "-n"]:
        result = execute_tool("k8s_pod_status", '{"pod": "%s"}' % bad)
        self.assertTrue(result.startswith("Tool error"), bad)
        self.assertNotIn("ARGS:", result)  # kubectl never ran
""", cap="tests/test_phase3.py — argv assertions and injection rejection."),
    PageBreak(),
]

# ---- 6. phase 4 ------------------------------------------------------------ #
story += [
    H1("6. Phase 4 — The investigation loop"),
    P("Phase 4 is the conceptual heart of the project: when a user reports a "
      "concrete problem, the agent stops answering and starts "
      "investigating. It opens a formal record, gathers evidence, tracks "
      "hypotheses, and concludes with a structured report."),
    H2("The flow"),
    *bullets([
        "The model opens a record with investigation_begin (one-line problem "
        "+ 2–4 initial hypotheses, which become H1, H2, …).",
        "It plans what it needs, then calls the read-only tools one "
        "deliberate step at a time.",
        "Every finding is recorded with investigation_record: evidence notes "
        "(linked to a hypothesis when they bear on one) and verdicts "
        "(supported / refuted / confirmed).",
        "Each record call returns the live tracker — problem, status, "
        "hypotheses with verdicts, evidence — so the model always knows "
        "where it stands without inspecting all of history.",
        "When evidence is sufficient the model calls investigation_conclude "
        "with root cause, remediation recommendations (nothing is ever "
        "executed), verification steps, and confidence — then ends its "
        "answer with the structured report.",
    ]),
    P("The record lives in the application, not just the conversation: the "
      "report is rendered deterministically from it, and the CLI exposes it "
      "directly (/investigate, /investigation, /report, /endinvestigation). "
      "The agent's own answer and /report are kept consistent by "
      "construction: render_report() is the single report format."),
    H2("The data model (agent/investigation.py)"),
    P("A pure-data module — no model calls, no I/O — so it is fully "
      "unit-testable. Hypotheses get sequential ids, verdicts are "
      "validated against an enum, evidence can link to a hypothesis, and "
      "conclusion requires root cause, remediation and verification."),
    *code("agent/investigation.py"),
    H2("The meta-tools (tools/investigation.py)"),
    P("Three tools the model uses to maintain the record while it works. "
      "These are the only stateful tools — and they mutate nothing outside "
      "the agent's own memory. The module also holds the shared functions "
      "the CLI reuses, so the model path and the human path are literally "
      "the same code."),
    *code("tools/investigation.py"),
    H2("Phase 4 tests — loop-driven investigation"),
    P("tests/test_phase4.py covers three layers: the pure data model, the "
      "meta-tools lifecycle, and the full loop with a fake client — the "
      "model opens an investigation, records a verdict, concludes, and the "
      "tracked state must exist in the application afterwards:"),
    *code_text("""
def test_loop_tracks_investigation_and_concludes(self):
    responses = [
        self._tool_response("investigation_begin", {
            "problem": "checkout pod is CrashLoopBackOff",
            "initial_hypotheses": ["bad image", "exiting entrypoint"],
        }),
        self._tool_response("investigation_record", {
            "kind": "verdict", "hypothesis_id": "H1", "status": "refuted",
            "content": "image pulls cleanly",
        }),
        self._tool_response("investigation_conclude", {
            "summary": "The entrypoint exits immediately.",
            "root_cause": "The image command exits with code 1.",
            "remediation": ["Fix the entrypoint", "add a liveness probe"],
            "verification": ["rollout restart", "restartCount flat"],
            "confidence": "high",
        }),
        self._text_response("Diagnosis complete."),
    ]
    ...
    answer = agent.ask("Investigate: the checkout pod is CrashLoopBackOff.")
    # State persisted outside the model: the tracker shows the verdict.
    tracker = status_text()
    self.assertIn("Status: concluded (confidence high)", tracker)
    self.assertIn("- H1 [refuted] bad image", tracker)
""", cap="tests/test_phase4.py — the model's plan becomes application state."),
    PageBreak(),
]

# ---- 7. phase 5 ------------------------------------------------------------ #
story += [
    H1("7. Phase 5 — Multi-domain tooling"),
    P("Phase 5 broadens the agent from Kubernetes-only to the wider DevOps "
      "surface: Linux systemd services and journals, Docker containers, "
      "Terraform state/plan, and git/GitHub pull requests — every tool "
      "still read-only, still a fixed allowlisted argv template, now 26 "
      "tools in total."),
    H2("Tool catalogue with backing commands"),
    table(["Domain", "Tool", "Backing command (read-only)"], [
        ["Host", "system_info", "date/uname/uptime/df/free"],
        ["Kubernetes", "k8s_pod_status", "kubectl get pod <pod> -n <ns> -o json"],
        ["", "k8s_pod_logs", "kubectl logs <pod> -n <ns> --tail=<n>"],
        ["", "k8s_deployment_status", "kubectl get deployment <dep> -n <ns> -o json"],
        ["", "k8s_events", "kubectl get events -n <ns> --sort-by=.lastTimestamp -o wide "
                           "[--field-selector involvedObject.name=<obj>]"],
        ["", "k8s_nodes", "kubectl get nodes -o json"],
        ["", "k8s_services", "kubectl get services -n <ns> -o json"],
        ["Linux system", "sys_service_status", "systemctl status <unit> --no-pager"],
        ["", "sys_service_logs", "journalctl -u <unit> --no-pager -n <n>"],
        ["", "sys_open_ports", "ss -tlnp"],
        ["", "sys_top_processes", "ps aux --sort=-%cpu --no-headers"],
        ["Docker", "docker_ps", "docker ps -a"],
        ["", "docker_inspect", "docker inspect <name>"],
        ["", "docker_logs", "docker logs --tail <n> <name>"],
        ["", "docker_stats", "docker stats --no-stream (flag pinned)"],
        ["", "docker_images", "docker images"],
        ["Terraform", "tf_show", "terraform show -no-color"],
        ["", "tf_state_list", "terraform state list"],
        ["", "tf_plan", "terraform plan -no-color -input=false (dry run)"],
        ["git/GitHub", "git_repo_status", "git status --short --branch"],
        ["", "git_log", "git log --oneline -n <n>"],
        ["", "git_diff", "git diff --stat HEAD"],
        ["", "gh_prs", "gh pr list --limit <n> --json number,title,state,..."],
        ["Investigation", "investigation_begin / _record / _conclude",
         "record only — memory, no external command"],
    ], [2.6 * cm, 4.6 * cm, 9.3 * cm], mono_cols=(1, 2)),
    H2("Domain modules (representative code)"),
    P("Each module follows the same shape as Phase 2/3: a validated argv "
      "template, a name validator where names exist, and register() calls. "
      "The four new modules:"),
    *code("tools/system.py"),
    PageBreak(),
    *code("tools/docker.py"),
    PageBreak(),
    *code("tools/terraform.py"),
    PageBreak(),
    *code("tools/git_ci.py"),
    H2("Safety notes baked into Phase 5"),
    *bullets([
        "docker stats is ALWAYS --no-stream: without it the command follows "
        "forever and would hang the turn.",
        "terraform plan is a dry run — it computes the diff, mutates "
        "nothing; -input=false keeps it from ever prompting. On a fresh "
        "directory the model reports terraform's own error, honestly.",
        "Terraform and git/gh tools operate on the current working directory "
        "the agent was launched from — no path parameters, which keeps "
        "traversal out.",
        "Log tails are bounded integers, validated 1–500 (git log 1–100, "
        "gh 1–50).",
        "Any missing CLI / unreachable target returns the exact error — "
        "nothing is invented.",
    ]),
    H2("Phase 5 tests — stub CLIs per domain"),
    P("tests/test_phase5.py puts tiny stub binaries on PATH for the CLIs "
      "each module uses and asserts the exact argv templates built — plus "
      "that invalid names/arguments are rejected with a Tool error before "
      "the binary is ever invoked. It ends with the full 26-tool registry "
      "check."),
    *code_text("""
class FakeBins:
    \"\"\"A temp dir of stub executables (echo "ARGS: $*") placed first on PATH.\"\"\"
    def __init__(self, *names: str):
        self._dir = tempfile.mkdtemp(prefix="p5-bins-")
        self._prev_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self._dir}:{self._prev_path}"
        for name in names:
            path = os.path.join(self._dir, name)
            with open(path, "w") as fh:
                fh.write('#!/bin/sh\\necho "ARGS: $*"\\n')
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

def test_docker_stats_always_no_stream(self):
    # The one docker verb that would block forever without --no-stream.
    result = self.run_tool("docker_stats", "{}")
    self.assertTrue(result.startswith("$ docker stats --no-stream"), result)

def test_plan_command_pinned_safe_flags(self):
    # -input=false is what keeps plan from ever sitting on a prompt.
    result = self.run_tool("tf_plan", "{}")
    self.assertTrue(
        result.startswith("$ terraform plan -no-color -input=false"), result
    )

def test_all_phase5_tools_registered(self):
    names = {tool.name for tool in get_tools()}
    self.assertEqual(len(names), 26)
""", cap="tests/test_phase5.py — stubs, pinned flags, and the registry check."),
    PageBreak(),
]

# ---- 8. phase 6 ------------------------------------------------------------ #
story += [
    H1("8. Phase 6 — Automation surface"),
    P("Phase 6 turns the REPL-only agent into something a pipeline can use: "
      "a one-shot CLI mode (exit-code driven, cron/CI-friendly) and a "
      "structured JSON export of the investigation report. The repository "
      "is also git-tracked with a clean .gitignore."),
    H2("main.py — the CLI, both modes"),
    P("REPL mode stays the interactive home. One-shot mode sends the problem "
      "once, prints the agent's report, and exits 0 on success / 1 on "
      "setup or API errors — so it drops straight into a pipeline. With "
      "--json the stdout is one JSON document; if the model never opened an "
      "investigation, --json fails with exit 1 rather than printing a "
      "malformed report."),
    *code("main.py"),
    H2("render_report_json — the automation view"),
    P("The JSON export lives beside the markdown renderer in "
      "agent/investigation.py. It always returns the same shape whether or "
      "not the investigation is concluded, and no model text is trusted — "
      "everything is re-derived deterministically from the tracked record:"),
    *code_text("""
def render_report_json(self) -> dict:
    \"\"\"Structured export of the investigation, for CI/automation tooling.\"\"\"
    out: dict = {
        "problem": self.problem,
        "status": "concluded" if self.conclusion is not None else "in_progress",
        "hypotheses": [
            {"id": h.id, "statement": h.statement, "status": h.status,
             "notes": list(h.notes)}
            for h in self.hypotheses
        ],
        "evidence": [
            {"id": e.id, "content": e.content, "hypothesis_id": e.hypothesis_id}
            for e in self.evidence
        ],
    }
    if self.conclusion is not None:
        c = self.conclusion
        out["conclusion"] = {
            "summary": c.summary,
            "root_cause": c.root_cause,
            "remediation": list(c.remediation),
            "verification": list(c.verification),
            "confidence": c.confidence,
        }
    return out
""", cap="agent/investigation.py — the same record, machine-readable."),
    H2("Phase 6 tests — offline, no network"),
    P("tests/test_automation.py verifies the JSON shape in progress and "
      "concluded, that JSON and markdown agree, and drives run_one_shot "
      "with a stubbed client:"),
    *code_text("""
def test_json_output_is_valid_and_structured(self):
    inv_tools.start_investigation("checkout pod crash-loops")
    inv_tools.conclude_investigation(
        summary="image entrypoint exits 1",
        root_cause="command exits immediately",
        remediation="fix the entrypoint command",
        verification="redeploy and watch restart count",
        confidence="high",
    )
    code, out = self._run("report it as json", as_json=True)
    self.assertEqual(code, 0)
    data = json.loads(out)
    self.assertEqual(data["status"], "concluded")
    self.assertEqual(data["problem"], "checkout pod crash-loops")
    self.assertEqual(data["conclusion"]["root_cause"], "command exits immediately")

def test_json_flag_without_investigation_fails_loud(self):
    code, out = self._run("hello", as_json=True)
    self.assertEqual(code, 1)
    self.assertNotIn("investigation complete.", out)

def test_markdown_never_leaks_to_json_stdout(self):
    ...
    json.loads(out)  # the entire stdout must be one valid JSON document
""", cap="tests/test_automation.py — the pipeline contract."),
    PageBreak(),
]

# ---- 9. phase 7 ------------------------------------------------------------ #
story += [
    H1("9. Phase 7 — Persistence"),
    P("Phase 7 makes the investigation record durable: every mutation is "
      "auto-saved to disk, so the record survives CLI exits. Storage lives in "
      "~/.devops-ai-agent/investigations/ by default (overridable with "
      "--store-dir or AGENT_STORE_DIR) — never inside a working directory, so "
      "records never pollute a repo. Conversation history stays ephemeral by "
      "design."),
    H2("Round-trip serialization (agent/investigation.py)"),
    P("render_report_json() is already a lossless view of the record, so "
      "persistence reuses it: to_dict() adds schema and saved_at metadata, "
      "and from_dict() rebuilds the record — tolerant of unknown keys, strict "
      "about our own (a corrupt file raises, and the store turns that into "
      "“skip this file” rather than a crash):"),
    *code_text("""
def to_dict(self, *, saved_at: str | None = None) -> dict:
    \"\"\"Full serializable state, for the store to write to disk.\"\"\"
    out = self.render_report_json()
    out["schema"] = 1
    if saved_at is not None:
        out["saved_at"] = saved_at
    return out

@classmethod
def from_dict(cls, data: dict) -> "Investigation":
    \"\"\"Rebuild an Investigation from to_dict() output.\"\"\"
    inv = cls(data["problem"])
    for h in data.get("hypotheses") or []:
        hyp = Hypothesis(
            id=str(h.get("id", "")),
            statement=str(h.get("statement", "")),
            status="proposed",
            notes=[str(n) for n in (h.get("notes") or [])],
        )
        hyp.set_status(str(h.get("status", "proposed")))
        number = _id_number(hyp.id, "H")
        if number is None:
            raise InvestigationError(f"malformed hypothesis id {hyp.id!r}")
        inv.hypotheses.append(hyp)
        if number >= inv._next_h:
            inv._next_h = number + 1
    ...
""", cap="agent/investigation.py — the record can now round-trip losslessly."),
    H2("The store (agent/store.py)"),
    P("One JSON file per investigation, written atomically (tmp file + "
      "rename) into the store directory. Every save rewrites the active "
      "record's file in place — the directory holds one file per "
      "investigation, not per change, and a crash mid-investigation loses "
      "nothing. Best-effort by design: an unwritable directory or corrupt "
      "file degrades to None / a skipped file, never an exception."),
    *code("agent/store.py"),
    PageBreak(),
    H2("The chokepoint wiring (tools/investigation.py)"),
    P("All record mutations already funnel through start_investigation / "
      "record / conclude_investigation / finish_investigation — shared by "
      "tool executors and CLI commands. That is the only place persistence "
      "needed wiring: each mutation calls _persist(), which appends a "
      "one-line “(saved to …)” note to the tool result the model "
      "sees, or a warning when the store is unavailable:"),
    *code_text("""
def _persist() -> str:
    \"\"\"Auto-save the active record; returns a short note for the result text.\"\"\"
    store = _get_store()
    if store is None:
        return ""
    path = store.save(_active)
    if path is None:
        return "\\n(note: persistence unavailable — the record is not being saved)"
    return f"\\n(saved to {path})"

def resume_investigation() -> str | None:
    \"\"\"Load the newest in-progress record from the store into memory.\"\"\"
    global _active
    if _active is not None:
        return None
    store = _get_store()
    if store is None:
        return None
    inv = store.resume_latest()
    if inv is None:
        return None
    _active = inv
    return f"Resumed: {inv.problem} — /investigation to view, continue as before."
""", cap="tools/investigation.py — save on every mutation, resume on startup."),
    H2("CLI surface (main.py)"),
    *bullets([
        "--store-dir PATH — override the persistence directory for the run "
        "(AGENT_STORE_DIR env also works).",
        "--resume — one-shot: continue the newest in-progress record before "
        "asking, so CI can pick up a prior run.",
        "--out PATH — additionally write the JSON report to an exact path "
        "(exit 1 if no investigation, same rule as --json).",
        "REPL startup auto-resumes the newest in-progress record and prints "
        "a one-line notice; /investigations (alias /history) lists saved "
        "records, marking the live one.",
        "Banner now shows the store directory: Store: <path>.",
    ]),
    H2("Phase 7 tests — still offline, hermetic"),
    P("tests/test_phase7.py covers four layers: round-trip serialization, "
      "store behavior (in-place updates, resume ordering, collision suffix, "
      "corrupt/unwritable tolerance), chokepoint auto-save, and the CLI "
      "flags. No test touches the real home directory — every store under "
      "test points at a tempdir, and set_store(None) disables persistence "
      "where it is not under test:"),
    *code_text("""
def test_save_updates_same_file_in_place(self):
    inv = Investigation("one problem only")
    first = self.store.save(inv)
    inv.record_evidence("some evidence")
    second = self.store.save(inv)
    self.assertEqual(first, second)
    self.assertEqual(list(Path(self.tmp).glob("*.json")), [first])
    data = json.loads(first.read_text(encoding="utf-8"))
    self.assertEqual(data["evidence"][0]["content"], "some evidence")

def test_resume_latest_skips_concluded_and_corrupt(self):
    self.store.save(Investigation("older in-progress"))
    self.store.forget()
    newer = Investigation("newer concluded")
    newer.conclude(summary="s", root_cause="r", remediation=["x"],
                   verification=["y"], confidence="low")
    self.store.save(newer)
    (Path(self.tmp) / "99999999-999999-garbage.json").write_text("{not json")
    resumed = self.store.resume_latest()
    self.assertIsNotNone(resumed)
    self.assertEqual(resumed.problem, "older in-progress")

def test_start_and_record_save_with_note(self):
    result = inv_tools.start_investigation("api-5d6f stuck rollout")
    self.assertIn("(saved to", result)
    self.assertEqual(len(list(Path(self.tmp).glob("*.json"))), 1)
""", cap="tests/test_phase7.py — persistence proven without a network."),
    PageBreak(),
]

# ---- 10. phase 8 ------------------------------------------------------------ #
story += [
    H1("10. Phase 8 — Tool expansion"),
    P("Phase 8 is pure additive breadth: 21 new read-only tools take the "
      "registry from 26 to 47, without changing the safety model by one "
      "iota. Kubernetes gets depth (pod listing, kubectl top resource usage, "
      "HPAs, PVCs, context listing), Docker gets depth (networks, volumes, "
      "disk usage), GitHub Actions arrives via gh (runs, run jobs, "
      "workflows), cloud identity lands for AWS/GCP/Azure, monitoring and "
      "logging query Prometheus, Loki and Grafana, and Ansible gets "
      "inventory/playbook listing. One deliberate safety extension: the "
      "monitoring module takes a URL — so its endpoint can never come from "
      "the model (see below)."),
    H2("The 21 new tools with backing commands"),
    table(["Domain", "Tool", "Backing command (read-only)"], [
        ["K8s depth", "k8s_pods", "kubectl get pods -n <ns> -o wide"],
        ["", "k8s_top_pods", "kubectl top pods -n <ns> [--sort-by=cpu|memory]"],
        ["", "k8s_top_nodes", "kubectl top nodes"],
        ["", "k8s_hpa", "kubectl get hpa [<name>] -n <ns> -o json"],
        ["", "k8s_pvc", "kubectl get pvc [<name>] -n <ns> -o json"],
        ["", "k8s_contexts", "kubectl config get-contexts (listing only — "
                             "never use-context)"],
        ["Docker", "docker_networks", "docker network ls"],
        ["", "docker_volumes", "docker volume ls"],
        ["", "docker_disk_usage", "docker system df"],
        ["GitHub Actions", "gh_runs", "gh run list --limit <n> --json "
                                      "databaseId,displayTitle,status,..."],
        ["", "gh_run_view", "gh run view <id> --json status,conclusion,jobs "
                            "(id digits-only)"],
        ["", "gh_workflows", "gh workflow list --limit <n> --json id,name,state"],
        ["Cloud", "aws_identity", "aws sts get-caller-identity --output json"],
        ["", "gcloud_identity", "gcloud config list --format=json"],
        ["", "az_account", "az account show"],
        ["", "az_groups", "az group list"],
        ["Monitoring", "prom_query", "curl <PROMETHEUS_URL>/api/v1/query?"
                                     "query=<urlencoded PromQL>"],
        ["", "loki_query", "curl <LOKI_URL>/loki/api/v1/query?query=<urlencoded "
                           "LogQL>&limit=<n>"],
        ["", "grafana_health", "curl <GRAFANA_URL>/api/health"],
        ["Ansible", "ansible_inventory", "ansible-inventory [--inventory <src>] --list"],
        ["", "ansible_playbook_tasks", "ansible-playbook --list-tasks "
                                       "--list-hosts <playbook>"],
    ], [3.0 * cm, 4.4 * cm, 9.1 * cm], mono_cols=(1, 2)),
    H2("New modules (representative code)"),
    P("tools/cloud.py is the simplest module in the project: four tools, "
      "zero arguments — identity/account level only, so nothing can be "
      "injected and no region-scoped resource sweep is possible yet."),
    *code("tools/cloud.py"),
    PageBreak(),
    P("tools/monitoring.py is the one deliberate safety extension of the "
      "phase: curl takes a URL, so the endpoint is read from environment "
      "configuration only (PROMETHEUS_URL / LOKI_URL / GRAFANA_URL). The "
      "model supplies query text, which is percent-encoded; the curl argv is "
      "pinned (--proto =https,http blocks file://; GET only; no shell)."),
    *code("tools/monitoring.py"),
    PageBreak(),
    P("tools/ansible.py takes path-shaped arguments, so they are validated "
      "as relative path fragments: no leading / or -, no .. segment, no "
      "slash. Both tools are pure listing modes — they connect to no "
      "managed host and change nothing."),
    *code("tools/ansible.py"),
    H2("k8s and gh depth — same argv-template pattern"),
    P("The six kubectl tools reuse the module's _check_name/_namespace "
      "validators and the pinned --request-timeout; k8s_contexts reads the "
      "local kubeconfig only and can never switch contexts. gh run ids are "
      "digits-only validated, which blocks flag injection entirely:"),
    *code_text("""
def _checked_run_id(args: dict) -> str:
    run_id = args.get("run_id")
    if (
        not isinstance(run_id, str)
        or not run_id.isdigit()
        or not 1 <= len(run_id) <= 20
    ):
        raise ToolError("run_id must be the numeric GitHub Actions run id")
    return run_id

def _gh_run_view(args: dict) -> str:
    run_id = _checked_run_id(args)
    return read_command_output(
        ("gh", "run", "view", run_id, "--json", "status,conclusion,jobs"),
        timeout=_TIMEOUT_S,
    )
""", cap="tools/git_ci.py — a digits-only id is the whole validation story."),
    *code_text("""
def _k8s_contexts(args: dict) -> str:
    # Local kubeconfig read — no cluster API, so no request timeout needed.
    return read_command_output(("kubectl", "config", "get-contexts"))
""", cap="tools/kubernetes.py — listing contexts, never switching them."),
    H2("Phase 8 tests — stubs, env-configured monitoring"),
    P("tests/test_phase8.py follows the same stub-binary strategy and adds "
      "one new dimension: environment configuration. The monitoring tests "
      "prove that an unset endpoint is an honest ToolError naming the "
      "variable, that a file:// endpoint is refused without curl ever "
      "running, and that the PromQL text lands percent-encoded in the "
      "pinned curl argv:"),
    *code_text("""
def test_unset_endpoint_is_an_honest_error(self):
    for tool, var in (
        ("prom_query", "PROMETHEUS_URL"),
        ("loki_query", "LOKI_URL"),
        ("grafana_health", "GRAFANA_URL"),
    ):
        result = self.run_tool(tool, '{"query": "up"}')
        self.assertTrue(result.startswith("Tool error"), (tool, result))
        self.assertIn(var, result)
        self.assertNotIn("ARGS:", result)  # curl was never invoked

def test_unsafe_endpoint_scheme_rejected(self):
    os.environ["PROMETHEUS_URL"] = "file:///etc/passwd"
    result = self.run_tool("prom_query", '{"query": "up"}')
    self.assertTrue(result.startswith("Tool error"), result)
    self.assertNotIn("ARGS:", result)

def test_gh_run_id_must_be_digits(self):
    for bad in ("-1", "abc", "12; rm -rf /", "--jobs", "1 2", "x" * 21, ""):
        result = self.run_tool("gh_run_view", f'{{"run_id": "{bad}"}}')
        self.assertTrue(result.startswith("Tool error"), (bad, result))
        self.assertNotIn("ARGS:", result)  # gh was never invoked
""", cap="tests/test_phase8.py — endpoints from env, ids digits-only."),
    PageBreak(),
]

# ---- 11. phase 9 ------------------------------------------------------------ #
story += [
    H1("11. Phase 9 — New Relic and trending DevOps tools"),
    P("Phase 9 keeps the additive rhythm: 11 more read-only tools take the "
      "registry from 47 to 58, aimed at what the current DevOps market runs "
      "on — observability (New Relic), supply-chain security (Trivy), "
      "release management (Helm), GitOps (Argo CD), service mesh (Istio) "
      "and Docker Compose. Host CLI reality is handled the project way: "
      "compose is installed and live-verified; helm/trivy/argocd/istioctl "
      "are not installed on the build host, so their tools are stub-tested "
      "and fail with the exact CLI error until an operator installs them."),
    H2("The 11 new tools with backing commands"),
    table(["Domain", "Tool", "Backing command (read-only)"], [
        ["New Relic", "newrelic_nrql", "curl -H \"API-Key: …\" -d <json payload> "
                                       "https://api.newrelic.com/graphql"],
        ["", "newrelic_alerts", "same pinned curl + payload (no model input)"],
        ["Security", "trivy_image_scan", "trivy image --scanners vuln "
                                         "--format table <image>"],
        ["Helm", "helm_list", "helm list -n <ns> | --all-namespaces"],
        ["", "helm_status", "helm status <release> -n <ns>"],
        ["", "helm_history", "helm history <release> -n <ns> --max <n>"],
        ["Argo CD", "argocd_apps", "argocd app list --output json"],
        ["", "argocd_app_status", "argocd app get <app>"],
        ["Istio", "istioctl_proxy_status", "istioctl proxy-status (no args)"],
        ["Compose", "docker_compose_ls", "docker compose ls"],
        ["", "docker_compose_ps", "docker compose [-p <project>] ps -a"],
    ], [2.6 * cm, 4.6 * cm, 9.3 * cm], mono_cols=(1, 2)),
    H2("New Relic — the monitoring pattern, extended to POST"),
    P("tools/newrelic.py extends tools/monitoring.py's \"endpoint from "
      "environment config\" rule to a POST API. Credentials NEVER come from "
      "the model: NEW_RELIC_API_KEY is read from the environment and passed "
      "only as a curl header value; NEW_RELIC_ACCOUNT_ID must be digits "
      "(it enters the payload as an integer). The NRQL text travels inside "
      "a json.dumps-built payload as a GraphQL variable — it can never "
      "escape its string slot — and only NerdGraph queries are ever sent, "
      "never mutations:"),
    *code("tools/newrelic.py"),
    PageBreak(),
    H2("Helm, Argo CD, Istio, Trivy — reads only, per domain"),
    P("Helm gets the kubernetes.py name validator and only the "
      "list/status/history verbs (no install/upgrade/rollback/uninstall). "
      "Argo CD gets list/get only (no sync/rollback/delete). Istio is one "
      "argument-free template. Trivy validates the image reference before "
      "a scan that can take minutes on first run (CVE DB download):"),
    *code("tools/helm.py"),
    PageBreak(),
    *code("tools/argocd.py"),
    *code("tools/istio.py"),
    *code("tools/trivy.py"),
    H2("Phase 9 tests — credentials, payloads, argv"),
    P("tests/test_phase9.py proves the New Relic env-credential contract "
      "(unset → honest error naming the variable; non-digit account id → "
      "refused), that the alerts payload is byte-identical regardless of "
      "what the model sends, and the exact argv of every stubbed CLI:"),
    *code_text("""
def test_alerts_payload_ignores_model_args(self):
    # No model input reaches the payload — a no-injection proof.
    os.environ["NEW_RELIC_API_KEY"] = "nrk-test"
    os.environ["NEW_RELIC_ACCOUNT_ID"] = "42"
    result = self.run_tool("newrelic_alerts", '{"evil": "drop tables"}')
    line = result.splitlines()[0]
    payload = line[line.index('{"query"'):].rsplit(" https://", 1)[0]
    data = json.loads(payload)
    self.assertEqual(data["variables"], {"accountId": 42})
    self.assertNotIn("evil", result)

def test_invalid_image_refs_rejected(self):
    for bad in ("-q", "img; rm -rf /", "img extra", "", "x" * 201):
        result = self.run_tool("trivy_image_scan", f'{{"image": "{bad}"}}')
        self.assertTrue(result.startswith("Tool error"), (bad, result))
        self.assertNotIn("ARGS:", result)  # trivy was never invoked
""", cap="tests/test_phase9.py — env credentials and injection rejection."),
    PageBreak(),
]

# ---- 12. phase 10 ----------------------------------------------------------- #
story += [
    H1("12. Phase 10 — Distribution: PyPI package and prebuilt image"),
    P("Phase 10 makes the agent installable without cloning the repo. Two "
      "distribution channels, both cut automatically by pushing a v* tag: "
      "the devopsiq package on PyPI (console command devopsiq, MIT) and a "
      "prebuilt multi-arch Docker image at "
      "ghcr.io/devopsabhii/devops-ai-agent that bundles the agent plus "
      "kubectl, helm, gh, trivy, git, curl and the docker CLI. No "
      "application code changed — packaging, licensing, containerization "
      "and CI only. The one-shot CLI surface is unchanged, so everything "
      "documented for python main.py works identically as devopsiq."),
    table(["File", "Role"], [
        ["pyproject.toml", "Package metadata: name devopsiq, version, MIT "
                           "license (PEP 639), dependencies, console "
                           "script devopsiq = main:main, shipped packages "
                           "agent/ + tools/ + main.py"],
        ["LICENSE", "MIT, Copyright (c) 2026 DevOpsAbhii"],
        ["Dockerfile", "python:3.12-slim + pinned CLIs (kubectl, helm, "
                       "trivy, gh) + app, non-root user, /data record "
                       "store"],
        [".dockerignore", "Keeps .git/.venv/.env/PDF/tests out of the "
                          "build context"],
        [".github/workflows/release.yml", "On v* tags: test gate, then "
                                          "PyPI (Trusted Publishing) and "
                                          "GHCR (multi-arch) in parallel"],
    ], [5.0 * cm, 11.5 * cm], mono_cols=(0,)),
    H2("The PyPI package (pyproject.toml)"),
    P("setuptools via PEP 621. The importable surface ships in full "
      "(agent/, tools/, main.py — level-2 library integration works from "
      "the installed package too), tests/docs stay out, and the console "
      "command runs the exact one-shot CLI:"),
    *code("pyproject.toml"),
    PageBreak(),
    H2("The Docker image (Dockerfile)"),
    P("Layers ordered for cache friendliness (apt → pip deps → pinned "
      "CLIs → app). CLIs come from their official release endpoints at "
      "ARG-pinned versions. CLIs NOT bundled (terraform, argocd, "
      "istioctl, aws/gcloud/az, ansible, systemd) are documented in the "
      "Dockerfile header — a missing CLI still fails with its exact "
      "error, so a custom layer can add just what an operator needs. "
      "Runs as non-root user agent (uid 1000) with AGENT_STORE_DIR=/data, "
      "so investigation records survive restarts via "
      "-v agent-records:/data:"),
    *code("Dockerfile", "dockerfile"),
    PageBreak(),
    H2("The release pipeline (.github/workflows/release.yml)"),
    P("Push a v* tag and three jobs run: an offline test gate first, then "
      "PyPI and GHCR in parallel. PyPI uses Trusted Publishing — the "
      "workflow proves itself to PyPI with an OIDC token, so no "
      "credential lives in the repo (registered once on pypi.org as "
      "owner DevOpsAbhii / repo devops-ai-agent / workflow release.yml / "
      "environment pypi); a PYPI_TOKEN secret remains the documented "
      "fallback. GHCR authenticates with the workflow's own GITHUB_TOKEN "
      "and builds linux/amd64 + linux/arm64 with buildx. One real-world "
      "gotcha cost the first run: a job-level permissions block replaces "
      "the workflow-level one (it does not merge), so contents: read had "
      "to be redeclared in each publish job or checkout could not see "
      "the repository:"),
    *code(".github/workflows/release.yml", "yaml"),
    PageBreak(),
    *code(".dockerignore", "config"),
    H2("Verified end to end"),
    *bullets([
        "python -m build produces the sdist and wheel; wheel contents "
        "checked (agent/, tools/, main.py) and installed into a throwaway "
        "venv — devopsiq /report then ran from an unrelated cwd, exit 0.",
        "Local docker build; docker run with a dummy key printed the "
        "no-investigation message, exited 0, showed the 58-tool banner, "
        "and runs as the non-root agent user.",
        "Full offline suite after Phase 10: 164 tests green.",
        "Live: devopsiq published on PyPI via Trusted Publishing; a fresh "
        "venv pip-installs it and runs it with no repo present; "
        "ghcr.io/devopsabhii/devops-ai-agent:0.1.0/:0.1.1 and :latest "
        "pull anonymously and are amd64+arm64 manifest lists.",
    ]),
    H2("After Phase 10 — v0.1.1: model-less mode"),
    P("The first follow-up release changed one contract: a missing (or "
      "placeholder) API key no longer blocks construction. DevOpsAgent "
      "builds with client=None and stores model_error; the chat chokepoint "
      "_complete() raises it as a normal ValueError on first use. "
      "Consequences: /report, /investigations and the other record "
      "commands work keyless in the REPL and one-shot (the REPL prints a "
      "[setup] notice and starts anyway), the 58-tool library layer needs "
      "no key at all, and an actual question still exits 1 with the same "
      "loud setup message. Maintainers get a Release & update playbook "
      "(docs/generate_release_guide.py → DevOps_Release_Guide.pdf): verify "
      "a release (Actions run, PyPI JSON, fresh-venv smoke test, anonymous "
      "GHCR manifest), the six-step change-and-tag flow, what each kind of "
      "change touches, and fixes for the failure modes hit so far."),
    *code_text("""
# keyless, verified against the published 0.1.1 package:
OPENROUTER_API_KEY= devopsiq /report      # (no investigation recorded), exit 0
OPENROUTER_API_KEY= devopsiq "why?"       # [input] OPENROUTER_API_KEY is not
                                          # set ... exit 1

# not on OpenRouter? point the same client anywhere OpenAI-compatible:
export OPENROUTER_BASE_URL=http://localhost:11434/v1
export OPENROUTER_MODEL=llama3.2          # any tool-calling Ollama model
""", cap="Model-less mode and local endpoints."),
    PageBreak(),
]

# ---- 13. safety ------------------------------------------------------------- #
story += [
    H1("13. How read-only is enforced (defense in depth)"),
    *bullets([
        "The tool schemas only allow picking names/counts/namespaces from "
        "validated arguments — there is no way to pass command text to any "
        "CLI.",
        "Every tool is a fixed argv template. No sh -c anywhere, so nothing "
        "is ever parsed by a shell; flags the model might abuse (--no-stream "
        "for docker stats, -input=false for terraform plan) are hard-coded "
        "into the template and cannot be removed or added.",
        "Only read-only verbs exist per domain — get/logs/top and config "
        "get-contexts (kubectl), status/-u/ss/ps (system), ps/inspect/logs/"
        "stats/images/network ls/volume ls/system df/compose ls/compose ps "
        "(docker), show/state list/plan (terraform), list/status/history "
        "(helm), app list/app get (argocd), proxy-status (istioctl), image "
        "--scanners vuln (trivy), status/log/diff/pr list/run list/run view/"
        "workflow list (git/gh), --list/--list-tasks (ansible), GET-only "
        "curl with a pinned argv (monitoring), query-only NerdGraph with a "
        "pinned curl (New Relic). No delete, restart, edit, apply, scale, "
        "exec, run, rm, pull, push, commit, reset, merge, use-context, "
        "playbook-run, install, upgrade, rollback, uninstall, sync, "
        "destroy — by construction.",
        "Names are validated per domain before reaching any CLI: Kubernetes "
        "object names (DNS style), systemd unit names (no /, no leading "
        "-), Docker names (no /), GitHub run ids (digits only), Ansible "
        "sources (relative paths, no ..), Helm/Argo CD names (DNS style), "
        "Trivy image refs (no leading -, no spaces), and no path parameters "
        "at all for terraform/git/gh tools. This blocks flag and path "
        "injection.",
        "New Relic credentials never come from the model: NEW_RELIC_API_KEY "
        "and NEW_RELIC_ACCOUNT_ID are environment-configured, the key is "
        "only a curl header value, the account id must be digits, and the "
        "NRQL text rides inside a json.dumps payload as a GraphQL variable.",
        "The monitoring endpoints never come from the model: they are read "
        "from PROMETHEUS_URL / LOKI_URL / GRAFANA_URL, must be http(s), and "
        "the query text is percent-encoded into the URL before curl runs.",
        "The executor re-validates every argument. Never trust the model.",
        "--request-timeout / subprocess timeouts bound slow or hanging "
        "commands; logs are tail-bounded; output truncated at 8,000 "
        "characters per result.",
        "Unrecognized tools/arguments return “Tool error: ...” to "
        "the model instead of executing.",
        "The investigation tools mutate only the agent's in-memory record.",
    ]),
    H2("The system prompt (agent/prompts.py)"),
    P("The prompt is kept in its own module so revisions never touch agent "
      "logic and it can be unit-tested / versioned independently. Its core "
      "rules: evidence before claims; distinguish facts, observations, "
      "hypotheses and conclusions; investigate before concluding; ask when "
      "information is missing; weight of destructive action (never "
      "recommend irreversible actions without understanding evidence and "
      "stating risk); be precise about uncertainty; never invent tool "
      "output; report CLI errors exactly; treat monitoring endpoints as "
      "operator-configured (name the missing env var, never invent a URL)."),
    PageBreak(),
]

# ---- 14. testing ----------------------------------------------------------- #
story += [
    H1("14. Testing"),
    P("Everything is offline: tests make no network calls and need no API "
      "key. Fake clients stand in for the model, and stub CLIs on PATH "
      "prove the exact argv the application builds. Real cluster/container "
      "verification is done live, separately."),
    table(["File", "Covers"], [
        ["tests/test_phase2.py", "Tool contract, registry, truncation, the "
                                 "tool-use loop, allowlist rejection"],
        ["tests/test_phase3.py", "kubectl argv templates, default namespace, "
                                 "verb allowlist, name validation, fake-"
                                 "kubectl loop test"],
        ["tests/test_phase4.py", "Investigation data model, meta-tool "
                                 "lifecycle and misuse, loop-driven "
                                 "investigation"],
        ["tests/test_phase5.py", "Argv templates for system/docker/tf/git "
                                 "+ gh, name validation, pinned flags"],
        ["tests/test_automation.py", "render_report_json shapes, agent "
                                     "delegates, parse_args (--model too), "
                                     "one-shot exit codes, JSON stdout "
                                     "purity, model-less mode, model-choice "
                                     "ladder (config.py, precedence, /model), "
                                     "retry classification (RetryTests)"],
        ["tests/test_phase7.py", "to_dict/from_dict round trip, store files "
                                 "and resume, chokepoint auto-save, CLI "
                                 "flags (--store-dir/--resume/--out), "
                                 "/investigations"],
        ["tests/test_phase8.py", "Argv templates for the 21 new tools, "
                                 "k8s top/hpa/pvc validation, digits-only "
                                 "gh run ids, env-configured monitoring "
                                 "endpoints, ansible path validation"],
        ["tests/test_phase9.py", "New Relic env credentials + payload "
                                 "construction (alerts ignores model args), "
                                 "trivy image-ref validation, helm/argocd/"
                                 "istio argv, compose project names, "
                                 "registry phase-9 set (58)"],
    ], [5.4 * cm, 11.1 * cm], mono_cols=(0,)),
    H2("Run the suite"),
    *code_text("""
cd ~/devops-ai-agent
source .venv/bin/activate
python -m unittest discover -s tests -v
# after the model-choice + retry work: 181 tests, OK (1 skipped as root)
""", cap="Offline tests — no network, no API key needed."),
]

# ---- 15. usage ------------------------------------------------------------- #
story += [
    H1("15. Installation and usage"),
    H2("Install — the published package or image (Phase 10)"),
    *code_text("""
pipx install devopsiq        # or: pip install devopsiq (PyPI)

docker run --rm \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v "$HOME/.kube:/home/agent/.kube:ro" \
  -v agent-records:/data \
  ghcr.io/devopsabhii/devops-ai-agent --json "check the cluster"
""", cap="Fastest — the PyPI package or the prebuilt multi-arch image."),
    P("The console command is devopsiq and behaves exactly like "
      "python main.py below. The image bundles kubectl, helm, gh, trivy, "
      "git, curl and the docker CLI; add "
      "-v /var/run/docker.sock:/var/run/docker.sock for the Docker/Compose "
      "tools. Whatever the install route, the agent still needs the CLIs "
      "of the domains you use:"),
    H2("Install — from source (development)"),
    *code_text("""
cd ~/devops-ai-agent
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env   # then edit: OPENROUTER_API_KEY=sk-or-...
""", cap="Setup — Python 3.10+, plus the CLIs of the domains you use."),
    P("Recommended CLIs, by domain: kubectl (configured context; "
      "metrics-server for top) for Kubernetes; systemctl/journalctl/ss/ps "
      "for Linux system; docker (daemon running); terraform (initialized "
      "directory); git; gh (authenticated, for PRs and Actions); aws / "
      "gcloud / az (only the ones you use); curl plus endpoint env vars for "
      "monitoring; ansible-inventory / ansible-playbook for Ansible. Each "
      "tool reports its exact error if the CLI is missing, so the agent "
      "runs with whatever subset you have."),
    H2("Model choice and model-less mode"),
    *bullets([
        "The model is set by a 4-rung ladder — the first one set wins: "
        "(1) the --model flag for a single run; (2) the /model <name> "
        "REPL command, which saves a default to "
        "~/.devops-ai-agent/config.json (agent/config.py — tolerant reads: "
        "a missing or corrupt file degrades to defaults, never a crash); "
        "(3) the OPENROUTER_MODEL env var (shell or .env); (4) the "
        "built-in default (z-ai/glm-5.3).",
        "Any model on OpenRouter works; pick a tool-caller (the agent is "
        "a tool-use loop) and mind that an investigation makes several "
        "calls per run.",
        "OPENROUTER_BASE_URL points the same client at any "
        "OpenAI-compatible endpoint — e.g. a local Ollama "
        "(http://localhost:11434/v1) for a free, offline agent.",
        "No key at all: the agent starts model-less — record commands and "
        "the tool layer work; only questions exit 1 naming "
        "OPENROUTER_API_KEY.",
    ]),
    H2("Resilient model calls (retries)"),
    *bullets([
        "Transient failures retry automatically: timeouts, connection "
        "errors, 429 rate limits, and server-side 5xx — up to 3 retries "
        "with exponential backoff (2s -> 4s -> 8s plus jitter), capped at "
        "60s.",
        "A 429's Retry-After header wins when present (clamped to "
        "1–60s) — the server knows its own budget.",
        "Client errors never retry: a rejected key (401) or any other 4xx "
        "fails immediately, because the identical request would fail "
        "identically forever. The retry lives in DevOpsAgent._call_model() "
        "around the single model-call chokepoint.",
    ]),
    H2("Run interactively (REPL)"),
    *code_text("""
.venv/bin/python main.py

# slash commands (handled locally, never reach the model):
#   /investigate <problem>   open a formal investigation
#   /investigation           show the live tracked state
#   /report                  show the canonical report (once concluded)
#   /endinvestigation        clear the record (memory only)
#   /model [<name>]          show the model, or save a default (config.json)
""", cap="REPL mode."),
    H2("Run one-shot (cron / CI / scripts)"),
    *code_text("""
.venv/bin/python main.py "why is api-5d6f crash-looping?"
.venv/bin/python main.py --json "why is api-5d6f crash-looping?"   # structured report
.venv/bin/python main.py --resume --json "any update?"             # continue prior run
.venv/bin/python main.py --store-dir /tmp/runs --out report.json "..."
.venv/bin/python main.py --model openai/gpt-5.2 "..."              # one-run model override
.venv/bin/python main.py /report                                   # slash commands work one-shot
""", cap="One-shot mode — exit 0 on success, 1 on setup/API errors."),
    H2("Persistence (Phase 7)"),
    *bullets([
        "Every record mutation auto-saves to ~/.devops-ai-agent/investigations/"
        " — one JSON file per investigation, atomically updated in place.",
        "The REPL resumes the newest in-progress record at startup; "
        "/investigations lists saved records (the live one is marked).",
        "/endinvestigation clears memory but keeps the saved file as history.",
        "One-shot: --resume continues a prior run; --out writes the JSON "
        "report to an exact path; --store-dir overrides the directory.",
        "AGENT_STORE_DIR env var overrides the default location globally.",
        "Monitoring endpoints are env-configured: PROMETHEUS_URL / "
        "LOKI_URL / GRAFANA_URL enable prom_query / loki_query / "
        "grafana_health; unset means an honest error naming the variable.",
        "A broken store degrades to a warning in the tool result — it never "
        "interrupts an investigation.",
    ]),
    H2("Example session"),
    P("With --json the stdout is one JSON document: problem, status, "
      "hypotheses, evidence, and — once concluded — conclusion with "
      "root_cause, remediation, verification, confidence. A pipeline can "
      "act on the verdict instead of parsing markdown."),
    H2("Example session"),
    *code_text("""
DevOps AI Agent (Phase 9 — 58 read-only tools, persistent investigations)
Model:   z-ai/glm-5.3
Backend: https://openrouter.ai/api/v1
Store:   /home/you/.devops-ai-agent/investigations
Tools:   docker_images, docker_inspect, docker_logs, docker_ps, ...

You: The checkout service container keeps exiting in Docker. Investigate.
Agent: (docker_ps -> docker_inspect -> docker_logs, tracks hypotheses, and
       ends with the structured report: the crash command, exit code, and
       the remediation recommendation)

You: /report
Agent: # Investigation report ... (the canonical record, rendered from state)

You: exit
""", cap="A Docker investigation, start to finish."),
    PageBreak(),
]

# ---- 16. limitations & roadmap ---------------------------------------------- #
story += [
    H1("16. Current limitations"),
    *bullets([
        "Each domain needs its CLI installed and reachable; missing CLIs, "
        "unauthenticated gh, a dead docker daemon, an uninitialized "
        "terraform directory or an unreachable cluster return the exact "
        "error honestly — but a tool can't produce data without its backend.",
        "The prebuilt Docker image bundles kubectl, helm, trivy, gh, git, "
        "curl and the docker CLI only; terraform, argocd, istioctl, "
        "aws/gcloud/az, ansible and systemd-backed system tools need your "
        "own image layer (documented in the Dockerfile header) or a "
        "non-container host.",
        "terraform/git/gh/ansible tools are working-directory scoped (no "
        "path arguments by design — keeps traversal out). To investigate "
        "another repo/module, launch the agent there.",
        "Monitoring endpoints are environment-configured by design: without "
        "PROMETHEUS_URL / LOKI_URL / GRAFANA_URL set, those tools fail with "
        "a message naming the variable — the agent never invents a URL.",
        "kubectl top needs metrics-server; clusters without it return "
        "kubectl's exact error — honest, but no usage data.",
        "Cloud tools are identity-level only: which account/principal/"
        "subscription am I looking at — region-scoped resource sweeps "
        "(ec2 describe-*, compute instances list, ...) are not integrated "
        "yet.",
        "The model can only select from the registered tools; it can never "
        "run an arbitrary or mutating verb — by construction.",
        "Raw CLI output goes to the model (Python does not re-parse), "
        "truncated at 8,000 characters per result.",
        "Short-term conversation memory only: chat history lives in the "
        "process and is lost when the CLI exits (the investigation record "
        "itself persists — Phase 7).",
        "Hypothesis tracking is model-driven: the record is what the model "
        "chose to record through the investigation tools.",
        "No streaming yet (retries with exponential backoff are in).",
        "Read-only is enforced by construction today; mutating capabilities "
        "will only be added behind an explicit human-approval gate, much "
        "later.",
    ]),
    H1("17. Roadmap"),
    table(["Phase", "Scope"], [
        ["Phase 8", "Tool expansion (done): 21 more read-only tools (26 → "
                    "47) — k8s depth, Docker depth, GitHub Actions, cloud "
                    "identity, monitoring (env-configured), Ansible "
                    "listing."],
        ["Phase 9", "Trending-market tools (done): 11 more read-only tools "
                    "(47 → 58) — New Relic (env-credentialed NerdGraph), "
                    "Trivy, Helm, Argo CD, Istio, Docker Compose."],
        ["Phase 10", "Distribution (done): the devopsiq package on PyPI "
                     "and the prebuilt multi-arch GHCR image, cut by a "
                     "tag-driven release workflow (test gate, Trusted "
                     "Publishing)."],
        ["Post-10", "Model choice + resilient calls (done): a 4-rung model "
                    "ladder (--model flag > /model-saved config.json > "
                    "OPENROUTER_MODEL > default) and bounded retries with "
                    "exponential backoff on transient model-call failures "
                    "(timeouts, connection errors, 429, 5xx)."],
        ["Later", "Region-scoped cloud resources (ec2 describe-*, compute "
                  "instances list, ...) behind the same template pattern; "
                  "streaming; conversation-history persistence; "
                  "human-approval gate before any mutating "
                  "action is ever allowed."],
    ], [3.4 * cm, 13.1 * cm]),
    H2("Repository hygiene"),
    P("Phase 6 also git-tracked the project. .gitignore keeps secrets and "
      "the venv out:"),
    *code(".gitignore", "config"),
    Spacer(1, 0.4 * cm),
    Paragraph("Documentation generated from the repository source on " + TODAY
              + " — regenerate any time by re-running the generator against "
              "the latest code.", S["cap"]),
]

# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
doc = Doc(OUT, pagesize=A4,
          leftMargin=2 * cm, rightMargin=2 * cm,
          topMargin=2 * cm, bottomMargin=2 * cm,
          title="DevOps AI Agent — Project Documentation",
          author="DevOpsAbhii")
frame = Frame(doc.leftMargin, doc.bottomMargin,
              doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
doc.multiBuild(story)
print("WROTE", OUT)
