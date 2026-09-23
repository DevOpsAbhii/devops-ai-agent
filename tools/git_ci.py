"""Read-only git / CI tools (Phase 5).

Four tools for code-and-pipeline problems: repository status (git status),
recent history (git log), working-tree diff summary (git diff), and open pull
requests via the GitHub CLI (gh pr list). Operating on the CURRENT WORKING
DIRECTORY the agent was launched from (like terraform).

Safety model:
- Only `git status --short --branch`, `git log --oneline -n`, `git diff
  --stat HEAD` and `gh pr list --limit --json` exist. No git reset,
  checkout/switch, commit, push, pull, clean, or stash; no gh pr create/
  merge/close, no gh workflow run.
- No free-form args: neither git nor gh ever receives user-supplied text
  beyond bounded integers, so flag/dispatch injection is impossible.
- git and gh must be installed; gh additionally needs authentication and to
  be inside a GitHub repository. Missing pieces surface as the exact CLI
  error — never invented.
"""

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

_TIMEOUT_S = 10


def _checked_count(args: dict, key: str, default: int, maximum: int, label: str) -> int:
    try:
        count = int(args.get(key, default))
    except (TypeError, ValueError):
        raise ToolError(f"{label} must be an integer between 1 and {maximum}")
    if not 1 <= count <= maximum:
        raise ToolError(f"{label} must be between 1 and {maximum}")
    return count


def _git_repo_status(args: dict) -> str:
    return read_command_output(("git", "status", "--short", "--branch"), timeout=_TIMEOUT_S)


def _git_log(args: dict) -> str:
    count = _checked_count(args, "count", 20, 100, "count")
    return read_command_output(
        ("git", "log", "--oneline", "-n", str(count)), timeout=_TIMEOUT_S
    )


def _git_diff(args: dict) -> str:
    return read_command_output(("git", "diff", "--stat", "HEAD"), timeout=_TIMEOUT_S)


def _gh_prs(args: dict) -> str:
    count = _checked_count(args, "limit", 10, 50, "limit")
    return read_command_output(
        (
            "gh", "pr", "list", "--limit", str(count),
            "--json", "number,title,state,headRefName,isDraft,updatedAt",
        ),
        timeout=_TIMEOUT_S,
    )


GIT_REPO_STATUS = Tool(
    name="git_repo_status",
    description=(
        "Repository status of the current working directory (git status "
        "--short --branch): current branch, ahead/behind, and modified/"
        "staged/untracked files. Use for 'have local changes been applied', "
        "unclean trees before a deploy. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_git_repo_status,
)

GIT_LOG = Tool(
    name="git_log",
    description=(
        "Recent commit history of the current working directory "
        "(git log --oneline -n): short hash + subject per commit. Use to see "
        "what changed recently or whether a fix was committed. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 20,
                "description": "How many commits to show (1–100).",
            }
        },
        "additionalProperties": False,
    },
    executor=_git_log,
)

GIT_DIFF = Tool(
    name="git_diff",
    description=(
        "Summary of working-tree changes vs HEAD in the current working "
        "directory (git diff --stat HEAD): files changed plus insertions/"
        "deletions. Use to judge the size/impact of uncommitted changes. "
        "Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_git_diff,
)

GH_PRS = Tool(
    name="gh_prs",
    description=(
        "List open pull requests of the current GitHub repository as JSON "
        "(gh pr list): number, title, state, head branch, draft flag, updated "
        "time. Use for 'what is waiting to merge', CI/CD pull-request state. "
        "Requires the gh CLI installed, authenticated, and a repository with "
        "a GitHub remote. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 10,
                "description": "How many PRs to list (1–50).",
            }
        },
        "additionalProperties": False,
    },
    executor=_gh_prs,
)

register(GIT_REPO_STATUS)
register(GIT_LOG)
register(GIT_DIFF)
register(GH_PRS)