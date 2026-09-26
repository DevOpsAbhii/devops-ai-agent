#!/usr/bin/env python3
"""Generate the DevOps AI Agent release & update playbook PDF.

A maintainer-facing cheat sheet: how to verify a release landed, and the
exact step-by-step flow to change something and ship it. Regenerate any
time:

    .venv/bin/python docs/generate_release_guide.py
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
OUT = os.path.join(ROOT, "DevOps_Release_Guide.pdf")

INK = colors.HexColor("#1a2332")
ACCENT = colors.HexColor("#2563eb")
ACCENT_SOFT = colors.HexColor("#dbeafe")
CODE_BG = colors.HexColor("#f4f5f7")
CODE_BORDER = colors.HexColor("#d8dbe0")
MUTED = colors.HexColor("#5b6472")
RULE = colors.HexColor("#c9ced6")
GOOD = colors.HexColor("#0f766e")

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
                    "DevOps AI Agent — Release & update playbook")
    canv.setFont("Helvetica-Bold", 8.5)
    canv.setFillColor(ACCENT)
    canv.drawCentredString(A4[0] / 2, 1.05 * cm, "Page %d" % doc.page)
    canv.restoreState()


story = []
TODAY = datetime.date.today().strftime("%d %B %Y")

# ---- cover ----------------------------------------------------------------- #
story += [
    Spacer(1, 6.0 * cm),
    Paragraph("Release &amp; update playbook", S["cover_title"]),
    Spacer(1, 0.7 * cm),
    Paragraph("devopsiq — verify a release, change something, ship it again",
              S["cover_sub"]),
    Spacer(1, 1.6 * cm),
    table(["", ""], [
        ["Project", "devops-ai-agent  (~/devops-ai-agent)"],
        ["Package", "devopsiq  (PyPI)  ·  ghcr.io/devopsabhii/devops-ai-agent"],
        ["Trigger", "push a tag:  git tag vX.Y.Z && git push origin vX.Y.Z"],
        ["Pipeline", "test → PyPI (Trusted Publishing) + GHCR (multi-arch)"],
        ["Generated", TODAY],
    ], [3.6 * cm, 12.9 * cm]),
    PageBreak(),
]

# ---- 1. what a release is -------------------------------------------------- #
story += [
    H1("1. What a release is in this project"),
    P("A release is one git tag. Nothing else — no buttons, no manual "
      "uploads. Pushing a tag named v* triggers .github/workflows/"
      "release.yml, which runs three GitHub Actions jobs in order:"),
    *bullets([
        "test — checks out the tag, installs requirements, runs the full "
        "offline suite (python -m unittest discover -s tests). Nothing "
        "publishes unless this passes.",
        "pypi — builds the sdist + wheel from pyproject.toml and publishes "
        "to PyPI via Trusted Publishing (OIDC; no token stored in the "
        "repo). One-time setup on pypi.org, already done.",
        "docker — builds the image for linux/amd64 and linux/arm64 with "
        "buildx and pushes ghcr.io/devopsabhii/devops-ai-agent:<version> "
        "and :latest (GITHUB_TOKEN; no setup needed).",
    ]),
    P("The version it publishes comes from one place: the version = field "
      "in pyproject.toml. The tag name and the pyproject version must "
      "match (v0.1.1 ↔ 0.1.1) — CI does not check this for you, so it is "
      "step 5 below."),
    PageBreak(),
]

# ---- 2. verifying ----------------------------------------------------------- #
story += [
    H1("2. How to verify a release is done"),
    P("Four checks, in the order you should run them. All commands assume "
      "the repo checkout at ~/devops-ai-agent."),
    H2("2.1 The workflow run (GitHub Actions)"),
    *code_text("""
# list the recent release runs (newest first)
gh run list --workflow=release.yml --limit 3
#   → expect a row:  completed  success  <commit message>  Release  vX.Y.Z

# live-watch the run for the tag you just pushed
gh run watch <run-id> --exit-status

# job-by-job detail (all three must be success)
gh run view <run-id> --json status,conclusion,jobs \\
  --jq '{conclusion, jobs: [.jobs[] | {name, conclusion}]}'
""", cap="Expect: conclusion success, jobs test / pypi / docker all success."),
    H2("2.2 PyPI — is the new version published?"),
    *code_text("""
# the authoritative machine-readable check:
curl -s https://pypi.org/pypi/devopsiq/json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('latest:', d['info']['version'])          # → 0.1.1
print('all:   ', sorted(d['releases'].keys()))  # → ['0.1.0', '0.1.1']
"

# or just open:  https://pypi.org/project/devopsiq/
""", cap="If it still shows the old version, wait 2–5 minutes: the PyPI CDN caches."),
    H2("2.3 Install it fresh and smoke-test"),
    *code_text("""
python3 -m venv /tmp/smoke-$$ && /tmp/smoke-$$/bin/pip install \\
  --no-cache-dir devopsiq==X.Y.Z
/tmp/smoke-$$/bin/pip show devopsiq | grep Version   # → X.Y.Z

# keyless path — record commands must work with no key:
cd /tmp && OPENROUTER_API_KEY= /tmp/smoke-$$/bin/devopsiq /report
#   → "(no investigation recorded)", exit 0

# question path without a key must fail LOUD, exit 1:
OPENROUTER_API_KEY= /tmp/smoke-$$/bin/devopsiq "why is it down?"

# full path with a real key:
OPENROUTER_API_KEY=sk-or-... /tmp/smoke-$$/bin/devopsiq \\
  --json "docker container checkout keeps exiting, investigate"
""", cap="--no-cache-dir matters: pip otherwise reuses a stale cached wheel."),
    H2("2.4 GHCR — image tags and architectures"),
    *code_text("""
# anonymous manifest check (works because the package is public):
tok=$(curl -s "https://ghcr.io/token?scope=repository:devopsabhii/devops-ai-agent:pull" \\
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $tok" \\
  -H "Accept: application/vnd.oci.image.index.v1+json" \\
  "https://ghcr.io/v2/devopsabhii/devops-ai-agent/manifests/X.Y.Z" \\
  | python3 -c "import json,sys; m=json.load(sys.stdin); \\
print([x['platform']['architecture'] for x in m['manifests']])"
#   → ['amd64', 'arm64', 'unknown', 'unknown']   (unknown = attestations, normal)

# or the practical check — pull it:
docker pull ghcr.io/devopsabhii/devops-ai-agent:X.Y.Z
""", cap="Or browse: https://github.com/DevOpsAbhii?tab=packages."),
    PageBreak(),
]

# ---- 3. the release flow ----------------------------------------------------- #
story += [
    H1("3. Change something and release it — step by step"),
    P("The whole loop, from edit to verified release. Version numbers below "
      "assume the current release is 0.1.1 and the next one is 0.1.2 — "
      "bump the patch digit for fixes, the minor digit for features."),
    H2("Step 1 — make your change"),
    *code_text("""
cd ~/devops-ai-agent
# edit the files (see section 4 for what a given change usually touches)
git status          # review what you touched
git diff            # review the actual edits
""", cap="No staging tricks: add exactly the files you meant to change."),
    H2("Step 2 — run the tests (the same gate CI will run)"),
    *code_text("""
.venv/bin/python -m unittest discover -s tests
#   → "Ran 169 tests ... OK"   (1 skip is expected when running as root)

# if you added behavior, add tests next to the existing pattern first:
#   tests/test_phaseN.py / tests/test_automation.py — offline, stub CLIs
""", cap="Never tag red: if the suite fails, CI's test job will fail too and nothing publishes."),
    H2("Step 3 — commit and push to main"),
    *code_text("""
git add <files>
git commit -m "Short summary of the change"
git push
""", cap="Write commit messages for future-you: what changed and why."),
    H2("Step 4 — bump the version in pyproject.toml"),
    *code_text("""
sed -i 's/^version = "0.1.1"/version = "0.1.2"/' pyproject.toml
grep -n '^version' pyproject.toml     # confirm: version = "0.1.2"

git add pyproject.toml
git commit -m "Bump version to 0.1.2 for release"
git push
""", cap="Tag name and this version must agree: tag v0.1.2 ↔ version 0.1.2."),
    H2("Step 5 — tag and push the tag (this triggers the release)"),
    *code_text("""
git tag v0.1.2
git push origin v0.1.2
""", cap="Pushing the tag is the release button. Nothing publishes without it."),
    H2("Step 6 — watch the run, then verify (section 2)"),
    *code_text("""
gh run list --workflow=release.yml --limit 1     # note the run id
gh run watch <run-id> --exit-status              # waits until done

# then, when all three jobs are success:
#   2.2 PyPI JSON shows the new version   (allow 2–5 min CDN lag)
#   2.3 fresh venv smoke test
#   2.4 GHCR manifest shows the new tag + amd64/arm64
""", cap="PyPI and GHCR publish in parallel after the test gate — GHCR usually lands first."),
    PageBreak(),
]

# ---- 4. what to touch -------------------------------------------------------- #
story += [
    H1("4. What a given change touches"),
    table(["You changed…", "Files", "Also update before tagging"], [
        ["Nothing user-facing (docs, comments)",
         "README.md, docs/", "Nothing — docs don't need a release. "
         "Regenerate the PDFs locally if wanted."],
        ["Agent behavior (loop, prompts, model-less mode)",
         "agent/agent.py, agent/prompts.py",
         "tests (tests/test_automation.py or phase tests), README "
         "section 3/4/7 if user-visible"],
        ["A tool (new one or behavior)",
         "tools/<domain>.py (self-registers at import)",
         "tests for its argv/validation, README tool catalogue rows, "
         "docs/generate_pdf.py section"],
        ["CLI surface (flags, slash commands)",
         "main.py",
         "tests/test_automation.py, README section 7, INTEGRATION.md "
         "contract table"],
        ["Dependencies",
         "requirements.txt AND pyproject.toml (keep both in sync)",
         "Run the suite; consider whether the image needs it too"],
        ["Docker image contents (bundled CLIs)",
         "Dockerfile (ARG versions), maybe .dockerignore",
         "Rebuild locally first: docker build -t devops-ai-agent:local . "
         "and run the offline /report check"],
        ["Release pipeline itself",
         ".github/workflows/release.yml",
         "Watch the FIRST run closely — a broken workflow fails visibly "
         "on the next tag (e.g. the job-permissions lesson: job-level "
         "permissions replace, not merge)"],
    ], [4.3 * cm, 4.6 * cm, 7.6 * cm], mono_cols=(1,)),
    P("Regenerating the local documentation PDFs (never blocks a release; "
      "the PDFs are gitignored artifacts built from the tracked "
      "generators):"),
    *code_text("""
.venv/bin/python docs/generate_pdf.py             # full project docs
.venv/bin/python docs/generate_release_guide.py   # this playbook
""", cap="Both read live source — always current with the working tree."),
    PageBreak(),
]

# ---- 5. when things go wrong -------------------------------------------------- #
story += [
    H1("5. When something goes wrong"),
    table(["Symptom", "Cause", "Fix"], [
        ["PyPI job red: “file already exists” / version conflict",
         "The version was already published (PyPI is immutable — a "
         "version can never be re-uploaded, even to fix content)",
         "Delete the tag, bump the version, re-tag: "
         "git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z, then "
         "bump pyproject to X.Y+1.Z and tag again"],
        ["pypi and docker jobs red at checkout: “repository not found”",
         "A job-level permissions block dropped contents: read "
         "(job permissions replace, not merge)",
         "Already fixed in the workflow — if it regresses, re-add "
         "contents: read next to id-token: write / packages: write"],
        ["PyPI JSON shows the old version minutes after a green run",
         "PyPI CDN cache",
         "Wait 2–5 minutes; the publish is already done"],
        ["Fresh install shows the old version",
         "pip's local HTTP cache",
         "pip install --no-cache-dir --upgrade devopsiq==X.Y.Z"],
        ["Need to move a tag (wrong commit), without re-running the "
         "release",
         "Re-pushing a tag re-triggers the workflow",
         "gh workflow disable release.yml → git push --force origin "
         "vX.Y.Z → gh workflow enable release.yml"],
        ["Only the docker job failed",
         "Transient registry/build issue",
         "Re-run just that job in the Actions UI (Re-run failed jobs)"],
        ["Red X on an old release run you want to ignore",
         "Historical failed run",
         "Nothing to do — only the newest tag's artifacts matter"],
    ], [4.6 * cm, 5.4 * cm, 6.5 * cm]),
    H2("The complete cheat sheet"),
    *code_text("""
# ---- change → release → verify, end to end ----
cd ~/devops-ai-agent
# ...edit files...
.venv/bin/python -m unittest discover -s tests        # green first
git add <files> && git commit -m "the change" && git push
sed -i 's/^version = "0.1.1"/version = "0.1.2"/' pyproject.toml
git add pyproject.toml && git commit -m "Bump version to 0.1.2" && git push
git tag v0.1.2 && git push origin v0.1.2              # ← the release button
gh run watch $(gh run list --workflow=release.yml --limit 1 -q '.[0].databaseId') \\
  --exit-status
curl -s https://pypi.org/pypi/devopsiq/json | grep -o '"0.1.2"'
docker pull ghcr.io/devopsabhii/devops-ai-agent:0.1.2
""", cap="Everything above, condensed to eight lines."),
    Spacer(1, 0.4 * cm),
    Paragraph("Release & update playbook — generated from the repository on "
              + TODAY + ". Regenerate: .venv/bin/python "
              "docs/generate_release_guide.py", S["cap"]),
]

doc = Doc(OUT, pagesize=A4,
          leftMargin=2 * cm, rightMargin=2 * cm,
          topMargin=2 * cm, bottomMargin=2 * cm,
          title="DevOps AI Agent — Release & update playbook",
          author="DevOpsAbhii")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
              id="main")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
doc.build(story)
print("WROTE", OUT)
