---
id: migration-and-rollback
title: "Zero-Downtime Migration from Legacy app-unifi and Rollback Playbook"
type: "Operational Playbook"
status: "active"
trust: "human_reviewed"
generated: { by: "hermes/gemini-4-argon", at: "2026-10-16T15:30:00Z" }
verified:
  - { by: "human:matthijs", at: "2026-10-16T15:30:00Z" }
tags: [migration, rollback, uxg-lite, home-assistant-integration]
sources:
  - id: ha-app-unifi-eol
    resource: "https://github.com/hassio-addons/app-unifi/issues/628"
    title: "Home Assistant app-unifi End-of-Life Notice"
---

# Zero-Downtime Migration from Legacy app-unifi and Rollback Playbook

## Context
The production network runs 10 UniFi devices (`UXG-Lite`, 4 switches, 5 APs) currently managed by `a0d7b954_unifi` (v5.3.1), which is End-of-Life.[^ha-app-unifi-eol]

## Migration Procedure

1. **Export Backup:** Download `.unf` backup from `a0d7b954_unifi` (`Settings > System > Backups`).
2. **Side-by-Side Installation:** Install `local_unifi_os_server` while `a0d7b954_unifi` is still present. Set `system_ip` to the Home Assistant LAN IP.
3. **Switchover:**
   - Stop `a0d7b954_unifi` and disable *Start on boot* (frees `8080/tcp` and `3478/udp`).
   - Start `local_unifi_os_server`.
   - Open `https://<HA-IP>:11443`, restore the `.unf` backup during onboarding.
   - Verify all 10 devices auto-adopt via `http://<HA-IP>:8080/inform`.
4. **Home Assistant Integration Re-Pointing:**
   - Create a local-only admin account in UniFi OS Control Plane (`Control Plane > Admins`).
   - Update the Home Assistant **UniFi Network** integration host/port from `8443` to `11443`.

## Instant Rollback Playbook (<30 Seconds)
If any regression occurs during testing:
1. Stop `local_unifi_os_server`.
2. Start `a0d7b954_unifi` (and re-enable *Start on boot*).
3. Revert the Home Assistant UniFi Network integration port back to `8443`.

[^ha-app-unifi-eol]: Home Assistant app-unifi End-of-Life Notice
