# Product Requirements Document (PRD) — UniFi OS Server & Network 11 HA App

**Project Slug:** `unifi_os_server`  
**Directory:** `/config/projects/HomeAssistant-Apps/apps/unifi-os-server/`  
**Version:** `0.2.0` (Targeting UniFi OS Server 6.0.19 EA)  
**Status:** Architecture Specified / Scaffolding Active  

---

## 1. Problem Statement & Objective

Ubiquiti has deprecated the legacy self-hosted **UniFi Network Server** (`hassio-addons/app-unifi`, `a0d7b954_unifi`) and requires **UniFi OS Server 6.0+** for **UniFi Network Application 11.0+**. Because Ubiquiti distributes UniFi OS Server exclusively as a Podman-oriented Rust installer wrapping a multi-service `systemd` OCI image, the official Home Assistant add-on has been marked End-of-Life without an upgrade path.

This project provides a clean, maintainable, generic, and security-hardened Home Assistant App (`unifi_os_server`) that runs UniFi OS Server 6.0+ and UniFi Network 11+ natively on Home Assistant OS without nested Podman containers or heavy QEMU virtual machines, ready for public open-source distribution.

---

## 2. Target Architectures & Community Compatibility

- **Supported CPU Architectures:**
  - `amd64` (x86_64: Intel Core/Xeon, AMD Ryzen, Proxmox VE, Unraid, bare-metal NUC).
  - `aarch64` (ARM64: Raspberry Pi 5, Home Assistant Green, Home Assistant Yellow, ODROID-M1).
- **Minimum Resource Requirements:**
  - Memory: 2 GB minimum (4 GB+ recommended for medium/large sites).
  - Storage: 20 GB free storage under HAOS `/data`.
- **UniFi Topology Compatibility:**
  - Compatible with all standalone UniFi Gateways (UXG-Pro, UXG-Max, UXG-Lite, UXG-Enterprise).
  - Compatible with UniFi Switches (USW series) and Access Points (U6, U7, AC/HD series).

---

## 3. Core Architectural Requirements

### 3.1 Build-Time OCI Extraction (Zero Nested Containers)
- The Docker build pipeline downloads Ubiquiti's official Linux installer (`x64` / `arm64`) from `https://fw-download.ubnt.com/data/unifi-os-server/...`.
- The installer (a self-extracting zip archive) embeds an OCI layout archive `image.tar`.
- During the multi-stage build using `ghcr.io/home-assistant/{arch}-base-debian:trixie` as extractor, `image.tar` is unpacked and its layers flattened into `/rootfs`.
- Layer whiteout markers (`.wh.*` and `.wh..wh..opq`) are processed cleanly.
- No runtime Podman daemon or nested container runtime is permitted.

### 3.2 HAOS Cgroup v2 & Service Supervision Compatibility
- Home Assistant Supervisor launches add-on containers with `--cgroupns=private` and a read-only `/sys/fs/cgroup` mount.
- To avoid requiring `privileged: true` or failing on `systemd` cgroup delegation, the image uses `docker-systemctl-replacement` (`systemctl3.py`) alongside a deterministic `run.sh` entrypoint to orchestrate upstream `.service` units (`postgresql`, `mongodb`, `rabbitmq-server`, `ulp-go`, `unifi-core`, `unifi`, `nginx`).
- Required Linux capabilities are restricted strictly to `NET_ADMIN` and `NET_RAW`.

### 3.3 Single-Volume `/data` Persistence & Database Pre-Seeding
- All persistent paths (`/var/lib/unifi`, `/var/lib/uosserver`, `/var/lib/postgresql`, `/var/lib/mongodb`, `/etc/rabbitmq/ssl`, `/data/unifi-core`, `/data/uos_uuid`, `/persistent`) are mapped into `/data/uos_storage/`.
- Dynamic memory auto-tuning reads `/sys/fs/cgroup/memory.max` to allocate appropriate JVM `-Xms`/`-Xmx` values when using default settings.
- Before starting services, `run.sh` idempotently initializes PostgreSQL 16 cluster and pre-seeds required roles and databases (`ulp-go`, `ulp-go-syslog`, `uid`, `ucs-agent`, `unifi-directory`, `unifi-identity-update`, `unifi`).
- PostgreSQL (`5432`) and Network App internal ports (`7443`/`8081`) remain strictly bound to `127.0.0.1` inside the container.

### 3.4 Automated Release Pipeline & Security Gates
- GitHub Actions workflow polls Ubiquiti's download API for new releases.
- Automated multi-arch build (`linux/amd64`, `linux/arm64`), live container startup smoke test (verifying services and ports `11443`, `8080`, `3478`), and **Trivy** vulnerability scan (`CRITICAL,HIGH`).
- Gated pass through **Mantis Security Agent** using Google Gemini 4 Argon (`gemini-4-argon`) before release tagging.

### 3.5 Universal Database Migration & Instant Rollback
- **Dropzone Auto-Restore:** Automatically scans `/backup/` and `/share/unifi-backup/` for legacy `.unf` backup files (supporting UniFi 5.x through 10.x), enabling 1-click migration without manual database conversions.
- **Parallel Testing:** Distinct add-on slug (`unifi_os_server`) allows parallel installation alongside the deprecated `a0d7b954_unifi` controller.
- **Rollback Safety:** Immediate fallback to the old controller by stopping `unifi_os_server` and starting `a0d7b954_unifi` (< 30 seconds).
