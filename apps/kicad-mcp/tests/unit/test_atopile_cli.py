"""Unit tests for headless atopile CLI helpers, project scaffolding, and output parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp_app.atopile_cli import (
    ato_add_package,
    ato_init_project,
    parse_ato_output,
)


def test_ato_init_project_templates_and_guards(tmp_path: Path) -> None:
    proj = tmp_path / "esp_node"
    res = ato_init_project(proj, project_name="esp_node", template="esp32_sensor")
    assert res["status"] == "ok"
    assert (proj / "ato.yaml").exists()
    assert (proj / "main.ato").exists()
    assert "i2c = new I2C" in (proj / "main.ato").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        ato_init_project(proj, project_name="esp_node", template="basic", overwrite=False)

    res2 = ato_init_project(proj, project_name="esp_node", template="basic", overwrite=True)
    assert res2["template"] == "basic"

    with pytest.raises(ValueError, match="Invalid project_name"):
        ato_init_project(tmp_path / "bad", project_name="../evil")


def test_parse_ato_output_success_and_picker_auth() -> None:
    sample_ok = """
    │   ✓ Resolving dependencies [0.02s]     │
    │   ✓ Verify electrical design [0.01s]   │
    Build successful!
    """
    parsed_ok = parse_ato_output(sample_ok, "", returncode=0)
    assert parsed_ok["passed"] is True
    assert parsed_ok["auth_required_for_picker"] is False
    assert len(parsed_ok["stages"]) == 2
    assert parsed_ok["stages"][1]["stage"] == "Verify electrical design"

    sample_auth = """
    │   ✓ Verify electrical design [0.01s]   │
    │   ✗ Picking parts [0.08s]              │
    Sign-in required
    Part picking on atopile 0.15.8 requires sign-in.
    """
    parsed_auth = parse_ato_output(sample_auth, "", returncode=1)
    assert parsed_auth["passed"] is False
    assert parsed_auth["auth_required_for_picker"] is True


@pytest.mark.asyncio
async def test_ato_add_package_blocks_flags_and_offline_policy(tmp_path: Path) -> None:
    ato_init_project(tmp_path, project_name="demo", template="basic")

    with pytest.raises(ValueError, match="Invalid atopile package"):
        await ato_add_package(tmp_path, packages=["--upgrade-evil"])

    with pytest.raises(PermissionError, match="allow_network_packages is disabled"):
        await ato_add_package(tmp_path, packages=["atopile/espressif-esp32-s3"], allow_network=False)
