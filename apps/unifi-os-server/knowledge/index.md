---
okf_version: "0.2"
title: "UniFi OS Server & Network 11 HA App Knowledge Bundle"
description: "Authoritative architectural contracts, security invariants, and migration playbooks for the unifi_os_server Home Assistant App."
last_updated: "2026-10-16"
---

# Knowledge Index — unifi_os_server

This bundle contains the normative architectural decisions, security boundaries, and migration procedures governing the **UniFi OS Server Home Assistant App** (`unifi_os_server`).

## 1. Architecture Contracts
- [`oci-extraction-and-supervision`](architecture/oci_extraction_and_supervision.md) — Build-time OCI rootfs extraction and HAOS cgroup v2 process supervision without nested Podman.
- [`data-persistence-and-postgres`](architecture/data_persistence_and_postgres.md) — Single-volume `/data` persistence mapping and idempotent PostgreSQL cluster pre-seeding for UniFi OS 6 & Network 11.

## 2. Operations & Security
- [`ci-cd-and-security-gates`](operations/ci_cd_and_security_gates.md) — Automated Ubiquiti API release polling, live container smoke testing, and Trivy/CVE-2026-34908 security gates.
- [`migration-and-rollback`](operations/migration_and_rollback.md) — Zero-downtime migration from legacy `a0d7b954_unifi` and 30-second warm rollback playbook.
