"""Read-only cloud-account tools (Phase 8).

Identity and listing probes for the three major cloud CLIs: who am I / which
account is active (aws sts get-caller-identity, gcloud config list, az account
show) and a first-level resource listing (az group list). These answer "which
cloud account am I even looking at" — usually the first question when an
incident report and the infrastructure disagree.

Safety model:
- Only fixed argv templates with read-only verbs exist. There is no create,
  delete, update, start, stop, tag, or IAM-mutation path, and no
  user-supplied argument anywhere: neither AWS, gcloud nor az ever receives
  model-chosen text, so flag/dispatch injection is impossible.
- `aws sts get-caller-identity` needs no region; listing tools are kept to
  account/subscription level on purpose — region-scoped resource sweeps
  (ec2 describe-*, compute instances list ...) can be added later behind the
  same template pattern.
- The CLIs must be installed and configured (aws credentials, gcloud/az
  logins). Missing pieces surface as the exact CLI error — never invented.
- Cloud CLIs are slow on a cold start (helper processes, token refresh), so
  the subprocess timeout is 30s rather than the usual 10s.
"""

from tools.base import Tool, read_command_output
from tools.registry import register

_TIMEOUT_S = 30


def _aws_identity(args: dict) -> str:
    return read_command_output(
        ("aws", "sts", "get-caller-identity", "--output", "json"),
        timeout=_TIMEOUT_S,
    )


def _gcloud_identity(args: dict) -> str:
    return read_command_output(
        ("gcloud", "config", "list", "--format=json"),
        timeout=_TIMEOUT_S,
    )


def _az_account(args: dict) -> str:
    return read_command_output(("az", "account", "show"), timeout=_TIMEOUT_S)


def _az_groups(args: dict) -> str:
    return read_command_output(("az", "group", "list"), timeout=_TIMEOUT_S)


AWS_IDENTITY = Tool(
    name="aws_identity",
    description=(
        "AWS caller identity as JSON (aws sts get-caller-identity): account "
        "id, user/role ARN. Use to answer 'which AWS account and principal "
        "are the configured credentials for'. Requires aws CLI with working "
        "credentials. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_aws_identity,
)

GCLOUD_IDENTITY = Tool(
    name="gcloud_identity",
    description=(
        "Active gcloud configuration as JSON (gcloud config list): account, "
        "project, region, zone. Use to answer 'which GCP project/region is "
        "this host pointed at'. Requires the gcloud CLI. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_gcloud_identity,
)

AZ_ACCOUNT = Tool(
    name="az_account",
    description=(
        "The active Azure subscription as JSON (az account show): id, name, "
        "state, tenant. Use to answer 'which Azure subscription am I looking "
        "at'. Requires the az CLI and a logged-in account. Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_az_account,
)

AZ_GROUPS = Tool(
    name="az_groups",
    description=(
        "List Azure resource groups in the active subscription as JSON (az "
        "group list): name, location, tags. Use to see the top-level layout "
        "of an Azure subscription during an investigation. Requires az CLI. "
        "Read-only."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    executor=_az_groups,
)

register(AWS_IDENTITY)
register(GCLOUD_IDENTITY)
register(AZ_ACCOUNT)
register(AZ_GROUPS)
