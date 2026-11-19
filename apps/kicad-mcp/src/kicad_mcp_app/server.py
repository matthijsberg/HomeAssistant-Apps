"""Streamable HTTP ASGI server combining Seeed-Studio KiCad MCP + headless KiCad 9 CLI tools."""

from __future__ import annotations

import logging
import sys

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import __version__
from .config import AppConfig, load_config
from .kicad_cli import check_pcbnew_available, get_kicad_version
from .middleware import WorkspaceSecurityMiddleware
from .security import BearerTokenAuthMiddleware, WorkspacePathGuard
from .tools_extra import register_extra_tools

logger = logging.getLogger("kicad_mcp_app")


def build_mcp_server(config: AppConfig, include_upstream: bool = True) -> tuple[FastMCP, WorkspacePathGuard]:
    """Build the FastMCP server with upstream Seeed-Studio tools + our KiCad 9 CLI extensions."""
    guard = WorkspacePathGuard(
        workspace_root=config.workspace_root,
        allowed_roots=config.effective_allowed_roots(),
        path_aliases=config.path_aliases,
    )

    if include_upstream:
        try:
            from kicad_mcp_server.server import mcp as upstream_mcp

            mcp = upstream_mcp
            logger.info("Loaded upstream Seeed-Studio kicad-mcp-server tools.")
        except ImportError as exc:
            logger.warning(
                "Upstream kicad_mcp_server not available (%s); starting with built-in KiCad CLI tools only.",
                exc,
            )
            mcp = FastMCP(
                name="kicad-headless-mcp",
                instructions="Headless KiCad 9 CLI & PCB/Schematic MCP server.",
            )
    else:
        mcp = FastMCP(
            name="kicad-headless-mcp",
            instructions="Headless KiCad 9 CLI & PCB/Schematic MCP server.",
        )

    register_extra_tools(mcp, config, guard)
    mcp.add_middleware(WorkspaceSecurityMiddleware(guard=guard, read_only=config.read_only))
    return mcp, guard


def create_asgi_app(config: AppConfig | None = None, include_upstream: bool = True) -> Starlette:
    """Create the Starlette ASGI app exposing GET /health and Streamable HTTP /mcp."""
    cfg = config or load_config()
    mcp, guard = build_mcp_server(cfg, include_upstream=include_upstream)
    mcp_http_app = mcp.http_app(path="/mcp")

    async def health_endpoint(_request: Request) -> JSONResponse:
        kicad_ver = await get_kicad_version()
        tools = await mcp.list_tools()
        return JSONResponse(
            {
                "status": "ok",
                "service": "kicad-headless-mcp",
                "version": __version__,
                "kicad_cli_version": kicad_ver,
                "pcbnew_available": check_pcbnew_available(),
                "workspace_root": str(guard.workspace_root),
                "read_only": cfg.read_only,
                "tool_count": len(tools),
                "auth_enabled": bool(cfg.bearer_token),
            }
        )

    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Mount("/", app=mcp_http_app),
        ],
        lifespan=mcp_http_app.lifespan,
    )
    app.add_middleware(
        BearerTokenAuthMiddleware,
        bearer_token=cfg.bearer_token,
        public_paths=frozenset({"/health"}),
    )
    return app


def main() -> None:
    """Entrypoint with self-healing startup diagnostics."""
    try:
        cfg = load_config()
        logging.basicConfig(
            level=getattr(logging, cfg.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        app = create_asgi_app(cfg, include_upstream=True)
        logger.info(
            "Starting KiCad Headless MCP v%s on %s:%s (workspace_root=%s, read_only=%s, auth=%s)",
            __version__,
            cfg.host,
            cfg.port,
            cfg.workspace_root,
            cfg.read_only,
            "enabled" if cfg.bearer_token else "disabled",
        )
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=cfg.log_level)
    except Exception as exc:
        print(
            f"\n[FATAL] KiCad Headless MCP failed to start: {exc}\n"
            "Fix check: verify /data/options.json syntax, kicad-cli availability (`kicad-cli --version`),\n"
            "and Python dependencies (`/opt/venv/bin/python3 -m pip check`).",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
