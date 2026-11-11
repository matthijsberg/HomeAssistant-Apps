---
id: oci-extraction-and-supervision
title: "Build-Time OCI Rootfs Extraction and HAOS Cgroup v2 Supervision"
type: "Architectural Decision"
status: "active"
trust: "human_reviewed"
generated: { by: "hermes/gemini-4-argon", at: "2026-10-16T15:30:00Z" }
verified:
  - { by: "human:matthijs", at: "2026-10-16T15:30:00Z" }
tags: [unifi-os, oci, cgroup-v2, systemctl, haos, docker]
sources:
  - id: ubiquiti-self-hosting
    resource: "https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi"
    title: "Ubiquiti Self-Hosting UniFi OS Server Documentation"
  - id: ha-cgroup-discussion
    resource: "https://github.com/orgs/home-assistant/discussions/3203"
    title: "Home Assistant Supervisor Private Cgroup v2 Namespace Architecture"
---

# Build-Time OCI Rootfs Extraction and HAOS Cgroup v2 Supervision

## Context & Problem
Ubiquiti distributes **UniFi OS Server** as a standalone Rust installer binary that embeds an OCI container archive (`image.tar`) and launches it via Podman with `--systemd=always`.[^ubiquiti-self-hosting] Meanwhile, Home Assistant Supervisor runs on cgroup v2 with `--cgroupns=private` and mounts `/sys/fs/cgroup` read-only inside add-on containers.[^ha-cgroup-discussion] Running nested Podman or QEMU inside a Home Assistant App introduces severe resource overhead and requires `privileged: true`.

## Normative Contracts & Invariants

1. **Zero Nested Containers:**
   - The multi-stage `Dockerfile` extracts `image.tar` from the official Ubiquiti installer during build time, parses `oci/index.json`, and flattens all OCI layers (applying `.wh.*` whiteout markers) directly into `/rootfs`.
2. **Cgroup v2 Safe Service Orchestration:**
   - Because `/sys/fs/cgroup` is read-only under HAOS Supervisor's default security profile, the container uses `systemctl3.py` (`docker-systemctl-replacement`) as its service supervisor to parse and launch the upstream `.service` units (`postgresql`, `mongodb`, `rabbitmq-server`, `ulp-go`, `unifi-core`, `unifi`, `nginx`) without requiring cgroup filesystem writes or `SYS_ADMIN`.
3. **Minimal Capability Footprint:**
   - The add-on manifest requests only `NET_ADMIN` and `NET_RAW` (never `privileged: true`).

[^ubiquiti-self-hosting]: Ubiquiti Self-Hosting UniFi OS Server Documentation
[^ha-cgroup-discussion]: Home Assistant Supervisor Private Cgroup v2 Namespace Architecture
