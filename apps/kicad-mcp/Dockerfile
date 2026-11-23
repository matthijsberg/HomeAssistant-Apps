FROM ubuntu:26.04

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/usr/local/bin:/opt/venv/bin:/usr/bin:/bin"

# Install headless KiCad 9.x (native in Ubuntu 26.04 LTS), Python bindings, SVG rasterizer,
# and minimal software-OpenGL/Xvfb libs for on-demand `kicad-cli pcb render` (no VNC/desktop).
# Force IPv4 and automatically fall back to a regional Ubuntu mirror if archive.ubuntu.com stalls.
RUN printf 'Acquire::ForceIPv4 "true";\nAcquire::http::Timeout "10";\nAcquire::Retries "2";\n' \
        > /etc/apt/apt.conf.d/99network \
    && (apt-get update -o APT::Update::Error-Mode=any || ( \
        sed -i 's|http://archive.ubuntu.com/ubuntu|http://nl.archive.ubuntu.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://nl.archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources \
        && apt-get update -o APT::Update::Error-Mode=any \
    )) \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        kicad \
        ngspice \
        librsvg2-bin \
        xvfb \
        xauth \
        libgl1 \
        libgl1-mesa-dri \
        libegl1 \
        libglu1-mesa \
        libgbm1 \
        fontconfig \
        fonts-dejavu-core \
        python3 \
        python3-pip \
        python3-venv \
        git \
        jq \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Wrap kicad-cli so `pcb render` automatically runs under an ephemeral xvfb-run + Mesa llvmpipe
# context whenever DISPLAY is unset — keeping zero persistent X11/VNC daemon overhead.
COPY bin/kicad-cli-wrapper.sh /usr/local/bin/kicad-cli
RUN chmod 0755 /usr/local/bin/kicad-cli

# Create Python venv inheriting system site-packages so KiCad's native `pcbnew` module is importable.
RUN python3 -m venv --system-site-packages /opt/venv

# Install atopile in an isolated venv on x86_64 so its dependency tree never conflicts
# with the pinned FastMCP/Seeed-Studio stack (and multi-arch aarch64 builds degrade gracefully).
RUN if [ "$(uname -m)" = "x86_64" ]; then \
        python3 -m venv /opt/atopile-venv \
        && /opt/atopile-venv/bin/pip install --no-cache-dir --upgrade pip \
        && /opt/atopile-venv/bin/pip install --no-cache-dir atopile==0.15.9; \
    else \
        echo "[KiCad-MCP] Skipping atopile install on $(uname -m) (no Linux wheel available)"; \
    fi

WORKDIR /opt/kicad-mcp
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml run.sh ./
COPY src/ ./src/

RUN /opt/venv/bin/pip install --no-cache-dir --no-deps -e . \
    && chmod 0755 /opt/kicad-mcp/run.sh \
    && mkdir -p /data /share/kicad

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT ["/opt/kicad-mcp/run.sh"]
