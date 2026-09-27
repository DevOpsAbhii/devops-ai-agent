# Changelog

All notable changes to this project are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/). Each version is published
automatically when its `vX.Y.Z` tag is pushed (see
`.github/workflows/release.yml`): PyPI + a multi-arch Docker image.

## [0.1.3] — 2026-09-27

### Changed
- Documentation only: feedback-only GitHub issue templates, release
  playbook updated (github-release job, v0.1.2→0.1.3 flow), INTEGRATION.md
  documents `--model`, `AGENT_CONFIG_FILE`, and the retry behavior.
  No code changes.

## [0.1.2] — 2026-09-26

### Added
- **Model choice ladder**: the model is now set by precedence — `--model`
  flag (one run) > `~/.devops-ai-agent/config.json` (saved via the new
  `/model <name>` REPL command) > `OPENROUTER_MODEL` env > built-in
  default. `/model` alone shows the active model and the config path.
  New `agent/config.py` reads the config file tolerantly (missing or
  corrupt → defaults, never a crash); `AGENT_CONFIG_FILE` overrides the
  path for tests.
- **Retries on transient model failures**: timeouts, connection errors,
  429 rate limits, and server-side 5xx are retried up to 3 times with
  exponential backoff (2s → 4s → 8s + jitter); a 429's `Retry-After`
  header wins when present (clamped 1–60s). A rejected key (401) and
  other client 4xx fail immediately — retrying cannot fix them. The retry
  lives in `DevOpsAgent._call_model()` around the single model-call
  chokepoint; no other behavior changed.
- Tests: `ModelChoiceTests` (4) and `RetryTests` (8) — config round-trip,
  precedence ladder, `/model` show/save, `--model` parsing, and offline
  retry classification (connection errors retried then succeed, 429
  honors Retry-After, 401/400 fail fast, retries exhaust loudly).
  Suite: 169 → 181, green.

### Changed
- README: model-precedence section, `/model` in the command table, one-shot
  examples, roadmap entry marked done; tests badge 169 → 181.

## [0.1.1] — 2026-09-26

### Added
- **Model-less mode**: the agent no longer requires an API key to start.
  Record commands (`/report`, `/investigations`, `/investigate`) and the
  entire 58-tool layer work with no key configured; only model questions
  exit 1 with the setup message. The REPL starts keyless with a `[setup]`
  notice. (`DevOpsAgent` builds with `client=None` and surfaces the error
  lazily at the single chat chokepoint.)
- **Model choice documented**: `OPENROUTER_MODEL` accepts any OpenRouter
  model; `OPENROUTER_BASE_URL` points the same client at any
  OpenAI-compatible endpoint — including a local Ollama for a free,
  offline agent.
- Tests: `KeylessTests` (5) — construction without a key, placeholder-key
  laziness, loud question failure, keyless one-shot slash command,
  keyless question exit 1. Suite: 164 → 169, green.

### Changed
- README: "Your model, your choice" and "No API key?" sections;
  limitations/roadmap refreshed.

## [0.1.0] — 2026-09-26

First published release. The complete project through Phase 10:

### Added
- **Agent core (Phases 1–4)**: OpenRouter-backed conversation with GLM 5.3
  (`z-ai/glm-5.3`), a hand-rolled tool-use loop (`_complete()` as the
  single model-call chokepoint), and a first-class investigation record —
  hypotheses, evidence, verdicts, structured report with root cause,
  remediation, verification, confidence.
- **58 read-only tools across 15 domains (Phases 2, 5, 8, 9)**: host
  facts, Kubernetes (12), Linux system (4), Docker + Compose (10),
  Terraform (3), Helm (3), Argo CD (2), Istio (1), Trivy (1), git/GitHub +
  Actions (7), cloud identity (4), monitoring (3), New Relic (2),
  Ansible (2), plus 3 investigation meta-tools. Read-only by
  construction: fixed argv templates, per-domain name validation, no
  shell, pinned flags, 8,000-char output truncation.
- **Automation surface (Phases 6–7)**: one-shot CLI with exit codes,
  structured `--json` export (`--out`, `--store-dir`, `--resume`),
  persistent investigation records (auto-save, atomic writes, REPL
  auto-resume).
- **Distribution (Phase 10)**: the `devopsiq` package on PyPI (console
  command `devopsiq`, MIT) and the prebuilt multi-arch GHCR image
  (`ghcr.io/devopsabhii/devops-ai-agent`), cut by a tag-driven release
  workflow with an offline test gate and PyPI Trusted Publishing.
- **Offline test suite**: 164 tests, no network, no API key; stub CLIs
  prove exact argv construction.
