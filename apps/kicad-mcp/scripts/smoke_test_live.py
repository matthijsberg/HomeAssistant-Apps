#!/usr/bin/env python3
"""Live end-to-end smoke test against a running KiCad Headless MCP Streamable HTTP server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any


def parse_mcp_response(raw: str) -> dict[str, Any]:
    """Parse either JSON or SSE-wrapped JSON-RPC payload from Streamable HTTP."""
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(raw)


def mcp_post(
    base_url: str,
    token: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    timeout: int = 240,
) -> tuple[dict[str, Any] | None, str | None]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["mcp-session-id"] = session_id

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        new_sid = resp.headers.get("mcp-session-id") or session_id
        raw = resp.read().decode("utf-8")
        if not raw.strip():
            return None, new_sid
        return parse_mcp_response(raw), new_sid


def call_tool(
    base_url: str,
    token: str,
    session_id: str | None,
    req_id: int,
    name: str,
    arguments: dict[str, Any],
) -> tuple[str, bool]:
    resp, _ = mcp_post(
        base_url,
        token,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        session_id=session_id,
    )
    assert resp is not None, f"Empty response for {name}"
    if "error" in resp:
        return json.dumps(resp["error"], indent=2), True
    result = resp.get("result", {})
    is_err = bool(result.get("isError", False))
    parts: list[str] = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        else:
            parts.append(f"[{item.get('type')}]")
    return "\n".join(parts), is_err


def main() -> int:
    parser = argparse.ArgumentParser(description="Live E2E smoke test for KiCad Headless MCP")
    parser.add_argument("--base-url", default="http://local-kicad-mcp:8000")
    parser.add_argument("--pcb", required=True, help="Path to a real .kicad_pcb file")
    parser.add_argument("--out-dir", required=True, help="Output directory for smoke test artifacts")
    parser.add_argument("--token-env", default="KICAD_MCP_BEARER_TOKEN")
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(f"ERROR: Environment variable {args.token_env} is empty.", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")

    # 1. /health
    with urllib.request.urlopen(f"{base}/health", timeout=15) as r:
        health = json.loads(r.read().decode("utf-8"))
    print("=== 1. /health ===")
    print(json.dumps(health, indent=2))

    # 2. MCP initialize + tools/list
    init_resp, sid = mcp_post(
        base,
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "kicad-mcp-e2e", "version": "1.0"},
            },
        },
    )
    assert init_resp is not None and "result" in init_resp, f"Initialize failed: {init_resp}"
    print("\n=== 2. MCP Initialize ===")
    print("serverInfo:", init_resp["result"].get("serverInfo"), "session:", bool(sid))

    mcp_post(base, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id=sid)
    tools_resp, sid = mcp_post(
        base,
        token,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=sid,
    )
    assert tools_resp is not None
    tool_names = sorted(t["name"] for t in tools_resp["result"]["tools"])
    print(f"tools/list count: {len(tool_names)}")
    print("tools:", ", ".join(tool_names))

    out_dir = args.out_dir.rstrip("/")
    failures: list[str] = []

    checks = [
        (3, "kicad_health", {}),
        (4, "run_drc_detailed", {"pcb_path": args.pcb, "output_path": f"{out_dir}/drc_report.json"}),
        (5, "get_pcb_statistics", {"file_path": args.pcb}),
        (
            6,
            "export_pcb_2d",
            {
                "pcb_path": args.pcb,
                "layers": ["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"],
                "output_dir": f"{out_dir}/2d_layers",
                "mode": "multi",
                "rasterize_png": True,
                "dpi": 900,
            },
        ),
        (
            7,
            "export_pcb_2d",
            {
                "pcb_path": args.pcb,
                "layers": ["F.Cu", "F.SilkS", "Edge.Cuts"],
                "output_dir": f"{out_dir}/2d_composite",
                "mode": "single",
                "rasterize_png": True,
                "dpi": 900,
            },
        ),
        (
            8,
            "render_pcb_3d_view",
            {
                "pcb_path": args.pcb,
                "output_path": f"{out_dir}/3d_top.png",
                "side": "top",
                "width": 1600,
                "height": 900,
                "quality": "basic",
            },
        ),
        (
            9,
            "render_pcb_3d_view",
            {
                "pcb_path": args.pcb,
                "output_path": f"{out_dir}/3d_iso.png",
                "side": "top",
                "rotate": "-35,0,25",
                "perspective": True,
                "width": 1600,
                "height": 900,
                "quality": "basic",
            },
        ),
        (
            10,
            "export_step_model",
            {
                "pcb_path": args.pcb,
                "output_path": f"{out_dir}/board.step",
                "board_only": False,
            },
        ),
    ]

    for req_id, tool_name, tool_args in checks:
        text, is_err = call_tool(base, token, sid, req_id, tool_name, tool_args)
        print(f"\n=== {req_id}. tools/call: {tool_name} (isError={is_err}) ===")
        print(text[:2500])
        if is_err:
            failures.append(tool_name)

    if failures:
        print(f"\nFAILED TOOLS: {failures}", file=sys.stderr)
        return 1

    print("\nALL E2E CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
