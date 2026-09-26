# DevOps AI Agent — the agent plus the CLIs it investigates with, in one image.
#
# Usage:
#   docker run --rm -e OPENROUTER_API_KEY=sk-or-... \
#     -v "$HOME/.kube:/home/agent/.kube:ro" \
#     -v agent-records:/data \
#     ghcr.io/devopsabhii/devops-ai-agent --json "why is api-5d6f crash-looping?"
#
# Bundled CLIs: kubectl, helm, gh, trivy, git, curl, docker CLI + compose
# (docker/compose tools need the host socket: -v /var/run/docker.sock:/var/run/docker.sock).
# Agent CLIs NOT bundled (install your own image layer if you need them):
# systemctl/journalctl (needs a systemd host), terraform, argocd, istioctl,
# aws/gcloud/az, ansible. Every missing CLI fails with its exact error — the
# agent stays honest about what it cannot reach.

FROM python:3.12-slim

ARG KUBECTL_VERSION=v1.31.2
ARG HELM_VERSION=v3.16.3
ARG TRIVY_VERSION=0.58.1
ARG GH_VERSION=2.62.0

# Layer 1: base tooling + apt-native CLIs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Layer 2: Python dependencies (rarely change; kept above the fast-moving CLIs).
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Layer 3: the CLIs that move faster, from their official release endpoints.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    # kubectl
    curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl" \
      && chmod +x /usr/local/bin/kubectl; \
    # helm
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz" \
      | tar -xz -C /tmp --strip-components=1 "linux-${arch}/helm" \
      && mv /tmp/helm /usr/local/bin/helm; \
    # trivy
    curl -fsSL -o /tmp/trivy.deb \
      "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.deb" \
      && dpkg -i /tmp/trivy.deb || apt-get -f install -y; \
    rm -f /tmp/trivy.deb; \
    # gh
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz" \
      | tar -xz -C /tmp --strip-components=1 \
      && mv /tmp/bin/gh /usr/local/bin/gh

# Layer 4: the application itself (installed from pyproject — the same
# package that ships to PyPI).
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# Run as a non-root user; /data is where investigation records go so they
# survive container restarts (AGENT_STORE_DIR points there).
RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /data && chown agent:agent /data
USER agent
ENV AGENT_STORE_DIR=/data
WORKDIR /home/agent

ENTRYPOINT ["python", "-m", "main"]
