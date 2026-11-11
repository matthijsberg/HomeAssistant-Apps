ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:trixie
FROM ${BUILD_FROM} AS extractor

ARG TARGETARCH
ARG INSTALLER_URL_AMD64="https://fw-download.ubnt.com/data/unifi-os-server/a6b0-linux-x64-6.0.19-4addcb6a-84d2-428c-84c3-d36a64740bdc.19-x64"
ARG INSTALLER_SHA256_AMD64="3f9bf0f34e98f0a80d8506cc477bccbbe4394adaf16d16c93d3cd9a5fbe99a48"
ARG INSTALLER_URL_ARM64="https://fw-download.ubnt.com/data/unifi-os-server/08a8-linux-arm64-6.0.19-111cc795-a829-4f60-a6fb-ec4e15d5b54f.19-arm64"
ARG INSTALLER_SHA256_ARM64="6a65e2e76b1587e338b298a6edcd15216ced976306a602bb7743d15756558d74"

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
RUN mkdir -p /build/oci /rootfs && \
    unzip -q installer.bin image.tar && \
    tar -xf image.tar -C /build/oci && \
    python3 -c '\
import json, tarfile, os, sys\n\
with open("/build/oci/manifest.json") as f:\n\
    manifest = json.load(f)\n\
layers = manifest[0].get("Layers", [])\n\
print(f"Extracting {len(layers)} OCI layers into /rootfs...")\n\
for layer_rel in layers:\n\
    layer_path = os.path.join("/build/oci", layer_rel)\n\
    print(f"  Unpacking {layer_rel}...")\n\
    with tarfile.open(layer_path) as tf:\n\
        for member in tf.getmembers():\n\
            base = os.path.basename(member.name)\n\
            if base.startswith(".wh."):\n\
                target_del = os.path.join("/rootfs", os.path.dirname(member.name), base[4:])\n\
                if os.path.exists(target_del):\n\
                    if os.path.isdir(target_del) and not os.path.islink(target_del):\n\
                        import shutil; shutil.rmtree(target_del, ignore_errors=True)\n\
                    else:\n\
                        os.remove(target_del)\n\
                continue\n\
            try:\n\
                tf.extract(member, path="/rootfs", set_attrs=True)\n\
            except Exception as e:\n\
                pass\n\
print("OCI rootfs extraction complete.")\n\
'

# 3. Install docker-systemctl-replacement (systemctl3.py) to manage services without cgroups v2 failure
RUN curl -sSL -o /rootfs/usr/bin/systemctl \
    https://raw.githubusercontent.com/gdraheim/docker-systemctl-replacement/master/files/docker/systemctl3.py && \
    chmod 755 /rootfs/usr/bin/systemctl && \
    ln -sf /usr/bin/systemctl /rootfs/sbin/init

# 4. Copy custom entrypoint and diagnostics tools
COPY rootfs/ /rootfs/
RUN chmod 755 /rootfs/run.sh /rootfs/usr/local/bin/uos-diagnostics

# --- Stage 2: Final Runtime Image ---
FROM scratch
LABEL maintainer="Matthijs van den Berg <matthijs@b3rg.nl>"
LABEL org.opencontainers.image.title="UniFi OS Server"
LABEL org.opencontainers.image.description="Self-hosted UniFi OS Server 6+ & UniFi Network 11+ for Home Assistant OS"
LABEL org.opencontainers.image.source="https://github.com/matthijsberg/HomeAssistant-Apps"

ENV UOS_SERVER_VERSION="6.0.19" \
    APP_VERSION="6.0.19" \
    APP_MODEL="UOSSERVER" \
    PRODUCT_NAME="UniFi OS Server" \
    DEBIAN_FRONTEND="noninteractive"

COPY --from=extractor /rootfs /

EXPOSE 11443/tcp 8080/tcp 8443/tcp 8444/tcp 8880/tcp 6789/tcp 3478/udp 10003/udp 10001/udp 5514/udp

ENTRYPOINT ["/run.sh"]
