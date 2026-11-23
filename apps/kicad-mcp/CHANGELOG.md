# Changelog

All notable changes to **KiCad Headless MCP** follow Semantic Versioning.

## [0.2.0] - 2026-11-23
### Added
- **Design-as-Code (`atopile` 0.15.9):** Installed in an isolated `/opt/atopile-venv` on `amd64` (gracefully unavailable on `aarch64`) with MCP tools `ato_init_project`, `ato_add_package`, `ato_check` (100% offline electrical/graph/assertion verification), and `ato_build`.
- **Deterministic Electrical & MCU Rule Checker (`validate_circuit_rules`):** Parses KiCad S-expression netlists (`kicadsexpr`) and checks power rails, IC decoupling, I2C pull-ups, 5 V/3.3 V voltage mismatches, USB-C 5.1 kΩ CC1/CC2 pull-downs, ESP32/S3/C3/C6 strapping pins & EN RC-reset circuits, SPI CS contention, and single-pin dangling nets — with built-in profiles and optional per-project `rules.yaml` overrides.
- **Headless Analog & Mixed-Signal Simulation (`ngspice`):** Native Ubuntu 26.04 `ngspice` integration via `export_spice_netlist` and `run_spice_simulation` (`op`, `tran`, `ac`, `raw`) with structured engineering metrics (min/max/mean/ripple, 10–90% rise time, AC -3 dB cutoff), security sanitization of netlists/`.include` paths, and pure-Pillow multi-trace PNG waveform plotting.
- **Unified Agent Verification Gate (`run_design_verification`):** Single-call orchestration across `atopile` → KiCad ERC → Circuit Rules → `ngspice` → KiCad DRC returning a consolidated `pass / warn / fail` report and prioritized action items.
- New HA App options `allow_network_packages` and `sim_timeout_seconds`; `/health` and `kicad_health` now expose `ngspice_version` and `atopile_version`.

## [0.1.1] - 2026-11-19
### Security
- Raised minimum dependency floors to `Pillow>=13.0.0,<14` and `starlette>=1.3.1,<2`, remediating all 30 Dependabot CVE floor alerts while keeping `mcp<2` and `fastmcp<4` aligned with `Seeed-Studio/kicad-mcp-server`.

## [0.1.0] - 2026-11-19
### Added
- Initial Home Assistant App release on Ubuntu 26.04 LTS with native headless KiCad 9.x (`kicad-cli` + `pcbnew`).
- Streamable HTTP MCP server (`/mcp`) combining `Seeed-Studio/kicad-mcp-server` with first-class `kicad-cli` tools: `kicad_health`, `list_workspace_projects`, `run_drc_detailed`, `run_erc_detailed`, `export_pcb_2d` (SVG + high-DPI PNG via `rsvg-convert`), `render_pcb_3d_view` (ephemeral `xvfb-run` + Mesa `llvmpipe`), `export_pcb_drill_files`, `export_fab_bundle`, `export_bom_csv`, and `export_step_model`.
- Unauthenticated `/health` endpoint and constant-time Bearer token auth with persistent auto-generated token fallback.
- `WorkspaceSecurityMiddleware` enforcing symlink-safe `allowed_roots` jailing, configurable `path_aliases`, and optional `read_only` mode.
