"""Unit tests for KiCad CLI report parsers and input validation."""

from __future__ import annotations

import pytest

from kicad_mcp_app.kicad_cli import parse_drc_json, parse_erc_json, validate_layer_names


def test_parse_drc_json_counts_violations_unconnected_and_excluded() -> None:
    report = {
        "kicad_version": "9.0.8",
        "source": "board.kicad_pcb",
        "date": "2026-11-19",
        "violations": [
            {
                "type": "clearance",
                "severity": "error",
                "excluded": False,
                "description": "Clearance violation",
                "items": [{"description": "Pad 1", "pos": {"x": 10.0, "y": 20.0}}],
            },
            {
                "type": "silk_over_copper",
                "severity": "warning",
                "excluded": False,
                "description": "Silkscreen clipped",
                "items": [],
            },
            {
                "type": "courtyard_overlap",
                "severity": "error",
                "excluded": True,
                "description": "Waived overlap",
                "items": [],
            },
        ],
        "unconnected_items": [
            {
                "type": "unconnected_items",
                "severity": "error",
                "excluded": False,
                "description": "Unconnected pad",
                "items": [],
            }
        ],
        "schematic_parity": [],
    }
    parsed = parse_drc_json(report)
    assert parsed["passed"] is False
    assert parsed["summary"]["errors"] == 2
    assert parsed["summary"]["warnings"] == 1
    assert parsed["summary"]["excluded"] == 1
    assert parsed["summary"]["violations_count"] == 3
    assert parsed["summary"]["unconnected_count"] == 1


def test_parse_erc_json_handles_kicad9_and_10_sheets_layout() -> None:
    report = {
        "kicad_version": "9.0.8",
        "source": "main.kicad_sch",
        "sheets": [
            {
                "path": "/",
                "violations": [
                    {
                        "type": "power_pin_not_driven",
                        "severity": "error",
                        "excluded": False,
                        "description": "Input Power pin not driven",
                        "items": [],
                    }
                ],
            }
        ],
    }
    parsed = parse_erc_json(report)
    assert parsed["passed"] is False
    assert parsed["summary"]["errors"] == 1
    assert parsed["violations"][0]["sheet"] == "/"


def test_validate_layer_names() -> None:
    assert validate_layer_names(["F.Cu", " B.Cu ", "F.SilkS"]) == ["F.Cu", "B.Cu", "F.SilkS"]
    with pytest.raises(ValueError):
        validate_layer_names([])
    with pytest.raises(ValueError):
        validate_layer_names(["F.Cu; rm -rf /"])
