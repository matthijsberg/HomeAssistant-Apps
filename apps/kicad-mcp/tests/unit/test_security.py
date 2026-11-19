"""Unit tests for workspace path jailing, symlink escape prevention, aliases, and read-only policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp_app.config import PathAlias
from kicad_mcp_app.security import (
    PathSecurityError,
    ReadOnlyPolicyError,
    WorkspacePathGuard,
    check_read_only_policy,
    is_path_argument,
)


def test_relative_and_alias_resolution(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    board = ws / "sensor" / "board.kicad_pcb"
    board.parent.mkdir(parents=True)
    board.write_text("(kicad_pcb)", encoding="utf-8")

    guard = WorkspacePathGuard(
        workspace_root=ws,
        allowed_roots=[ws],
        path_aliases=[PathAlias(**{"from": "/config/projects", "to": str(ws)})],
    )

    assert guard.resolve_and_validate("sensor/board.kicad_pcb") == board.resolve()
    assert guard.resolve_and_validate("/config/projects/sensor/board.kicad_pcb") == board.resolve()
    assert guard.resolve_and_validate(str(board)) == board.resolve()


def test_blocks_path_traversal_and_outside_paths(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")

    guard = WorkspacePathGuard(workspace_root=ws, allowed_roots=[ws])

    with pytest.raises(PathSecurityError):
        guard.resolve_and_validate("../secret.txt")
    with pytest.raises(PathSecurityError):
        guard.resolve_and_validate("/etc/passwd")
    with pytest.raises(PathSecurityError):
        guard.resolve_and_validate("ok/../../secret.txt")
    with pytest.raises(PathSecurityError):
        guard.resolve_and_validate("bad\x00path")


def test_blocks_symlink_escape(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "private.kicad_pcb"
    secret.write_text("(kicad_pcb)", encoding="utf-8")

    link = ws / "escape_link"
    link.symlink_to(outside)

    guard = WorkspacePathGuard(workspace_root=ws, allowed_roots=[ws])
    with pytest.raises(PathSecurityError):
        guard.resolve_and_validate("escape_link/private.kicad_pcb")


def test_sanitize_arguments_only_rewrites_path_keys(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    guard = WorkspacePathGuard(
        workspace_root=ws,
        allowed_roots=[ws],
        path_aliases=[PathAlias(**{"from": "/client", "to": str(ws)})],
    )

    sanitized = guard.sanitize_arguments(
        {
            "pcb_path": "/client/a.kicad_pcb",
            "output_dir": "out",
            "side": "top",
            "layers": ["F.Cu", "B.Cu"],
            "empty_path": "",
        }
    )
    assert sanitized["pcb_path"] == str((ws / "a.kicad_pcb").resolve())
    assert sanitized["output_dir"] == str((ws / "out").resolve())
    assert sanitized["side"] == "top"
    assert sanitized["layers"] == ["F.Cu", "B.Cu"]
    assert sanitized["empty_path"] == ""


def test_read_only_policy_blocks_mutating_tools() -> None:
    check_read_only_policy("run_drc_detailed", read_only=True)
    check_read_only_policy("add_wire", read_only=False)
    with pytest.raises(ReadOnlyPolicyError):
        check_read_only_policy("add_wire", read_only=True)
    with pytest.raises(ReadOnlyPolicyError):
        check_read_only_policy("create_kicad_project", read_only=True)


def test_is_path_argument() -> None:
    assert is_path_argument("pcb_path")
    assert is_path_argument("output_dir")
    assert is_path_argument("schematic_file")
    assert not is_path_argument("layers")
    assert not is_path_argument("dpi")
