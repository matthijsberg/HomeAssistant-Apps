---
id: log
title: "Langfuse Knowledge Maintenance Log"
type: log
status: active
trust: verified
---

# Knowledge Maintenance Log

### [2026-11-08] Maintenance: Upgrade to v4.76.0 (Debian Trixie base)
- **Date**: 2026-11-08
- **Urgency**: MEDIUM
- **Action**: Upstream upgrade to Langfuse v4.76.0
- **Summary**: Upstream update to Langfuse v4.76.0 on Debian 13 Trixie base (`ghcr.io/home-assistant/{arch}-base-debian:trixie`). Dynamic Prisma query engine discovery in `init_config.sh`. Mantis Security review passed clean with Gemini 4 Argon (`rev_25bc18081f`).
- **Status**: active

### [2026-11-04] Maintenance: Upgrade to v4.72.3 (Debian Trixie base)
- **Date**: 2026-11-04
- **Urgency**: HIGH
- **Action**: Runtime platform migration to Debian 13 Trixie
- **Summary**: Migrated base image from Alpine to Debian 13 Trixie (`ghcr.io/home-assistant/{arch}-base-debian:trixie`). Resolved glibc/musl native binding incompatibilities for `@langfuse/native` and Prisma query engine. Eliminated worker crash-loop and constant CPU load.
- **Status**: active

### [2026-11-02] Maintenance: Upgrade to v4.72.0
- **Date**: 2026-11-02
- **Urgency**: MEDIUM
- **Action**: Automated weekly maintenance pipeline run
- **Summary**: Upgraded Langfuse upstream images to v4.72.0. Verified s6-overlay services, pre-flight manifest, and dual Nginx listeners.
- **Security Pass**: Mantis review with Gemini 4 Argon (`gemini-4-argon`) verdict CLEAN.
- **Verification**: Tests and pre-flight mock run passed.
- **Status**: active
