"""Integration tests for Streamable HTTP MCP server, Bearer auth, and /health endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from kicad_mcp_app.config import AppConfig
from kicad_mcp_app.server import create_asgi_app


@pytest.mark.asyncio
async def test_health_and_bearer_auth_and_mcp_handshake(tmp_path: Path) -> None:
    dummy_auth = "unit-auth-fixture"
    cfg = AppConfig(
        workspace_root=tmp_path,
        allowed_roots=[tmp_path],
        read_only=True,
        bearer_token=dummy_auth,
    )
    app = create_asgi_app(cfg, include_upstream=False)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. /health is public
            r_health = await client.get("/health")
            assert r_health.status_code == 200
            body = r_health.json()
            assert body["status"] == "ok"
            assert body["read_only"] is True
            assert body["auth_enabled"] is True
            assert body["tool_count"] >= 10

            # 2. /mcp rejects missing or invalid bearer tokens
            mcp_init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            }
            headers_base = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }

            r_no_auth = await client.post("/mcp", json=mcp_init, headers=headers_base)
            assert r_no_auth.status_code == 401

            r_bad_auth = await client.post(
                "/mcp",
                json=mcp_init,
                headers={**headers_base, "Authorization": "Bearer wrong-token"},
            )
            assert r_bad_auth.status_code == 403

            # 3. Valid bearer token completes MCP initialize + tools/list
            auth_headers = {**headers_base, "Authorization": f"Bearer {cfg.bearer_token}"}
            r_init = await client.post("/mcp", json=mcp_init, headers=auth_headers)
            assert r_init.status_code == 200
            session_id = r_init.headers.get("mcp-session-id")

            # Parse JSON or SSE payload
            text = r_init.text
            if "data: " in text:
                data_line = next(line[6:] for line in text.splitlines() if line.startswith("data: "))
                init_json = json.loads(data_line)
            else:
                init_json = r_init.json()
            assert "result" in init_json
            assert init_json["result"]["serverInfo"]["name"] == "kicad-headless-mcp"

            list_headers = dict(auth_headers)
            if session_id:
                list_headers["mcp-session-id"] = session_id

            # Send initialized notification
            await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=list_headers,
            )

            r_tools = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=list_headers,
            )
            assert r_tools.status_code == 200
            tools_text = r_tools.text
            if "data: " in tools_text:
                data_line = next(
                    line[6:] for line in tools_text.splitlines() if line.startswith("data: ")
                )
                tools_json = json.loads(data_line)
            else:
                tools_json = r_tools.json()
            tool_names = {t["name"] for t in tools_json["result"]["tools"]}
            assert "kicad_health" in tool_names
            assert "run_drc_detailed" in tool_names
            assert "export_pcb_2d" in tool_names
            assert "render_pcb_3d_view" in tool_names
            assert "export_step_model" in tool_names


@pytest.mark.asyncio
async def test_upstream_tools_loaded_and_middleware_jails_paths(tmp_path: Path) -> None:
    dummy_auth = "upstream-auth-fixture"
    cfg = AppConfig(
        workspace_root=tmp_path,
        allowed_roots=[tmp_path],
        read_only=True,
        bearer_token=dummy_auth,
    )
    app = create_asgi_app(cfg, include_upstream=True)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r_health = await client.get("/health")
            assert r_health.status_code == 200
            body = r_health.json()
            # Upstream Seeed-Studio (~30+ tools) + our 10 extra tools
            assert body["tool_count"] >= 35

            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.bearer_token}",
            }
            r_init = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "1.0"},
                    },
                },
                headers=headers,
            )
            assert r_init.status_code == 200
            sid = r_init.headers.get("mcp-session-id")
            if sid:
                headers["mcp-session-id"] = sid
            await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=headers,
            )

            # Attempt path traversal on an upstream tool -> must be blocked by middleware
            r_escape = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "run_drc_detailed",
                        "arguments": {"pcb_path": "/etc/passwd"},
                    },
                },
                headers=headers,
            )
            assert r_escape.status_code == 200
            assert "Access denied" in r_escape.text or "outside allowed workspace" in r_escape.text

            # Attempt read-only blocked tool -> must be blocked by middleware
            r_ro = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "create_kicad_project",
                        "arguments": {"project_name": "nope", "project_dir": str(tmp_path)},
                    },
                },
                headers=headers,
            )
            assert r_ro.status_code == 200
            assert "read_only" in r_ro.text
