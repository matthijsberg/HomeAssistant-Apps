# KiCad Headless MCP — PRD & Architecture (v0.1.1)

## 1. Objective
Provide a lightweight, headless **KiCad 9 CLI + Streamable HTTP MCP Server** packaged as a generic, open-source Home Assistant App (`slug: kicad_mcp`). Enables AI agents on Home Assistant OS (such as Hermes Agent) to inspect, validate (ERC/DRC), render (2D SVG/PNG layers and 3D PNG), and export manufacturing artifacts (Gerbers, Excellon drills, CPL, BOM, STEP) on shared KiCad projects while the designer uses native KiCad 9 on their desktop/laptop — without running any X11 desktop or VNC server.

## 2. Architecture
- **Base OS:** `ubuntu:26.04` (LTS) with native KiCad 9.x (`kicad` `--no-install-recommends`, skipping multi-GB 3D libraries and docs), `librsvg2-bin` (`rsvg-convert`) for crisp 2D SVG→PNG rasterization, and minimal Mesa `llvmpipe` + ephemeral `xvfb-run` invoked **only** for `kicad-cli pcb render`.
- **No Alpine `BUILD_FROM` Trap:** `Dockerfile` hardcodes `FROM ubuntu:26.04` with `init: false` in `config.yaml`.
- **MCP Stack:** Pure Python (`python3 -m venv --system-site-packages /opt/venv` to inherit KiCad's native `pcbnew` bindings), combining:
  - Upstream `Seeed-Studio/kicad-mcp-server` (MIT, pinned commit) for schematic/PCB analysis, netlist tracing, pin analysis, and KiCad 9/10 parsers.
  - First-class `kicad_mcp_app` extensions: `kicad_health`, `list_workspace_projects`, `run_drc_detailed`, `run_erc_detailed`, `export_pcb_2d` (SVG + PNG), `render_pcb_3d_view`, `export_pcb_drill_files`, `export_fab_bundle`, `export_bom_csv`, `export_step_model`.
- **Transport & Auth:** FastMCP Streamable HTTP mounted at `/mcp` plus unauthenticated `/health` for container healthchecks. Constant-time Bearer token auth (`secrets.compare_digest`), auto-generating a persistent 256-bit `0600` token at `/data/bearer_token.txt` if `options.bearer_token` is blank.
- **Security Guardrails:**
  - `WorkspaceSecurityMiddleware` intercepts every MCP tool call (upstream + built-in).
  - Resolves configurable `path_aliases` and relative paths against `workspace_root`, then enforces `os.path.realpath()` containment inside `allowed_roots` (blocking path traversal and symlink escapes).
  - Optional `read_only: true` mode blocks source-mutating tools while keeping inspection, DRC/ERC, and export tools operational.

## 3. Versioning & Release Lifecycle
- 4-tier SemVer starting at `0.1.0`; promoted to `1.0.0` at stable production go-live.
- Single source of truth in `src/kicad_mcp_app/__init__.py` mirrored in `config.yaml`, `pyproject.toml`, `CHANGELOG.md`, `README.md`.
- Local-first staging to `/addons/kicad-mcp/`, live build, runtime RAM/log inspection, real `kicad-cli` E2E test, and pre-commit secret scan before Git commit/push.
