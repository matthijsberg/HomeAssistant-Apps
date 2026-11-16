# OKF v0.2 Knowledge Audit Log — unifi_os_server

- **2026-11-05T09:48:00Z** — `rev_31d890493b`
  - Target: `apps/unifi-os-server/` (v6.0.19-0 EA activation)
  - Diff Snapshot: `diff:74ae20f44964`
  - Reviewer: Mantis Security Agent (Gemini 4 Argon)
  - Verdict: **CLEAN** (0 CWE findings, 0 secrets, least-privilege NET_ADMIN/NET_RAW verified).

- **2026-11-16T20:05:00Z** — `rev_e8c2fc64ed`
  - Target: `apps/unifi-os-server/` (v6.0.21-0 EA live HAOS build + D-Bus/PG14/MongoDB/UUIDv5 runtime fixes)
  - Diff Snapshot: `diff:a5d2264d39b2`
  - Reviewer: Mantis Security Agent
  - Verdict: **CLEAN** (0 CWE findings, 0 secrets, 40.4 KB diff scanned).

- **2026-11-16T20:28:00Z** — `rev_ae9f4fe171`
  - Target: `apps/unifi-os-server/` (UCP4 supervisor shim + MainPID /proc liveness check)
  - Diff Snapshot: `diff:d89fe3137463`
  - Reviewer: Mantis Security Agent
  - Verdict: **CLEAN** (0 CWE findings, 0 secrets, 7.2 KB diff scanned).

- **2026-11-16T21:30:00Z** — `rev_bb0ec9595c`
  - Target: `apps/unifi-os-server/` (HA SSL integration via `userCertificates` IPC API, Early Access rename, PII/path hygiene)
  - Diff Snapshot: `diff:820a8a044fc6`
  - Reviewer: Mantis Security Agent
  - Verdict: **CLEAN** (0 CWE findings, 0 secrets, 13.4 KB diff scanned).

- **2026-11-16T21:42:00Z** — `rev_bf51850b9f`
  - Target: `apps/unifi-os-server/` (Disable in-container UniFi OS / application auto-update schedules on startup)
  - Diff Snapshot: `diff:b9170aaac3db`
  - Reviewer: Mantis Security Agent
  - Verdict: **CLEAN** (0 CWE findings, 0 secrets, 3.9 KB diff scanned).
