# Home Assistant App: KiCad Headless MCP

## Overview
Runs headless KiCad 9 (`kicad-cli` + `pcbnew`) and exposes a **Streamable HTTP MCP** endpoint at `http://local-kicad-mcp:8000/mcp` alongside a health endpoint at `http://local-kicad-mcp:8000/health`.

## Configuration Options

- **`workspace_root`**: Default base directory for KiCad projects (default: `/share/kicad`). Relative paths passed to MCP tools resolve inside this directory.
- **`allowed_roots`**: List of container directories the MCP server is permitted to access. Any path resolving outside these directories (including via symlinks or `..`) is rejected.
- **`path_aliases`**: Optional list of `{from, to}` prefix rewrites so another container (for example an AI agent add-on mounting its own `addon_config` as `/config`) can pass its own paths transparently.
- **`read_only`**: Set to `true` to disable schematic/PCB editing tools while keeping analysis, DRC/ERC, renders, and fabrication exports enabled.
- **`bearer_token`**: Static Bearer token for `/mcp`. Leave blank to auto-generate a persistent 256-bit token at `/data/bearer_token.txt` (`chmod 600`).
- **`log_level`**: `debug`, `info`, `warning`, or `error`.
- **`cli_timeout_seconds`**: Timeout for `kicad-cli` operations (default: `120`).
- **`render_timeout_seconds`**: Timeout for headless 3D PCB renders (default: `180`).

## Connecting an MCP Client (Example)
```yaml
mcp_servers:
  kicad:
    url: http://local-kicad-mcp:8000/mcp
    headers:
      Authorization: Bearer <your-token>
    timeout: 180
    connect_timeout: 30
```
