"""Per-user preferences: ~/.devops-ai-agent/config.json.

The `devopsiq` equivalent of "my settings" — currently the preferred model,
written by the /model command and read by the agent at startup. Precedence
for the model, highest first:

    --model flag  >  config.json  >  OPENROUTER_MODEL env  >  built-in default

The file is tiny JSON, one flat object. Every read is tolerant: a missing
file, an unreadable home directory, or corrupt content yields {} — a broken
config never blocks the agent (the same degrade-don't-crash rule the
investigation store follows). Tests point AGENT_CONFIG_FILE at a tmp path.
"""

import json
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".devops-ai-agent" / "config.json"


def config_path() -> Path:
    """The active config file (AGENT_CONFIG_FILE overrides; tests use tmp)."""
    return Path(os.getenv("AGENT_CONFIG_FILE") or DEFAULT_CONFIG_PATH)


def load_user_config() -> dict:
    """Read the config file; {} when missing or unreadable — never raise."""
    try:
        raw = config_path().read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_config(update: dict) -> Path:
    """Merge `update` into the config file (create the directory if needed)."""
    path = config_path()
    data = load_user_config()
    data.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
