FROM debian:bookworm-slim

ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/venv/bin:$PATH"

# Install system dependencies and static analysis tools
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    jq \
    tar \
    util-linux \
    procps \
    ca-certificates \
    shellcheck \
    && rm -rf /var/lib/apt/lists/*

# Install Gitleaks (amd64) with SHA-256 verification
RUN curl -fsSL -o /tmp/gitleaks.tar.gz https://github.com/gitleaks/gitleaks/releases/download/v8.24.0/gitleaks_8.24.0_linux_x64.tar.gz \
    && echo "cb49b7de5ee986510fe8666ca0273a6cc15eb82571f2f14832c9e8920751f3a4  /tmp/gitleaks.tar.gz" | sha256sum -c - \
    && tar -xz -C /usr/local/bin -f /tmp/gitleaks.tar.gz gitleaks \
    && rm -f /tmp/gitleaks.tar.gz \
    && chmod +x /usr/local/bin/gitleaks

# Install Hadolint (amd64) with SHA-256 verification
RUN curl -fsSL -o /usr/local/bin/hadolint https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 \
    && echo "56de6d5e5ec427e17b74fa48d51271c7fc0d61244bf5c90e828aab8362d55010  /usr/local/bin/hadolint" | sha256sum -c - \
    && chmod +x /usr/local/bin/hadolint

# Set up Python virtual environment
RUN python3 -m venv /opt/venv

# Install Python requirements
WORKDIR /opt/mantis-security-agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /opt/mantis-security-agent/

# Set up runtime directories
RUN mkdir -p /data/cache /data/reports /data/workspaces \
    && chmod +x /opt/mantis-security-agent/run.sh

ENTRYPOINT ["/opt/mantis-security-agent/run.sh"]
