"""Read-only region-scoped cloud resource tools (Phase 13).

The Phase 8 cloud tools answer "which account am I even looking at"; these
answer the next question an incident raises: "what actually runs in this
region" — compute instances, their sizes and states — across the three
major clouds:

    AWS     aws ec2 describe-instances          (instance id, type, state, private IP)
    GCP     gcloud compute instances list      (name, zone, machine type, status)
    Azure   az vm list                         (name, location, power state via -d)

Safety model — identical to the Phase 8 identity tools:
- Fixed argv templates only. The model never supplies command text; the
  only model-chosen values are a region / zone / group *name* passed as the
  value of a dedicated flag, and names are validated before use (see
  _validate_name) so flag-value injection ("--output text; rm -rf /") is
  impossible: subprocess runs argv directly, and a validated name can only
  appear as a flag's value, never as a new flag.
- Read-only verbs only: describe-*, list, show. No create/start/stop/
  terminate/delete/tag/patch anywhere in the module.
- Output is JSON (parsed server-side by the model as usual); truncated to
  the standard 8k like every tool result.
- The CLIs must be installed and configured; missing pieces surface as the
  exact CLI error — never invented.
- Cloud CLIs are slow on cold start (Phase 8 note), so subprocess timeout
  is 30s.
"""

from __future__ import annotations

import re

from tools.base import Tool, read_command_output
from tools.registry import register

_TIMEOUT_S = 30

# What a valid region/zone/resource-group name can look like across the
# three clouds (lowercase alphanumerics and dashes, GCP zones have a
# single dash-numbered suffix; AWS regions may carry a gov/iso partition
# prefix, e.g. us-gov-west-1, cn-north-1). If it does not match, the tool
# refuses before any CLI is invoked.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


def _validate_name(name: str, kind: str) -> str:
    """Reject anything that is not a plain cloud resource name.

    The value is only ever emitted as the *value* of --region/--zone/-g,
    but validating keeps the allowlist honest: a name with spaces, equals
    signs or leading dashes can never reach the subprocess.
    """
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid {kind} name: {name!r} — expected lowercase "
            "alphanumerics and dashes (e.g. us-east-1, europe-west1b)"
        )
    return name


# --- executors ---------------------------------------------------------------

def _aws_instances(args: dict) -> str:
    region = _validate_name(args.get("region", ""), "region")
    return read_command_output(
        (
            "aws", "ec2", "describe-instances",
            "--region", region,
            "--query",
            "Reservations[].Instances[].{id:InstanceId,type:InstanceType,"
            "state:State.Name,az:Placement.AvailabilityZone,"
            "private_ip:PrivateIpAddress,name:Tags[?Key=='Name']|[0].Value}",
            "--output", "json",
        ),
        timeout=_TIMEOUT_S,
    )


def _gcloud_instances(args: dict) -> str:
    zone = _validate_name(args.get("zone", ""), "zone")
    return read_command_output(
        (
            "gcloud", "compute", "instances", "list",
            f"--zones={zone}",
            "--format=json(name,zone,machineType,networkInterfaces[0]."
            "networkIP,status)",
        ),
        timeout=_TIMEOUT_S,
    )


def _az_vms(args: dict) -> str:
    group = _validate_name(args.get("group", ""), "resource group")
    return read_command_output(
        ("az", "vm", "list", "-g", group, "-d", "--output", "json"),
        timeout=_TIMEOUT_S,
    )


# --- tool definitions ----------------------------------------------------------

AWS_INSTANCES = Tool(
    name="aws_ec2_instances",
    description=(
        "List EC2 instances in one AWS region as compact JSON "
        "(aws ec2 describe-instances --region <region> with a --query "
        "projection: id, type, state, availability zone, private IP, Name "
        "tag). Use to see what compute runs in a region during an "
        "investigation. Requires the aws CLI with working credentials. "
        "Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "AWS region name, e.g. us-east-1",
            },
        },
        "required": ["region"],
        "additionalProperties": False,
    },
    executor=_aws_instances,
)

GCLOUD_INSTANCES = Tool(
    name="gcloud_compute_instances",
    description=(
        "List GCP compute instances in one zone as JSON (gcloud compute "
        "instances list --zones=<zone>: name, zone, machine type, internal "
        "IP, status). Use to see what compute runs in a GCP zone during an "
        "investigation. Requires the gcloud CLI. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "zone": {
                "type": "string",
                "description": "GCP zone name, e.g. us-central1-a",
            },
        },
        "required": ["zone"],
        "additionalProperties": False,
    },
    executor=_gcloud_instances,
)

AZ_VMS = Tool(
    name="az_vm_list",
    description=(
        "List Azure VMs in one resource group with power state as JSON "
        "(az vm list -g <group> -d: name, location, powerState, "
        "provisioningState). Use to see what compute runs in an Azure "
        "resource group during an investigation. Requires the az CLI. "
        "Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "group": {
                "type": "string",
                "description": "Azure resource group name, e.g. rg-prod-east",
            },
        },
        "required": ["group"],
        "additionalProperties": False,
    },
    executor=_az_vms,
)

register(AWS_INSTANCES)
register(GCLOUD_INSTANCES)
register(AZ_VMS)
