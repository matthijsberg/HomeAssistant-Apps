"""Security guardrails: workspace path jailing, read-only policy, and Bearer auth."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import PathAlias

# Tools that mutate KiCad project / schematic / PCB source files.
MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "create_kicad_project",
        "add_component_from_library",
        "add_wire",
        "add_label",
        "setup_pcb_layout",
        "download_part",
        "install_part",
        "modify_schematic",
        "edit_schematic",
        "ato_init_project",
        "ato_add_package",
        "ato_build",
    }
)

# Argument names considered filesystem paths across upstream and custom tools.
PATH_ARG_EXACT: frozenset[str] = frozenset(
    {
        "path",
        "file_path",
        "filepath",
        "pcb_path",
        "schematic_path",
        "project_path",
        "project_dir",
        "ato_dir",
        "output_path",
        "output_dir",
        "directory",
        "target_dir",
        "netlist_path",
        "bom_path",
        "report_path",
        "rules_path",
        "plot_output_path",
        "spice_netlists",
    }
)

PATH_ARG_SUFFIXES: tuple[str, ...] = ("_path", "_dir", "_file", "_directory")


class PathSecurityError(ValueError):
    """Raised when a requested path escapes allowed workspace roots."""


class ReadOnlyPolicyError(PermissionError):
    """Raised when a mutating tool is invoked while read_only=True."""


def is_path_argument(arg_name: str) -> bool:
    """Return True if an MCP tool argument name represents a filesystem path."""
    lower = arg_name.lower()
    return lower in PATH_ARG_EXACT or lower.endswith(PATH_ARG_SUFFIXES)


class WorkspacePathGuard:
    """Resolves aliases and jails all file/directory arguments within allowed roots."""

    def __init__(
        self,
        workspace_root: Path,
        allowed_roots: list[Path],
        path_aliases: list[PathAlias] | None = None,
    ) -> None:
        self.workspace_root = Path(os.path.realpath(str(workspace_root)))
        resolved_roots: list[Path] = []
        seen: set[str] = set()
        for root in [workspace_root, *allowed_roots]:
            real = Path(os.path.realpath(str(root)))
            key = str(real)
            if key not in seen:
                seen.add(key)
                resolved_roots.append(real)
        self.allowed_roots = resolved_roots
        # Longest-prefix-first matching prevents shorter aliases shadowing nested ones
        self.path_aliases = sorted(
            path_aliases or [],
            key=lambda a: len(a.from_prefix.rstrip("/")),
            reverse=True,
        )

    def _apply_alias(self, raw_path: str) -> str:
        normalized = raw_path.strip()
        for alias in self.path_aliases:
            src = alias.from_prefix.rstrip("/")
            dst = alias.to_prefix.rstrip("/")
            if not src:
                continue
            if normalized == src:
                return dst
            if normalized.startswith(src + "/"):
                return dst + normalized[len(src) :]
        return normalized

    def resolve_and_validate(self, raw_path: str) -> Path:
        """Resolve an input path (relative or aliased) and assert it stays inside allowed_roots."""
        if not raw_path or not raw_path.strip():
            raise PathSecurityError("Empty path is not allowed.")
        if "\x00" in raw_path:
            raise PathSecurityError("Null byte in path is not allowed.")

        rewritten = self._apply_alias(raw_path)
        candidate = Path(rewritten)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        # Resolve symlinks even if the final file does not yet exist by resolving the full path
        resolved = Path(os.path.realpath(str(candidate)))

        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue

        allowed_str = ", ".join(str(r) for r in self.allowed_roots)
        raise PathSecurityError(
            f"Access denied: '{raw_path}' resolves to '{resolved}', "
            f"which is outside allowed workspace roots ({allowed_str})."
        )

    def sanitize_arguments(self, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Return a copy of tool arguments with all non-empty path fields validated and resolved."""
        if not arguments:
            return {}
        sanitized = dict(arguments)
        for key, value in arguments.items():
            if not is_path_argument(key):
                continue
            if value is None:
                continue
            if isinstance(value, str):
                if not value.strip():
                    continue
                sanitized[key] = str(self.resolve_and_validate(value))
            elif isinstance(value, list):
                sanitized[key] = [
                    str(self.resolve_and_validate(item)) if isinstance(item, str) and item.strip() else item
                    for item in value
                ]
        return sanitized


def check_read_only_policy(tool_name: str, read_only: bool) -> None:
    """Block mutating tools when read_only mode is enabled."""
    if read_only and tool_name in MUTATING_TOOLS:
        raise ReadOnlyPolicyError(
            f"Tool '{tool_name}' is disabled because KiCad Headless MCP is running in read_only mode. "
            "Set 'read_only: false' in add-on options to enable source-file edits."
        )


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Constant-time Bearer token guard for HTTP MCP routes (leaves /health open)."""

    def __init__(self, app: Any, bearer_token: str, public_paths: frozenset[str] | None = None) -> None:
        super().__init__(app)
        self._token = bearer_token
        self._public_paths = public_paths or frozenset({"/health"})

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in self._public_paths or not self._token:
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        if not auth_header:
            return JSONResponse(
                {"error": "unauthorized", "detail": "Missing Authorization header"},
                status_code=401,
            )

        parts = auth_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                {"error": "unauthorized", "detail": "Invalid Authorization header format"},
                status_code=401,
            )

        if not secrets.compare_digest(parts[1].strip(), self._token):
            return JSONResponse(
                {"error": "forbidden", "detail": "Invalid bearer token"},
                status_code=403,
            )

        return await call_next(request)
