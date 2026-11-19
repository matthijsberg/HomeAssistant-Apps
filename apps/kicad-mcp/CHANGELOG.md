# Changelog

All notable changes to **KiCad Headless MCP** follow Semantic Versioning.

## [0.1.0] - 2026-11-19
### Added
- Initial Home Assistant App release on Ubuntu 26.04 LTS with native headless KiCad 9.x (`kicad-cli` + `pcbnew`).
- Streamable HTTP MCP server (`/mcp`) combining `Seeed-Studio/kicad-mcp-server` with first-class `kicad-cli` tools: `kicad_health`, `list_workspace_projects`, `run_drc_detailed`, `run_erc_detailed`, `export_pcb_2d` (SVG + high-DPI PNG via `rsvg-convert`), `render_pcb_3d_view` (ephemeral `xvfb-run` + Mesa `llvmpipe`), `export_pcb_drill_files`, `export_fab_bundle`, `export_bom_csv`, and `export_step_model`.
- Unauthenticated `/health` endpoint and constant-time Bearer token auth with persistent auto-generated token fallback.
- `WorkspaceSecurityMiddleware` enforcing symlink-safe `allowed_roots` jailing, configurable `path_aliases`, and optional `read_only` mode.
