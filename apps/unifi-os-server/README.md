# UniFi OS Server (Home Assistant App)

> **Status:** Staged (`0.1.0`) — awaiting Ubiquiti's official release of **UniFi OS Server 6.0** (required for **UniFi Network Application 11.0+**).
> Implementation plan: `/config/.hermes/plans/2026-10-16_152500-unifi-os-server-ha-app.md`

Self-hosted **UniFi OS Server 6+** and **UniFi Network Application 11+** packaged as a clean, zero-nested-container Home Assistant OS App.

## Key Features

- **Direct OCI Rootfs Extraction:** Extracts the official `uosserver` OCI image at build time — no nested Podman or QEMU virtualization overhead.
- **HAOS Cgroup v2 Native:** Orchestrates UniFi OS services (`unifi-core`, `unifi`, `postgresql`, `mongodb`, `rabbitmq-server`, `nginx`, `ulp-go`) without requiring `privileged: true` or host cgroup namespace hacks.
- **Automated Security & Release Pipeline:** Daily CI check against Ubiquiti's download API with automated container smoke testing and Trivy/CVE security gates.
- **Drop-In Migration:** Preserves `8080/tcp` inform and `3478/udp` STUN ports for seamless migration from the legacy `a0d7b954_unifi` add-on.

## Verification

Run all local manifest, OKF v0.2, security, and pytest quality gates:

```bash
./scripts/setup.sh
```
