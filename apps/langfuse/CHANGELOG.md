# Changelog

All notable changes to the `Langfuse` Home Assistant Add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.76.0] - 2026-11-08

## What’s changed

## ⬆️ Dependency updates

- ⬆️ Update Langfuse upstream web and worker to v4.76.0
- ⬆️ Update base image to Debian 13 Trixie (`ghcr.io/home-assistant/{arch}-base-debian:trixie`)
- ⬆️ Update PostgreSQL to v16 via official Debian Trixie repository (`trixie-pgdg`)

## 🚀 Features

- 🚀 Chronological session list view and session tab in trace peek view
- 🚀 Topics summaries, assignments and rules in public API and MCP
- 🚀 Searchable organization, project, and model switchers
- 🚀 Audit-log read-access events for tRPC traces, sessions, and scores

## 🐛 Bug fixes

- 🐛 Dynamic Prisma query engine library detection (`PRISMA_QUERY_ENGINE_LIBRARY`) resolving pnpm path shifts across versions
- 🐛 Fixed `@langfuse/native-linux-x64-gnu` module resolution on glibc Debian runtime, eliminating worker crash loop and constant CPU load

## 🧰 Maintenance

- 🛡️ Verified clean security diff review via Mantis Security Agent (gemini-4-argon) [Job: rev_25bc18081f, Verdict: CLEAN]

## [4.72.3] - 2026-11-04

### Changed
- Migrated base image to Debian 13 Trixie (`ghcr.io/home-assistant/{arch}-base-debian:trixie`) with native glibc 2.41 and OpenSSL 3.0 runtime.
- Installed PostgreSQL 16 via official PostgreSQL Trixie repository (`trixie-pgdg`) to maintain 100% binary compatibility with existing `/data/postgres` data clusters.
- Configured explicit Prisma Query Engine library loading (`PRISMA_QUERY_ENGINE_LIBRARY`) for Langfuse Web and Worker.

### Fixed
- Fixed high constant CPU consumption caused by `langfuse-worker` crash loop missing `@langfuse/native-linux-x64-musl`. Native module `langfuse-native.linux-x64-gnu.node` now loads cleanly.
- Fixed HTTP 500 errors in `langfuse-web` caused by missing Prisma musl query engine.

## [4.72.2] - 2026-11-03

### Security
- Restricted ClickHouse user network scope strictly to loopback (`127.0.0.1` and `::1`) and revoked `access_management: 1` admin privileges in `users.d/langfuse.xml` following Mantis GLM-5.3 audit findings.
- Added Redis memory ceiling (`--maxmemory 512mb --maxmemory-policy allkeys-lru`) and enforced PostgreSQL buffer boundaries (`shared_buffers = 256MB`, `work_mem = 16MB`).
- Modernized options parsing in `init_config.sh` to use `jq` and sanitized fallback URL to generic Home Assistant address.
- Verified with Mantis Security Agent using GLM 5.3 (`z-ai/glm-5.3`).

## [4.72.1] - 2026-11-03

### Fixed
- Enforced strict ClickHouse memory caps via `max_server_memory_usage` and `users.d` query limits based on `clickhouse_memory_limit_mb` (default 4096 MB) to prevent host RAM exhaustion.
- Added `init-config` to `clickhouse` s6-overlay dependencies to ensure memory cap configs are written before server startup.
- Removed duplicate background `ha_sensor_reporter.js &` from `langfuse-worker/run`, resolving leaked orphaned node processes across worker restarts.

## [4.72.0] - 2026-11-02

### Changed
- Upgraded Langfuse upstream images to v4.72.0 (`ghcr.io/langfuse/langfuse:4` web and worker).
- Validated all s6-overlay service configurations, dual Nginx listeners, and Ingress routing.
- Passed pre-flight manifest and build schema validation tests.
- Verified OKF v0.2 knowledge bundle conformance.
- Security review pass completed via Mantis using Google Gemini 4 Argon (`gemini-4-argon`): Clean verdict.

## [4.0.0-1] - 2026-09-29

### Added
- Initial scaffolding and architecture for Langfuse v4 Home Assistant Add-on.
- Full multi-service architecture specification: PostgreSQL 16, ClickHouse 26.4, Redis 7.2, SeaweedFS (S3), Langfuse Web & Worker.
- Dynamic optional port mapping (`ports: 3000/tcp: null`) allowing Ingress-only default or user-defined LAN exposure.
- Open Knowledge Format (OKF v0.2) architectural knowledge bundle in `knowledge/`.
- Automated pre-commit linting, manifest verification (`scripts/test_config.py`), and secret scanning (`scripts/security_audit.sh`).
- Cold backup integration (`backup: cold`) and 120s graceful shutdown timeout (`timeout: 120`).
- Automated 30-day data retention engine specification.
