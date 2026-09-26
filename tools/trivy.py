"""Read-only security-scanning tools (Phase 9).

One tool: trivy image scan — a vulnerability report for a container image
(`trivy image --scanners vuln --format table <image>`). Trivy scans are
read-only: they pull the image and the vulnerability database and print a
report; nothing on this host or the registry is modified.

Safety model:
- Fixed argv template — the model may only choose the image reference.
- Image references are validated: letters, digits, '.', '-', '_', '/', ':',
  '@' only; must start (and end) alphanumeric, no leading '-', max 200
  characters. This blocks flag injection (refs starting with '-') and
  anything shell-ish — and there is no shell anyway (argv only).
- The subprocess timeout is long (180s) because a cold trivy download of
  the vulnerability database can take a while; the tool says so in its
  description so the model can warn the user.
- trivy must be installed; if missing, the exact error is returned.
"""

import re

from tools.base import Tool, ToolError, read_command_output
from tools.registry import register

# Container image reference: registry/repo:tag@digest shape, alnum at the
# ends, no leading '-' (no flag injection), no spaces.
_IMAGE_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._@/\-]*(?::[a-zA-Z0-9._\-]+)?"
)

_TIMEOUT_S = 180


def _check_image(value, kind: str = "image reference") -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 200
        or not _IMAGE_RE.fullmatch(value)
        or not value[-1].isalnum()
        or " " in value
    ):
        raise ToolError(
            f"invalid {kind} {value!r}: expected a container image reference "
            "like 'nginx:1.27' or 'registry.example.com/team/api:v2' "
            "(letters, digits, '.', '-', '_', '/', ':', '@'; no leading '-')"
        )
    return value


def _trivy_image_scan(args: dict) -> str:
    image = _check_image(args.get("image"))
    return read_command_output(
        ("trivy", "image", "--scanners", "vuln", "--format", "table", image),
        timeout=_TIMEOUT_S,
    )


TRIVY_IMAGE_SCAN = Tool(
    name="trivy_image_scan",
    description=(
        "Scan a container image for vulnerabilities with Trivy and return "
        "the report table: CVE id, severity, package, fixed version. Use "
        "when a pod/container incident smells like a CVE, when triaging "
        "'is this image safe to keep', or before recommending an image "
        "bump. NOTE: the first run downloads the vulnerability database "
        "and can take a couple of minutes. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "Image reference to scan, e.g. 'nginx:1.27' "
                "or 'registry.example.com/team/api:v2'.",
            }
        },
        "required": ["image"],
        "additionalProperties": False,
    },
    executor=_trivy_image_scan,
)

register(TRIVY_IMAGE_SCAN)
