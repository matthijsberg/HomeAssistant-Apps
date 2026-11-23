"""Unit tests for deterministic KiCad netlist parser and electrical/MCU circuit rule validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp_app.circuit_rules import (
    detect_esp_variant,
    evaluate_circuit_rules,
    parse_eng_value,
    parse_kicad_netlist,
    parse_kicad_pcb_netlist,
    validate_circuit_file,
)

CLEAN_ESP32_S3_NETLIST = """
(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32-S3-WROOM-1") (libsource (lib "RF_Module") (part "ESP32-S3-WROOM-1")))
    (comp (ref "U2") (value "BME280") (libsource (lib "Sensor") (part "BME280")))
    (comp (ref "J1") (value "USB_C_Receptacle") (libsource (lib "Connector") (part "USB_C_Receptacle_USB2.0")))
    (comp (ref "C1") (value "100nF") (libsource (lib "Device") (part "C")))
    (comp (ref "C2") (value "100nF") (libsource (lib "Device") (part "C")))
    (comp (ref "R1") (value "4.7k") (libsource (lib "Device") (part "R")))
    (comp (ref "R2") (value "4k7") (libsource (lib "Device") (part "R")))
    (comp (ref "R3") (value "10k") (libsource (lib "Device") (part "R")))
    (comp (ref "R4") (value "5.1k") (libsource (lib "Device") (part "R")))
    (comp (ref "R5") (value "5.1kΩ") (libsource (lib "Device") (part "R")))
  )
  (nets
    (net (code "1") (name "GND")
      (node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "U2") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "C1") (pin "2") (pintype "passive"))
      (node (ref "C2") (pin "2") (pintype "passive"))
      (node (ref "R4") (pin "2") (pintype "passive"))
      (node (ref "R5") (pin "2") (pintype "passive")))
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
    (net (code "6") (name "USB_CC1")
      (node (ref "J1") (pin "A5") (pinfunction "CC1") (pintype "bidirectional"))
      (node (ref "R4") (pin "1") (pintype "passive")))
    (net (code "7") (name "USB_CC2")
      (node (ref "J1") (pin "B5") (pinfunction "CC2") (pintype "bidirectional"))
      (node (ref "R5") (pin "1") (pintype "passive")))
  )
)
"""

BROKEN_ESP32_NETLIST = """
(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32-WROOM-32") (libsource (lib "RF_Module") (part "ESP32-WROOM-32")))
    (comp (ref "U2") (value "ADS1115") (libsource (lib "Analog_ADC") (part "ADS1115")))
    (comp (ref "U3") (value "MCP3008") (libsource (lib "Analog_ADC") (part "MCP3008")))
    (comp (ref "U4") (value "MAX31865") (libsource (lib "Sensor") (part "MAX31865")))
    (comp (ref "J1") (value "USB_C") (libsource (lib "Connector") (part "USB_C")))
    (comp (ref "R_BAD_STRAP") (value "10k") (libsource (lib "Device") (part "R")))
    (comp (ref "R_I2C_GND") (value "4.7k") (libsource (lib "Device") (part "R")))
  )
  (nets
    (net (code "1") (name "GND")
      (node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "R_I2C_GND") (pin "2") (pintype "passive")))
    (net (code "2") (name "+3V3")
      (node (ref "U1") (pin "2") (pinfunction "3V3") (pintype "power_in"))
      (node (ref "U2") (pin "8") (pinfunction "VDD") (pintype "power_in"))
      (node (ref "R_BAD_STRAP") (pin "1") (pintype "passive")))
    (net (code "3") (name "+5V")
      (node (ref "U1") (pin "10") (pinfunction "GPIO4") (pintype "bidirectional")))
    (net (code "4") (name "EN")
      (node (ref "U1") (pin "3") (pinfunction "EN") (pintype "input")))
    (net (code "5") (name "I2C_SDA")
      (node (ref "U1") (pin "21") (pinfunction "GPIO21") (pintype "bidirectional"))
      (node (ref "U2") (pin "9") (pinfunction "SDA") (pintype "bidirectional"))
      (node (ref "R_I2C_GND") (pin "1") (pintype "passive")))
    (net (code "6") (name "I2C_SCL")
      (node (ref "U1") (pin "22") (pinfunction "GPIO22") (pintype "bidirectional"))
      (node (ref "U2") (pin "10") (pinfunction "SCL") (pintype "input")))
    (net (code "7") (name "STRAP_12")
      (node (ref "U1") (pin "14") (pinfunction "GPIO12") (pintype "bidirectional"))
      (node (ref "R_BAD_STRAP") (pin "2") (pintype "passive")))
    (net (code "8") (name "USB_CC")
      (node (ref "J1") (pin "A5") (pinfunction "CC1") (pintype "bidirectional"))
      (node (ref "J1") (pin "B5") (pinfunction "CC2") (pintype "bidirectional")))
    (net (code "9") (name "SPI_CS_SHARED")
      (node (ref "U3") (pin "10") (pinfunction "CS") (pintype "input"))
      (node (ref "U4") (pin "10") (pinfunction "CS") (pintype "input")))
    (net (code "10") (name "DANGLING_SIG")
      (node (ref "U1") (pin "18") (pinfunction "GPIO18") (pintype "bidirectional")))
  )
)
"""


def test_parse_eng_value() -> None:
    assert parse_eng_value("4.7k") == pytest.approx(4700.0)
    assert parse_eng_value("4k7") == pytest.approx(4700.0)
    assert parse_eng_value("5.1kΩ") == pytest.approx(5100.0)
    assert parse_eng_value("5R1") == pytest.approx(5.1)
    assert parse_eng_value("100nF") == pytest.approx(1e-7)
    assert parse_eng_value("10u") == pytest.approx(1e-5)
    assert parse_eng_value("2.2M") == pytest.approx(2.2e6)
    assert parse_eng_value("not_a_value") is None


def test_clean_esp32_s3_board_passes() -> None:
    model = parse_kicad_netlist(CLEAN_ESP32_S3_NETLIST, source="clean.net")
    assert detect_esp_variant(model) == "esp32-s3"
    report = evaluate_circuit_rules(model, profile="auto")
    assert report["passed"] is True
    assert report["effective_profile"] == "esp32-s3"
    assert report["summary"]["errors"] == 0
    assert report["summary"]["warnings"] == 0
    assert report["findings"] == []


def test_broken_esp32_board_catches_all_domain_bugs() -> None:
    model = parse_kicad_netlist(BROKEN_ESP32_NETLIST, source="broken.net")
    assert detect_esp_variant(model) == "esp32"
    report = evaluate_circuit_rules(model, profile="auto")
    assert report["passed"] is False
    rule_ids = {f["rule_id"] for f in report["findings"]}
    assert "R002_IC_DECOUPLING" in rule_ids
    assert "R003_I2C_PULLUPS" in rule_ids
    assert "R004_VOLTAGE_MISMATCH" in rule_ids
    assert "R005_USBC_CC_PULLDOWNS" in rule_ids
    assert "R006_ESP_STRAPPING_PINS" in rule_ids
    assert "R007_ESP_EN_RESET" in rule_ids
    assert "R008_SPI_BUS" in rule_ids
    assert "R009_SINGLE_PIN_NETS" in rule_ids


@pytest.mark.asyncio
async def test_rules_yaml_overrides(tmp_path: Path) -> None:
    net_file = tmp_path / "broken.net"
    net_file.write_text(BROKEN_ESP32_NETLIST, encoding="utf-8")
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        "disabled_rules:\n"
        "  - R003_I2C_PULLUPS\n"
        "  - R004_VOLTAGE_MISMATCH\n"
        "  - R005_USBC_CC_PULLDOWNS\n"
        "  - R006_ESP_STRAPPING_PINS\n"
        "  - R007_ESP_EN_RESET\n"
        "  - R008_SPI_BUS\n",
        encoding="utf-8",
    )
    report = await validate_circuit_file(netlist_path=net_file, rules_path=rules_file)
    assert report["passed"] is True
    assert report["summary"]["errors"] == 0
    assert report["summary"]["warnings"] >= 1


def test_parse_kicad_pcb_netlist_and_nc_suffix() -> None:
    sample_pcb = """
    (kicad_pcb (version 20240108)
      (net 0 "")
      (net 1 "VDD")
      (net 2 "GND")
      (net 3 "U2_ALERT_NC")
      (footprint "Pkg:IC" (layer "F.Cu")
        (property "Reference" "U1")
        (property "Value" "TMP117")
        (pad "1" smd rect (net 1 "VDD"))
        (pad "2" smd rect (net 2 "GND"))
        (pad "3" smd rect (net 3 "U2_ALERT_NC")))
      (footprint "Pkg:C0603" (layer "F.Cu")
        (property "Reference" "C1")
        (property "Value" "100nF")
        (pad "1" smd rect (net 1 "VDD"))
        (pad "2" smd rect (net 2 "GND")))
    )
    """
    model = parse_kicad_pcb_netlist(sample_pcb, source="board.kicad_pcb")
    assert set(model.components.keys()) == {"U1", "C1"}
    rep = evaluate_circuit_rules(model, profile="sensor-node")
    assert rep["passed"] is True
    assert rep["summary"]["warnings"] == 0

