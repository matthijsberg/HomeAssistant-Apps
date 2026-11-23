# KiCad Headless MCP — PRD & Architecture (v0.2.0)

## 1. Objective
Provide a lightweight, headless **KiCad 9 + Electronic Validation & Simulation Streamable HTTP MCP Server** packaged as a generic, open-source Home Assistant App (`slug: kicad_mcp`). Enables AI agents on Home Assistant OS (such as Hermes Agent) to design, electrically validate, simulate, inspect, render, and export complete PCB / MCU / sensor boards — without running any X11 desktop or VNC server.

## 2. End-to-End Agent Design & Validation Pipeline
Every stage is individually callable over MCP and also unified under a single quality-gate tool (`run_design_verification`):
1. **Design-as-Code (`atopile`):** Installed in an isolated Python venv (`/opt/atopile-venv/bin/ato`) on `amd64` (gracefully marked unavailable on `aarch64`) so dependencies never conflict with `fastmcp`/`mcp`/`pcbnew`. Tools: `ato_init_project`, `ato_add_package`, `ato_check` (100% offline electrical/graph/assertion verification), `ato_build`.
2. **Static Electrical & Domain Validation (KiCad ERC + Netlist Rule Checker):** `run_erc_detailed` + `validate_circuit_rules` parsing KiCad S-expression netlists (`kicad-cli sch export netlist --format kicadsexpr`) with built-in profiles (`auto`, `generic`, `esp32`, `esp32-s3`, `esp32-c3`, `esp32-c6`, `sensor-node`) and optional `rules.yaml` overrides (power rails/shorts, IC decoupling, I2C pull-ups, logic-level mismatches, USB-C 5.1 kΩ CC pull-downs, ESP32 strapping pins & EN RC reset, SPI CS conflicts, single-pin dangling nets).
3. **Analog & Mixed-Signal Simulation (`ngspice`):** Native Ubuntu 26.04 `ngspice` headless batch mode (`export_spice_netlist`, `run_spice_simulation`) supporting DC `.op`, transient `.tran`, AC `.ac`, and raw directives with structured numerical metrics and optional pure-Pillow multi-trace PNG waveform plots.
4. **Physical Layout, Visualization & Manufacturing (KiCad 9):** `run_drc_detailed`, `export_pcb_2d`, `render_pcb_3d_view`, `export_pcb_drill_files`, `export_fab_bundle`, `export_bom_csv`, `export_step_model`, plus upstream `Seeed-Studio/kicad-mcp-server` tools.
5. **Unified Verification Gate (`run_design_verification`):** Auto-discovers `ato.yaml`, `.kicad_sch`, `.net`, `sim/*.cir`, `.kicad_pcb`, and `rules.yaml`, executes every applicable stage, and returns a single `pass / warn / fail` JSON report with prioritized action items.

## 3. Architecture & Security
- **Base OS:** `ubuntu:26.04` (LTS) with native KiCad 9.x (`kicad` `--no-install-recommends`), `ngspice`, `librsvg2-bin`, minimal Mesa `llvmpipe` + ephemeral `xvfb-run`, and isolated `/opt/atopile-venv` on `amd64`.
- **No Alpine `BUILD_FROM` Trap:** `Dockerfile` hardcodes `FROM ubuntu:26.04` with `init: false` in `config.yaml`.
- **Transport & Auth:** FastMCP Streamable HTTP at `/mcp` plus unauthenticated `/health` (exposing `kicad_cli`, `pcbnew`, `ngspice`, `atopile` versions/status). Constant-time Bearer token auth (`secrets.compare_digest`).
- **Security Guardrails:**
  - `WorkspaceSecurityMiddleware` jails every path argument (including path lists) via `os.path.realpath()` inside `allowed_roots`, rewrites `path_aliases`, blocks mutating tools (`ato_init_project`, `ato_add_package`, `ato_build`, KiCad edits) when `read_only: true`, and gates registry downloads via `allow_network_packages`.
  - SPICE netlist sanitizer blocks shell escapes and validates `.include`/`.lib` paths against `allowed_roots`.

## 4. Versioning & Release Lifecycle
- SemVer single source of truth in `src/kicad_mcp_app/__init__.py` (`0.2.0`), mirrored in `config.yaml`, `pyproject.toml`, `CHANGELOG.md`, `README.md`, `DOCS.md`.
- Local-first staging to `/addons/kicad-mcp/`, live build on HAOS, runtime verification, real E2E smoke test, and pre-commit secret scan before Git commit/push.
