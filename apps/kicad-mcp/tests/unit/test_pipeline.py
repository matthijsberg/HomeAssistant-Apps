"""Unit tests for the unified design verification pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp_app.pipeline import run_design_verification

CLEAN_NETLIST = """
(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32-S3-WROOM-1") (libsource (lib "RF_Module") (part "ESP32-S3-WROOM-1")))
    (comp (ref "U2") (value "BME280") (libsource (lib "Sensor") (part "BME280")))
    (comp (ref "C1") (value "100nF") (libsource (lib "Device") (part "C")))
    (comp (ref "C2") (value "100nF") (libsource (lib "Device") (part "C")))
    (comp (ref "R1") (value "4.7k") (libsource (lib "Device") (part "R")))
    (comp (ref "R2") (value "4.7k") (libsource (lib "Device") (part "R")))
    (comp (ref "R3") (value "10k") (libsource (lib "Device") (part "R")))
  )
  (nets
    (net (code "1") (name "GND")
      (node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "U2") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "C1") (pin "2") (pintype "passive"))
      (node (ref "C2") (pin "2") (pintype "passive")))
    (net (code "2") (name "+3V3")
      (node (ref "U1") (pin "2") (pinfunction "3V3") (pintype "power_in"))
      (node (ref "U2") (pin "2") (pinfunction "VDD") (pintype "power_in"))
      (node (ref "C1") (pin "1") (pintype "passive"))
      (node (ref "R1") (pin "1") (pintype "passive"))
      (node (ref "R2") (pin "1") (pintype "passive"))
      (node (ref "R3") (pin "1") (pintype "passive")))
    (net (code "3") (name "EN")
      (node (ref "U1") (pin "3") (pinfunction "EN") (pintype "input"))
      (node (ref "R3") (pin "2") (pintype "passive"))
      (node (ref "C2") (pin "1") (pintype "passive")))
    (net (code "4") (name "I2C_SDA")
      (node (ref "U1") (pin "8") (pinfunction "GPIO8") (pintype "bidirectional"))
      (node (ref "U2") (pin "3") (pinfunction "SDA") (pintype "bidirectional"))
      (node (ref "R1") (pin "2") (pintype "passive")))
    (net (code "5") (name "I2C_SCL")
      (node (ref "U1") (pin "9") (pinfunction "GPIO9") (pintype "bidirectional"))
      (node (ref "U2") (pin "4") (pinfunction "SCL") (pintype "input"))
      (node (ref "R2") (pin "2") (pintype "passive")))
  )
)
"""

BROKEN_NETLIST = """
(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32-WROOM-32") (libsource (lib "RF_Module") (part "ESP32-WROOM-32")))
    (comp (ref "U2") (value "BME280") (libsource (lib "Sensor") (part "BME280")))
  )
  (nets
    (net (code "1") (name "GND")
      (node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in")))
    (net (code "2") (name "+3V3")
      (node (ref "U1") (pin "2") (pinfunction "3V3") (pintype "power_in")))
    (net (code "3") (name "+5V")
      (node (ref "U1") (pin "4") (pinfunction "GPIO4") (pintype "bidirectional")))
    (net (code "4") (name "EN")
      (node (ref "U1") (pin "3") (pinfunction "EN") (pintype "input")))
    (net (code "5") (name "I2C_SDA")
      (node (ref "U1") (pin "21") (pinfunction "GPIO21") (pintype "bidirectional"))
      (node (ref "U2") (pin "3") (pinfunction "SDA") (pintype "bidirectional")))
  )
)
"""


@pytest.mark.asyncio
async def test_pipeline_pass_on_clean_netlist(tmp_path: Path) -> None:
    (tmp_path / "board.net").write_text(CLEAN_NETLIST, encoding="utf-8")
    res = await run_design_verification(
        project_dir=tmp_path,
        run_atopile=False,
        run_erc=False,
        run_spice=False,
        run_drc=False,
    )
    assert res["overall_status"] == "pass"
    assert res["passed"] is True
    assert res["stages"]["circuit_rules"]["status"] == "pass"
    assert res["stages"]["atopile_check"]["status"] == "skipped"
    assert res["action_items"] == []


@pytest.mark.asyncio
async def test_pipeline_fail_and_action_items_on_broken_netlist(tmp_path: Path) -> None:
    (tmp_path / "broken.net").write_text(BROKEN_NETLIST, encoding="utf-8")
    res = await run_design_verification(
        project_dir=tmp_path,
        run_atopile=False,
        run_erc=False,
        run_spice=False,
        run_drc=False,
    )
    assert res["overall_status"] == "fail"
    assert res["passed"] is False
    assert res["summary"]["total_errors"] >= 3
    assert len(res["action_items"]) >= 3
