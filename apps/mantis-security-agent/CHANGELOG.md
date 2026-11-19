# Changelog

All notable changes to the Mantis Security Agent are documented in this file.

## [1.1.3] - 2026-11-19

### Changed
- Consolidated Dependabot Python dependency updates (compatible with `semgrep==1.185.0`): `fastapi==0.141.1` (`starlette==1.10.0`), `uvicorn==0.54.0`, `pydantic==2.14.3`, `httpx==0.28.1`, `httpx-sse==0.4.3`, `semgrep==1.185.0`, `pyyaml==6.0.3`, `yamllint==1.38.0`, `aiofiles==25.1.0`, `jsonschema==4.25.1`, `python-multipart==0.0.34`.

## [1.1.2] - 2026-11-16

### Added
- OpenRouter provider support (including `z-ai/glm-5.3`), provider credential/base URL resolution from `APP_OPTIONS["providers"]` / environment, and executive deep AI assessment in audit reports.
- `auto_approve_scheduled_paths` add-on option (default `[]`) allowing unattended scheduled audits only for explicitly allow-listed paths.

### Changed
- Excluded `.venv`, `node_modules`, `.git`, `vendor`, and cache directories from snapshot hashing and Semgrep SAST scans, and capped file reads at 512 KB.
- Limited inline triage patch synthesis to top 5 CRITICAL/HIGH/ERROR findings per run.

## [1.1.1] - 2026-11-02

### Changed
- Dependency security reconciliation: upgraded `jinja2` to `3.1.6` and `python-multipart` to `0.0.33`, remediating 32 dependency CVEs.
- Removed unused external `mcp` SDK dependency in favor of native FastAPI JSON-RPC MCP implementation, resolving version constraint deadlock with `semgrep`.
- Verified clean build and full test suite pass (13/13 tests) against Python 3.11 Debian Bookworm target.
- Verified zero CVEs and clean security audit via OSV.dev.

## [1.1.0] - 2026-10-13

### Added
- Native MCP JSON-RPC 2.0 interface supporting synchronous diff reviews (`mantis_review_diff`) and security campaigns.
- Open Knowledge Format (OKF v0.2) integration with automated concept extraction.
- Gitleaks v8.24.0 integration for deterministic secret scanning.
