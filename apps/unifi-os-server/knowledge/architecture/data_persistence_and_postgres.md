---
id: data-persistence-and-postgres
title: "Single-Volume /data Persistence and Idempotent PostgreSQL Pre-Seeding"
type: "Architectural Decision"
status: "active"
trust: "human_reviewed"
generated: { by: "hermes/gemini-4-argon", at: "2026-10-16T15:30:00Z" }
verified:
  - { by: "human:matthijs", at: "2026-10-16T15:30:00Z" }
tags: [postgresql, mongodb, persistence, unifi-network-11, storage]
sources:
  - id: unifi-network-11-release
    resource: "https://community.ui.com/releases/UniFi-Network-Application-11-0-83/d6940379-cd5a-4e61-8596-7e22d647a4ea"
    title: "UniFi Network Application 11.0.83 Release Notes (PostgreSQL Migration)"
---

# Single-Volume /data Persistence and Idempotent PostgreSQL Pre-Seeding

## Context & Problem
Home Assistant Supervisor provides a single persistent `/data` volume per add-on, whereas UniFi OS Server writes state across `/var/lib/unifi`, `/var/lib/uosserver`, `/var/lib/postgresql`, `/var/lib/mongodb`, `/etc/rabbitmq/ssl`, and `/data`. Furthermore, **UniFi Network 11** migrates the core Network Application database from MongoDB to **PostgreSQL**,[^unifi-network-11-release] and upstream `pre-start.sh` scripts fail non-deterministically if PostgreSQL roles or databases already exist or start concurrently.

## Normative Contracts & Invariants

1. **Unified `/data/uos_storage` Hierarchy:**
   - On startup, `run.sh` initializes `/data/uos_storage/{unifi,uosserver,unifi-core,postgresql,mongodb,rabbitmq-ssl,logs}` and bind-mounts/symlinks each target path before starting any daemon.
   - Console UUIDv5 identity is persisted in `/data/uos_uuid` so Site Manager and local RS256 JWKS keys (`/run/unifi-core/jwks.json`) survive container upgrades.
2. **Idempotent PostgreSQL Pre-Seeding:**
   - Prior to starting `unifi-core` or `unifi`, `run.sh` starts PostgreSQL locally, verifies/creates roles and databases (`ulp-go`, `ulp-go-syslog`, `uid`, `ucs-agent`, `unifi-directory`, `unifi-identity-update`, `unifi`), records a versioned `.uos_postgres_preseeded` marker, and cleanly stops the pre-seed instance.
3. **Strict Localhost Database Binding:**
   - PostgreSQL (`5432`) and MongoDB (`27017`/`27117`) listen exclusively on `127.0.0.1`. They are never exposed to the Docker bridge or host network.

[^unifi-network-11-release]: UniFi Network Application 11.0.83 Release Notes (PostgreSQL Migration)
