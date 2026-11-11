# Changelog

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
