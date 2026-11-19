"""Unit tests for AppConfig loading and generic defaults."""

from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp_app.config import load_config


def test_load_config_generic_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KICAD_MCP_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("KICAD_MCP_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("KICAD_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("KICAD_MCP_READ_ONLY", raising=False)

    cfg = load_config(options_file=tmp_path / "missing.json")
    assert cfg.workspace_root == Path("/share/kicad")
    assert cfg.allowed_roots == [Path("/share/kicad")]
    assert cfg.path_aliases == []
    assert cfg.read_only is False
    assert cfg.port == 8000


def test_load_config_from_options_and_env_override(tmp_path: Path, monkeypatch) -> None:
    opts = tmp_path / "options.json"
    opts.write_text(
        json.dumps(
            {
                "workspace_root": str(tmp_path / "projects"),
                "allowed_roots": [str(tmp_path / "projects"), str(tmp_path / "extra")],
                "path_aliases": [{"from": "/client/proj", "to": str(tmp_path / "projects")}],
                "read_only": True,
                "bearer_token": "file-token",
                "log_level": "debug",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KICAD_MCP_BEARER_TOKEN", "env-override-token")

    cfg = load_config(options_file=opts)
    assert cfg.workspace_root == tmp_path / "projects"
    assert len(cfg.effective_allowed_roots()) == 2
    assert cfg.path_aliases[0].from_prefix == "/client/proj"
    assert cfg.path_aliases[0].to_prefix == str(tmp_path / "projects")
    assert cfg.read_only is True
    assert cfg.bearer_token == "env-override-token"
    assert cfg.log_level == "debug"
