"""Configuration loader for KiCad Headless MCP Home Assistant App."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PathAlias(BaseModel):
    """Maps a client-visible path prefix to a container-local path prefix."""

    from_prefix: str = Field(alias="from")
    to_prefix: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class AppConfig(BaseModel):
    """Runtime configuration resolved from HA options.json and environment variables."""

    workspace_root: Path = Field(default=Path("/share/kicad"))
    allowed_roots: list[Path] = Field(default_factory=lambda: [Path("/share/kicad")])
    path_aliases: list[PathAlias] = Field(default_factory=list)
    read_only: bool = False
    allow_network_packages: bool = True
    bearer_token: str = ""
    log_level: str = "info"
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    cli_timeout_seconds: int = 120
    render_timeout_seconds: int = 180
    sim_timeout_seconds: int = 120

    def effective_allowed_roots(self) -> list[Path]:
        """Return deduplicated allowed roots, always including workspace_root."""
        roots: list[Path] = []
        seen: set[str] = set()
        for candidate in [self.workspace_root, *self.allowed_roots]:
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                roots.append(candidate)
        return roots


def load_config(options_file: Path | None = None) -> AppConfig:
    """Load AppConfig from /data/options.json (when present) plus environment overrides."""
    opt_path = options_file or Path(os.environ.get("KICAD_MCP_OPTIONS_FILE", "/data/options.json"))
    raw: dict[str, Any] = {}
    if opt_path.exists():
        raw = json.loads(opt_path.read_text(encoding="utf-8"))

    # Environment variable overrides take precedence for testing and container run.sh
    if env_ws := os.environ.get("KICAD_MCP_WORKSPACE_ROOT"):
        raw["workspace_root"] = env_ws
    if env_roots := os.environ.get("KICAD_MCP_ALLOWED_ROOTS"):
        raw["allowed_roots"] = [r.strip() for r in env_roots.split(",") if r.strip()]
    if env_ro := os.environ.get("KICAD_MCP_READ_ONLY"):
        raw["read_only"] = env_ro.strip().lower() in {"1", "true", "yes", "on"}
    if env_net := os.environ.get("KICAD_MCP_ALLOW_NETWORK_PACKAGES"):
        raw["allow_network_packages"] = env_net.strip().lower() in {"1", "true", "yes", "on"}
    if env_token := os.environ.get("KICAD_MCP_BEARER_TOKEN"):
        raw["bearer_token"] = env_token
    if env_log := os.environ.get("KICAD_MCP_LOG_LEVEL"):
        raw["log_level"] = env_log.strip().lower()
    if env_host := os.environ.get("KICAD_MCP_HOST"):
        raw["host"] = env_host
    if env_port := os.environ.get("KICAD_MCP_PORT"):
        raw["port"] = int(env_port)

    return AppConfig.model_validate(raw)
