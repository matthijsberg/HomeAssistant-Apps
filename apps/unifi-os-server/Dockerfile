ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:trixie
FROM ${BUILD_FROM} AS extractor

ARG TARGETARCH
ARG INSTALLER_URL_AMD64="https://fw-download.ubnt.com/data/unifi-os-server/37c2-linux-x64-6.0.21-f1a1e11d-30fa-4687-94b1-07229690ad6a.21-x64"
ARG INSTALLER_SHA256_AMD64="f918d5dd015dcda4fcbb1cee5f48a8a029a2bc5d885ed3114cd9b983c71995a7"
ARG INSTALLER_URL_ARM64="https://fw-download.ubnt.com/data/unifi-os-server/b5e4-linux-arm64-6.0.21-d1ffae05-9398-40a9-bfdf-28cba938ac98.21-arm64"
ARG INSTALLER_SHA256_ARM64="dee51de9ba1e4a4204c3b0e6a09ecefbc2fcd92959615c8797f517dd285ed057"

SHELL ["/bin/bash", "-Eeuo", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    jq \
    ca-certificates \
    python3 \
    tar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 1. Download official Ubiquiti UniFi OS Server installer matching architecture
RUN if [ "${TARGETARCH:-amd64}" = "arm64" ]; then \
        INSTALLER_URL="${INSTALLER_URL_ARM64}"; \
        EXPECTED_SHA256="${INSTALLER_SHA256_ARM64}"; \
    else \
        INSTALLER_URL="${INSTALLER_URL_AMD64}"; \
        EXPECTED_SHA256="${INSTALLER_SHA256_AMD64}"; \
    fi; \
    echo "Downloading installer from ${INSTALLER_URL}..."; \
    curl -sSL -o installer.bin "${INSTALLER_URL}"; \
    echo "${EXPECTED_SHA256}  installer.bin" | sha256sum -c -

# 2. Extract embedded OCI image and flatten layers into /rootfs
COPY scripts/extract_oci.py /build/extract_oci.py
RUN python3 /build/extract_oci.py && rm -rf /build

# 3. Install docker-systemctl-replacement (systemctl3.py) to manage services without cgroups v2 failure
RUN rm -f /rootfs/usr/bin/systemctl /rootfs/sbin/init /rootfs/usr/sbin/init && \
    curl -sSL -o /rootfs/usr/bin/systemctl \
    https://raw.githubusercontent.com/gdraheim/docker-systemctl-replacement/master/files/docker/systemctl3.py && \
    chmod 755 /rootfs/usr/bin/systemctl && \
    if [ -L /rootfs/sbin ]; then ln -sf /usr/bin/systemctl /rootfs/usr/sbin/init; else mkdir -p /rootfs/sbin && ln -sf /usr/bin/systemctl /rootfs/sbin/init; fi

# 4. Copy custom entrypoint and diagnostics tools
COPY rootfs/ /rootfs/
RUN chmod 755 /rootfs/run.sh /rootfs/usr/local/bin/uos-diagnostics /rootfs/usr/local/bin/systemd-dbus-shim.py /rootfs/usr/local/bin/uos-supervisor-shim.mjs

# --- Stage 2: Final Runtime Image ---
FROM scratch
LABEL org.opencontainers.image.authors="HomeAssistant-Apps Contributors"
LABEL org.opencontainers.image.title="UniFi OS - Early Access"
LABEL org.opencontainers.image.description="Self-hosted UniFi OS Server 6+ & UniFi Network controller for Home Assistant OS"
LABEL org.opencontainers.image.source="https://github.com/matthijsberg/HomeAssistant-Apps"

ENV UOS_SERVER_VERSION="6.0.21" \
    APP_VERSION="6.0.21" \
    APP_MODEL="UOSSERVER" \
    PRODUCT_NAME="UniFi OS Server" \
    DEBIAN_FRONTEND="noninteractive"

COPY --from=extractor /rootfs /

EXPOSE 443/tcp 80/tcp 8080/tcp 8443/tcp 8444/tcp 8880/tcp 6789/tcp 3478/udp 10003/udp 10001/udp 5514/udp

ENTRYPOINT ["/run.sh"]
