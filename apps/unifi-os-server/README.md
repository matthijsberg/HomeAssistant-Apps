# UniFi OS - Early Access (Home Assistant App)

> **Early Access Notice:** This app currently targets **Ubiquiti UniFi OS Server `6.0.21` (Early Access)** bundling **UniFi Network `11.0.99`**, **UniFi Matter Controller `1.0.0`**, and optional **UniFi InnerSpace `1.4.3`**. Early Access releases can change rapidly compared to GA (`5.1.x`).

Self-hosted **UniFi OS Server 6+** and **UniFi Network Application** packaged as a clean, zero-nested-container Home Assistant OS App.

## Testers Wanted

Community testing and feedback are welcome! The following areas still need end-to-end verification before a stable GA release:

1. **Setup Wizard & Live Device Adoption:** Completing the full UniFi OS setup flow and cutting over `8080/tcp`, `3478/udp`, and `10001/udp` to adopt/manage live switches and access points.
2. **Legacy `5.x` Backup Migration:** Importing/restoring `.unf` backups from the legacy `a0d7b954_unifi` add-on into UniFi OS Server `6.0.21`.
3. **`aarch64` (ARM64) Runtime:** Installer URLs and SHA-256 checksums for `arm64` are verified, while live runtime testing has so far been completed on `amd64` only.

## Key Features

- **Direct OCI Rootfs Extraction:** Extracts the official `uosserver` OCI image at build time — no nested Podman or QEMU virtualization overhead.
- **HAOS Cgroup v2 Native:** Orchestrates UniFi OS services (`unifi-core`, `unifi`, `postgresql`, `mongodb`, `rabbitmq-server`, `nginx`, `ulp-go`, `uos-agent`) without requiring `privileged: true` or host cgroup namespace hacks.
- **Automatic Home Assistant SSL Integration:** Uses a valid certificate from `/ssl` (such as Let's Encrypt) when `use_ha_ssl: true`, and falls back cleanly to UniFi's built-in self-signed certificate if none is present or disabled.
- **Isolated Backups & Drop-In Migration:** Stores backups separately in `/backup/unifi-os-server/` while preserving `8080/tcp` inform and `3478/udp` STUN ports for cutover from `a0d7b954_unifi`.

## Verification

Run all local manifest, OKF v0.2, security, and pytest quality gates:

```bash
./scripts/setup.sh
```
