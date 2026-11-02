# Changelog

All notable changes to the Mantis Security Agent are documented in this file.

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
