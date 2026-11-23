# KiCad Headless MCP (Home Assistant App)

**Version:** `0.2.0`

A lightweight, headless **KiCad 9 + Electronic Validation & Simulation Streamable HTTP MCP server** for Home Assistant OS — built on **Ubuntu 26.04 LTS** with zero VNC or desktop GUI overhead.

## Capabilities
- **Design-as-Code (`atopile`):** `ato_init_project`, `ato_add_package`, `ato_check` (100% offline electrical & constraint verification), and `ato_build` (isolated venv on `amd64`).
- **Circuit & MCU Rule Validation:** `validate_circuit_rules` runs deterministic netlist checks for power rails, IC decoupling, I2C pull-ups, 5 V/3.3 V mismatches, USB-C 5.1 kΩ CC pull-downs, ESP32/S3/C3/C6 strapping pins & EN RC-reset, SPI CS conflicts, and dangling nets — with `rules.yaml` overrides.
- **Analog & Mixed-Signal Simulation (`ngspice`):** `export_spice_netlist` and `run_spice_simulation` (`op`, `tran`, `ac`, `raw`) returning structured metrics + optional pure-Pillow PNG waveform plots.
- **Unified Agent Verification Gate:** `run_design_verification` chains `atopile` → KiCad ERC → Circuit Rules → `ngspice` → KiCad DRC in a single MCP call.
- **KiCad 9 Headless CLI & `pcbnew`:** Structured JSON `run_drc_detailed` / `run_erc_detailed`, 2D SVG/PNG layers, 3D PNG renders (ephemeral `xvfb-run` + Mesa `llvmpipe`), Gerbers, Excellon drill, CPL, BOM CSV, STEP, and upstream `Seeed-Studio/kicad-mcp-server` tools.
- **Security by Design:** Constant-time Bearer token auth, symlink-safe `workspace_root` / `allowed_roots` jailing, configurable `path_aliases`, `read_only` mode, `allow_network_packages` toggle, and SPICE netlist sanitization.

## Quickstart (Home Assistant)
1. Sync or install the add-on (`slug: kicad_mcp`) in Home Assistant OS.
2. Configure `workspace_root` and `allowed_roots` (defaults to `/share/kicad`; optionally configure `path_aliases` if another add-on accesses the same files under a different mount prefix).
3. Start the app and verify `GET http://local-kicad-mcp:8000/health`.
4. Connect any Streamable HTTP MCP client to `http://local-kicad-mcp:8000/mcp` with header `Authorization: Bearer <token>`.

## Local Development
```bash
./scripts/setup.sh
./scripts/demo.sh
```
