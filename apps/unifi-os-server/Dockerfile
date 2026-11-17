ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:trixie
FROM ${BUILD_FROM} AS extractor

ARG TARGETARCH
ARG INSTALLER_URL_AMD64="https://fw-download.ubnt.com/data/unifi-os-server/37c2-linux-x64-6.0.21-f1a1e11d-30fa-4687-94b1-07229690ad6a.21-x64"
ARG INSTALLER_SHA256_AMD64="f918d5dd015dcda4fcbb1cee5f48a8a029a2bc5d885ed3114cd9b983c71995a7"
ARG INSTALLER_URL_ARM64="https://fw-download.ubnt.com/data/unifi-os-server/b5e4-linux-arm64-6.0.21-d1ffae05-9398-40a9-bfdf-28cba938ac98.21-arm64"
ARG INSTALLER_SHA256_ARM64="dee51de9ba1e4a4204c3b0e6a09ecefbc2fcd92959615c8797f517dd285ed057"
ARG MATTER_URL_AMD64="https://fw-download.ubnt.com/data/unifi-matter-controller/0004-uos-deb13-amd64-1.0.0-f8ed302f-fd41-49bf-b54b-9627b978683f.deb"
ARG MATTER_SHA256_AMD64="141ecca87c81989d44d8bccce65a5c828c4eff91834d16eb42b846371239dabb"
ARG MATTER_URL_ARM64="https://fw-download.ubnt.com/data/unifi-matter-controller/912c-uos-deb13-arm64-1.0.0-2803b05b-03ce-48d4-b533-af608c494441.deb"
ARG MATTER_SHA256_ARM64="0fc4b3aa6b41383ef439a0fc731a8933b2561310d602e7c95c28e4c360b51520"
ARG NETWORK_URL_AMD64="https://fw-download.ubnt.com/data/unifi/c11a-uos-deb13-amd64-11.0.99-37236-1-846bfcb2-6633-4f0c-8a93-4bff501748b2.deb"
ARG NETWORK_SHA256_AMD64="ebf4143ef67ce4c735b6739b2c41dc63e7519240cb465cd920f4b31d39e46a9d"
ARG NETWORK_URL_ARM64="https://fw-download.ubnt.com/data/unifi/fbce-uos-deb13-arm64-11.0.99-37236-1-469e36af-35c5-40e0-9106-78bcacad7b95.deb"
ARG NETWORK_SHA256_ARM64="ebf4143ef67ce4c735b6739b2c41dc63e7519240cb465cd920f4b31d39e46a9d"
ARG INNERSPACE_URL_AMD64="https://fw-download.ubnt.com/data/unifi-innerspace/e900-uos-deb13-amd64-1.4.3-a5191e93-2e87-48eb-9b69-4f68d7ad1923.deb"
ARG INNERSPACE_SHA256_AMD64="68c97fba9300c39412691ef0bc04c8a08aa83b66b6fc67da5a1969c904eb3c61"
ARG INNERSPACE_URL_ARM64="https://fw-download.ubnt.com/data/unifi-innerspace/6e65-uos-deb13-arm64-1.4.3-a59063b0-083a-41e5-89ff-120989a7e07d.deb"
ARG INNERSPACE_SHA256_ARM64="27cd32b509fbd3a0a5197b95d2a836e18a3fbb9681873d4122f276afc8ea6e98"

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
COPY scripts/patch_systemctl.py /build/patch_systemctl.py
RUN rm -f /rootfs/usr/bin/systemctl /rootfs/sbin/init /rootfs/usr/sbin/init && \
    curl -sSL -o /rootfs/usr/bin/systemctl \
    https://raw.githubusercontent.com/gdraheim/docker-systemctl-replacement/master/files/docker/systemctl3.py && \
    chmod 755 /rootfs/usr/bin/systemctl && \
    python3 /build/patch_systemctl.py && rm -rf /build && \
    if [ -L /rootfs/sbin ]; then ln -sf /usr/bin/systemctl /rootfs/usr/sbin/init; else mkdir -p /rootfs/sbin && ln -sf /usr/bin/systemctl /rootfs/sbin/init; fi

# 3b. Upgrade bundled UniFi Network (11.0.99) + Matter Controller (1.0.0) and install InnerSpace (1.4.3)
RUN if [ "${TARGETARCH:-amd64}" = "arm64" ]; then \
        MATTER_URL="${MATTER_URL_ARM64}"; MATTER_SHA="${MATTER_SHA256_ARM64}"; \
        NETWORK_URL="${NETWORK_URL_ARM64}"; NETWORK_SHA="${NETWORK_SHA256_ARM64}"; \
        INNERSPACE_URL="${INNERSPACE_URL_ARM64}"; INNERSPACE_SHA="${INNERSPACE_SHA256_ARM64}"; \
    else \
        MATTER_URL="${MATTER_URL_AMD64}"; MATTER_SHA="${MATTER_SHA256_AMD64}"; \
        NETWORK_URL="${NETWORK_URL_AMD64}"; NETWORK_SHA="${NETWORK_SHA256_AMD64}"; \
        INNERSPACE_URL="${INNERSPACE_URL_AMD64}"; INNERSPACE_SHA="${INNERSPACE_SHA256_AMD64}"; \
    fi; \
    curl -fsSL -o /rootfs/tmp/matter.deb "${MATTER_URL}" && echo "${MATTER_SHA}  /rootfs/tmp/matter.deb" | sha256sum -c - && \
    curl -fsSL -o /rootfs/tmp/unifi.deb "${NETWORK_URL}" && echo "${NETWORK_SHA}  /rootfs/tmp/unifi.deb" | sha256sum -c - && \
    curl -fsSL -o /rootfs/tmp/innerspace.deb "${INNERSPACE_URL}" && echo "${INNERSPACE_SHA}  /rootfs/tmp/innerspace.deb" | sha256sum -c - && \
    printf '#!/bin/sh\nexit 101\n' > /rootfs/usr/sbin/policy-rc.d && chmod 755 /rootfs/usr/sbin/policy-rc.d && \
    mv /rootfs/etc/dpkg/dpkg.cfg.d/015-ubnt-dpkg-status /rootfs/tmp/015-ubnt-dpkg-status.bak && \
    mv /rootfs/etc/dpkg/dpkg.cfg.d/020-ubnt-dpkg-cache /rootfs/tmp/020-ubnt-dpkg-cache.bak && \
    DEBIAN_FRONTEND=noninteractive chroot /rootfs dpkg -i --force-confold /tmp/matter.deb /tmp/unifi.deb /tmp/innerspace.deb && \
    cp -L /etc/resolv.conf /rootfs/etc/resolv.conf && \
    DEBIAN_FRONTEND=noninteractive chroot /rootfs apt-get update && \
    DEBIAN_FRONTEND=noninteractive chroot /rootfs apt-get install -y --only-upgrade --no-install-recommends apt libapt-pkg7.0 zlib1g && \
    rm -rf /rootfs/var/lib/apt/lists/* /rootfs/etc/resolv.conf && \
    mv /rootfs/tmp/015-ubnt-dpkg-status.bak /rootfs/etc/dpkg/dpkg.cfg.d/015-ubnt-dpkg-status && \
    mv /rootfs/tmp/020-ubnt-dpkg-cache.bak /rootfs/etc/dpkg/dpkg.cfg.d/020-ubnt-dpkg-cache && \
    rm -f /rootfs/tmp/matter.deb /rootfs/tmp/unifi.deb /rootfs/tmp/innerspace.deb /rootfs/usr/sbin/policy-rc.d /rootfs/var/log/unifi_package.log && \
    rm -f /rootfs/etc/systemd/system/multi-user.target.wants/unifi-innerspace.service

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
    UNIFI_NETWORK_VERSION="11.0.99-37236-1" \
    UNIFI_INNERSPACE_VERSION="1.4.3" \
    UNIFI_MATTER_VERSION="1.0.0" \
    APP_VERSION="6.0.21" \
    APP_MODEL="UOSSERVER" \
    PRODUCT_NAME="UniFi OS Server" \
    DEBIAN_FRONTEND="noninteractive"

COPY --from=extractor /rootfs /

EXPOSE 443/tcp 80/tcp 8080/tcp 8443/tcp 8444/tcp 8880/tcp 6789/tcp 3478/udp 10003/udp 10001/udp 5514/udp

ENTRYPOINT ["/run.sh"]
