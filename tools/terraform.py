"""Read-only Terraform tools (Phase 5).

Three tools for infrastructure-as-code problems: what the current state holds
(terraform state list), what a plan would change (terraform plan), and a
human-readable render of the state (terraform show). All operate on the
current working directory the agent was launched from.

Safety model:
- Only `show`, `state list`, and `plan` exist. There is no apply, destroy,
  import, force-unlock, refresh (mutating), workspace delete, or taint.
- `plan` is a dry run: it computes the diff but changes nothing. Pinned to
  `-input=false` so it can never sit waiting on a prompt, and `-no-color`
  keeps output model-readable.
- A generous timeout (60s for plan — providers may need to fetch schemas)
  bounds slow modules.
- terraform must be installed and the directory must be initialized
  (`terraform init`). If not, the exact error is returned — nothing is
  invented. On a fresh directory the model sees terraform's own
  "Please run 'terraform init'" and must report it, not fabricate state.
"""

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Plan can take much longer than the default 10s on a real module (provider
# schema downloads); everything else stays snappy.
_PLAN_TIMEOUT_S = 60
_OTHER_TIMEOUT_S = 15


def _tf_show(args: dict) -> str:
    return read_command_output(
        ("terraform", "show", "-no-color"), timeout=_OTHER_TIMEOUT_S
    )


def _tf_state_list(args: dict) -> str:
    return read_command_output(
        ("terraform", "state", "list"), timeout=_OTHER_TIMEOUT_S
    )


def _tf_plan(args: dict) -> str:
    return read_command_output(
        ("terraform", "plan", "-no-color", "-input=false"),
        timeout=_PLAN_TIMEOUT_S,
    )


TF_SHOW = Tool(
    name="tf_show",
    description=(
        "Render the current Terraform state of the working directory "
        "(terraform show): resources with their attribute values as stored. "
        "Use to see what IaC currently believes exists. Requires an "
        "initialized directory. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_tf_show,
)

TF_STATE_LIST = Tool(
    name="tf_state_list",
    description=(
        "List every resource address in the Terraform state of the working "
        "directory (terraform state list), e.g. aws_instance.web. Use to see "
        "what infrastructure is tracked and spot drift from config. "
        "Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_tf_state_list,
)

TF_PLAN = Tool(
    name="tf_plan",
    description=(
        "Dry-run Terraform plan for the working directory "
        "(terraform plan -no-color -input=false): prints what would be "
        "added/changed/destroyed — WITHOUT changing anything. Use to assess "
        "the impact of local config changes or detect drift. Requires an "
        "initialized directory. Read-only; may take up to 60s on large "
        "modules."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_tf_plan,
)

register(TF_SHOW)
register(TF_STATE_LIST)
register(TF_PLAN)