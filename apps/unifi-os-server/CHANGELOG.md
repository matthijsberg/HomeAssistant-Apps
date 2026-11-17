# Changelog

## [6.0.21-2] - 2026-11-17 (Early Access Target)
- Hardened Home Assistant host mounts in `config.yaml` from `ssl:rw` and `share:rw` to read-only (`ssl:ro`, `share:ro`).
- Enforced `0600` permissions on all persisted TLS private keys (`*.key`) in `/data/uos_storage/unifi-core/config/` via `rootfs/run.sh` and `uos-supervisor-shim.mjs`.
- Upgraded Debian Trixie security packages (`apt`, `libapt-pkg7.0`, `zlib1g`) in `Dockerfile` during image build (`CVE-2026-109518`, `CVE-2026-85091`).
- Added dedicated GitHub Actions CI & Trivy container image security workflow (`.github/workflows/addon-unifi-os-server.yml`).

## [6.0.21-1] - 2026-11-16 (Early Access Target)
- Upgraded bundled UniFi Network Application from `10.6.109` to `11.0.99-37236-1` along with required `unifi-matter-controller` (`1.0.0`) via SHA-256 verified build-time `.deb` installation (`amd64` & `aarch64`).
- Added bundled UniFi InnerSpace (`1.4.3`) gated by a new `enable_innerspace` option (default `false`) with persistent `/data/unifi-innerspace` storage.
- Configured Ubiquiti Firmware Update Service (`fw-update.ui.com`) upstream polling in `maintenance.yaml` and `tools/maintenance/` across `unifi-os-server`, `unifi`, `unifi-innerspace`, and `unifi-matter-controller`, and documented component requirements in `PRD.md`.

## [6.0.21-0] - 2026-11-16 (Early Access Target)

### Changed
- Upgraded target installer to UniFi OS Server `6.0.21` EA (`amd64` and `arm64` SHA-256 checksums verified), bundling UniFi Network `10.6.109` and Identity Sync `1.8.8`.
- Isolated UniFi OS Server backups under `/backup/unifi-os-server/` (preventing collisions with legacy `/backup/unifi/`) while selecting the newest `.unf` backup by mtime for dropzone auto-restore.
- Added `scripts/extract_oci.py` (Python `zipfile` + whiteout-aware OCI extraction) to handle SFX installer extra-bytes cleanly.
- Added `systemd-dbus-shim.py` (`org.freedesktop.systemd1` D-Bus shim backed by `systemctl3.py`), D-Bus daemon startup, PostgreSQL 14 cluster init (`14-main` + `14-apps`), `unifi-mongodb.service` enablement, UUIDv5 `uos_uuid` generation, and `443/tcp -> 11443` port mapping.
- Added `uos-supervisor-shim.mjs` (UCP4 `/api/ws/supervisor` client using `@ubnt/ucp4`) and `MainPID` `/proc` liveness check in `systemd-dbus-shim.py` so `unifi-core` reaches `deviceState: notSetup` with `network.info.isReadyForSetup: true` and `GET /api/backup/setup/has-legacy-net` returns HTTP 200.
- Added `use_ha_ssl` (default `true`) synced by `uos-supervisor-shim.mjs` via `unifi-core`'s official `userCertificates` IPC API (supporting RSA & ECDSA `/ssl` certificates with automatic fallback to UniFi's built-in self-signed certificate when disabled or invalid); renamed app to `UniFi OS - Early Access`, documented tester callout in `README.md`, and removed personal/local paths.
- Disabled UniFi OS and application in-container auto-update schedules (`firmware.yaml` and `apps.userPrefs.yaml`) on startup so updates remain managed exclusively by Home Assistant.

## [6.0.19-0] - 2026-11-05 (Early Access Target)

### Added
- Activated `config.yaml` for UniFi OS Server 6.0.19 Early Access release.
- Added multi-stage `Dockerfile` extracting official Ubiquiti OCI image from Debian Trixie base (`ghcr.io/home-assistant/{arch}-base-debian:trixie`).
- Added `rootfs/run.sh` entrypoint supporting cgroups v2 dynamic memory auto-scaling, `/data/uos_storage` persistence, universal `.unf` dropzone auto-restore, and PostgreSQL 16 pre-seeding.
- Added `rootfs/usr/local/bin/uos-diagnostics` service status utility.
- Added store branding assets `icon.png` (512x512) and `logo.png` (1280x640).
- Updated `build.yaml` with verified SHA256 checksums for `amd64` and `aarch64`.

## [0.1.0] - 2026-10-16 (Staged)

### Added
- Initial HA App scaffolding, PRD, OKF v0.2 knowledge bundle, and automated test suite for UniFi OS Server 6.0+ & UniFi Network 11+.
- Staged as `config.yaml.disabled` pending Ubiquiti's official release of UniFi OS Server 6.0.
