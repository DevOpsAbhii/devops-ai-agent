"""Tool registry: the single place tools are declared and executed.

Tools self-register by calling `register(tool)` at import time (see
tools/preflight.py). The agent pulls the full list with `get_tools()` and
executes model-requested calls through `execute_tool()`, which never raises:
every failure is converted into an error string the model can read and adapt
to, keeping the conversation loop alive.
"""

import json

from tools.base import Tool, ToolError

_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    if tool.name in _TOOLS:
        raise ValueError(f"a tool named {tool.name!r} is already registered")
    _TOOLS[tool.name] = tool


def get_tools() -> list[Tool]:
    return list(_TOOLS.values())


def execute_tool(name: str, arguments: str) -> str:
    """Execute one tool call and return the text to feed back to the model.

    Never raises. Failures (unknown tool, unparseable arguments, executor
    errors) are returned as "Tool error: ..." strings so the model can read
    them, apologize, or re-request with valid arguments.
    """
    tool = _TOOLS.get(name)
    if tool is None:
        known = ", ".join(sorted(_TOOLS)) or "none"
        return f"Tool error: unknown tool {name!r}. Available tools: {known}."

    try:
        args = json.loads(arguments) if arguments and arguments.strip() else {}
        if not isinstance(args, dict):
            raise TypeError("tool arguments must be a JSON object")
        return tool.executor(args)
    except json.JSONDecodeError as exc:
        return f"Tool error: could not parse arguments JSON: {exc}"
    except ToolError as exc:
        return f"Tool error: {exc}"
    except Exception as exc:  # noqa: BLE001 - last resort; keep the loop alive
        return f"Tool error: {type(exc).__name__}: {exc}"