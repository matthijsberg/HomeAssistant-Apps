# AGENTS.md — UniFi OS Server HA App (`unifi_os_server`)

## 1. Current State & Execution Gate
- **ACTIVE TARGET:** UniFi OS Server **6.0.19** Early Access (EA) target enabled and actively staging.
- The manifest `config.yaml` is active (`version: "6.0.19-0"`).
- Base build image: `ghcr.io/home-assistant/{arch}-base-debian:trixie`.
- Full implementation plan: `/config/.hermes/plans/2026-10-16_152500-unifi-os-server-ha-app.md`.

## 2. Quality Gates & Test Commands
Run the complete verification suite from `/config/projects/HomeAssistant-Apps/apps/unifi-os-server`:
```bash
./scripts/setup.sh
```
Individual checks:
- Manifest & translations parity: `python3 scripts/test_config.py`
- OKF v0.2 knowledge bundle: `bash scripts/validate_okf.sh`
- Secret & security scan: `bash scripts/security_audit.sh`
- Pytest suite: `pytest tests/ -v`

## 3. Architectural Invariants
1. **Strict English Only:** All code, manifests, translations, logs, and documentation must remain strictly in English.
2. **No Nested Containers / No Privileged Mode:** Never run Podman-in-Docker or `privileged: true`. Use only `NET_ADMIN` and `NET_RAW`.
3. **Localhost-Only Internal Ports:** Never expose PostgreSQL (`5432`) or the unauthenticated Network App bypass (`7443`/`8081`) outside `127.0.0.1`.
4. **Single `/data` Persistence:** All stateful paths must map under `/data/uos_storage/`.
