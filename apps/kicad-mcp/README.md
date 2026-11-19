# KiCad Headless MCP (Home Assistant App)

**Version:** `0.1.1`

A lightweight, headless **KiCad 9 CLI + Streamable HTTP MCP server** for Home Assistant OS — built on **Ubuntu 26.04 LTS** with zero VNC or desktop GUI overhead.

## Capabilities
- **KiCad 9 Headless CLI & `pcbnew`:** Native KiCad 9.x `kicad-cli` and Python `pcbnew` bindings.
- **Validation:** Structured JSON `run_drc_detailed` and `run_erc_detailed` (plus upstream `run_drc` / `run_erc`).
- **2D & 3D Visualization:** Multi-layer or composite 2D PCB SVG + high-DPI PNG export (`F.Cu`, `B.Cu`, `F.SilkS`, `B.SilkS`, `Edge.Cuts`) and headless 3D PNG renders (`render_pcb_3d_view` via ephemeral `xvfb-run` + Mesa `llvmpipe`).
- **Manufacturing & CAD Exports:** Gerbers, Excellon drill + drill maps, CPL position CSV, Gerber ZIP bundles, schematic BOM CSV, and mechanical 3D STEP models.
- **Schematic & PCB Analysis:** Component/net/footprint inspection, pin-level netlist tracing, and routing statistics via `Seeed-Studio/kicad-mcp-server`.
- **Security by Design:** Constant-time Bearer token authentication, symlink-safe `workspace_root` / `allowed_roots` jailing, configurable `path_aliases`, and optional `read_only` mode.

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
