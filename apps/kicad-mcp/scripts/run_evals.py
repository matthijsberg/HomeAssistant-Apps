#!/usr/bin/env python3
"""Golden live evaluation suite for KiCad Headless MCP (v0.2.0+).

Evaluates every individual engine AND the unified `run_design_verification` gate
against analytical physics ground truth, single-fault mutation recall, false-positive
precision, real KiCad 9 CLI outputs, real atopile constraint failures, and security
guardrails — using zero mocks against a running Streamable HTTP MCP container.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    eval_id: str
    suite: str
    passed: bool
    duration_s: float
    detail: str


class MCPClient:
    """Minimal stdlib-only Streamable HTTP MCP JSON-RPC client."""

    def __init__(self, base_url: str, bearer_token: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = bearer_token
        self.timeout = timeout
        self.session_id: str | None = None
        self._req_id = 0

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        req = urllib.request.Request(
            f"{self.base_url}/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if sid := resp.headers.get("mcp-session-id"):
                self.session_id = sid
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return None
            for line in raw.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
            return json.loads(raw)

    def initialize(self) -> dict[str, Any]:
        self._req_id += 1
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "kicad-mcp-golden-eval", "version": "1.0"},
                },
            }
        )
        assert resp and "result" in resp, f"Initialize failed: {resp}"
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp["result"]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        self._req_id += 1
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert resp is not None, f"Empty MCP response for {name}"
        if "error" in resp:
            return resp["error"], True
        result = resp.get("result", {})
        is_err = bool(result.get("isError", False))
        text = "\n".join(
            item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"
        )
        try:
            return json.loads(text), is_err
        except json.JSONDecodeError:
            return text, is_err


def _make_clean_esp32_s3_netlist(
    *,
    drop_scl_pullup: bool = False,
    sda_pull_to_gnd: bool = False,
    tie_5v_to_gpio: bool = False,
    short_usbc_cc: bool = False,
    drop_usbc_cc1_pd: bool = False,
    esp_variant: str = "ESP32-S3-WROOM-1",
    pull_high_strap_gpio: str = "",
    float_en: bool = False,
    share_spi_cs: bool = False,
    add_dangling_net: bool = False,
) -> str:
    """Generate a deterministic KiCad S-expression netlist with optional isolated single-fault mutations."""
    comps = [
        f'(comp (ref "U1") (value "{esp_variant}") (libsource (lib "RF_Module") (part "{esp_variant}")))',
        '(comp (ref "U2") (value "BME280") (libsource (lib "Sensor") (part "BME280")))',
        '(comp (ref "J1") (value "USB_C_Receptacle") (libsource (lib "Connector") (part "USB_C_Receptacle_USB2.0")))',
        '(comp (ref "C1") (value "100nF") (libsource (lib "Device") (part "C")))',
        '(comp (ref "C2") (value "100nF") (libsource (lib "Device") (part "C")))',
        '(comp (ref "R1") (value "4.7k") (libsource (lib "Device") (part "R")))',
        '(comp (ref "R2") (value "4.7k") (libsource (lib "Device") (part "R")))',
        '(comp (ref "R3") (value "10k") (libsource (lib "Device") (part "R")))',
        '(comp (ref "R4") (value "5.1k") (libsource (lib "Device") (part "R")))',
        '(comp (ref "R5") (value "5.1k") (libsource (lib "Device") (part "R")))',
    ]
    if pull_high_strap_gpio:
        comps.append('(comp (ref "R_STRAP") (value "10k") (libsource (lib "Device") (part "R")))')
    if share_spi_cs:
        comps.append('(comp (ref "U3") (value "MCP3008") (libsource (lib "Analog_ADC") (part "MCP3008")))')
        comps.append('(comp (ref "U4") (value "MAX31865") (libsource (lib "Sensor") (part "MAX31865")))')

    gnd_nodes = [
        '(node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in"))',
        '(node (ref "U2") (pin "1") (pinfunction "GND") (pintype "power_in"))',
        '(node (ref "C1") (pin "2") (pintype "passive"))',
        '(node (ref "C2") (pin "2") (pintype "passive"))',
        '(node (ref "R5") (pin "2") (pintype "passive"))',
    ]
    if not drop_usbc_cc1_pd:
        gnd_nodes.append('(node (ref "R4") (pin "2") (pintype "passive"))')
    if sda_pull_to_gnd:
        gnd_nodes.append('(node (ref "R1") (pin "1") (pintype "passive"))')

    v33_nodes = [
        '(node (ref "U1") (pin "2") (pinfunction "3V3") (pintype "power_in"))',
        '(node (ref "U2") (pin "2") (pinfunction "VDD") (pintype "power_in"))',
        '(node (ref "C1") (pin "1") (pintype "passive"))',
    ]
    if not sda_pull_to_gnd:
        v33_nodes.append('(node (ref "R1") (pin "1") (pintype "passive"))')
    if not drop_scl_pullup:
        v33_nodes.append('(node (ref "R2") (pin "1") (pintype "passive"))')
    if not float_en:
        v33_nodes.append('(node (ref "R3") (pin "1") (pintype "passive"))')
    if pull_high_strap_gpio:
        v33_nodes.append('(node (ref "R_STRAP") (pin "1") (pintype "passive"))')

    en_nodes = ['(node (ref "U1") (pin "3") (pinfunction "EN") (pintype "input"))']
    if not float_en:
        en_nodes.append('(node (ref "R3") (pin "2") (pintype "passive"))')
        en_nodes.append('(node (ref "C2") (pin "1") (pintype "passive"))')

    sda_nodes = [
        '(node (ref "U1") (pin "8") (pinfunction "GPIO17") (pintype "bidirectional"))',
        '(node (ref "U2") (pin "3") (pinfunction "SDA") (pintype "bidirectional"))',
        '(node (ref "R1") (pin "2") (pintype "passive"))',
    ]
    scl_nodes = [
        '(node (ref "U1") (pin "9") (pinfunction "GPIO18") (pintype "bidirectional"))',
        '(node (ref "U2") (pin "4") (pinfunction "SCL") (pintype "input"))',
    ]
    if not drop_scl_pullup:
        scl_nodes.append('(node (ref "R2") (pin "2") (pintype "passive"))')

    nets = [
        f'(net (code "1") (name "GND") {" ".join(gnd_nodes)})',
        f'(net (code "2") (name "+3V3") {" ".join(v33_nodes)})',
        f'(net (code "3") (name "EN") {" ".join(en_nodes)})',
        f'(net (code "4") (name "I2C_SDA") {" ".join(sda_nodes)})',
        f'(net (code "5") (name "I2C_SCL") {" ".join(scl_nodes)})',
    ]

    if short_usbc_cc:
        nets.append(
            '(net (code "6") (name "USB_CC_SHORT") '
            '(node (ref "J1") (pin "A5") (pinfunction "CC1") (pintype "bidirectional")) '
            '(node (ref "J1") (pin "B5") (pinfunction "CC2") (pintype "bidirectional")) '
            '(node (ref "R4") (pin "1") (pintype "passive")))'
        )
    else:
        cc1_nodes = ['(node (ref "J1") (pin "A5") (pinfunction "CC1") (pintype "bidirectional"))']
        if not drop_usbc_cc1_pd:
            cc1_nodes.append('(node (ref "R4") (pin "1") (pintype "passive"))')
        nets.append(f'(net (code "6") (name "USB_CC1") {" ".join(cc1_nodes)})')
        nets.append(
            '(net (code "7") (name "USB_CC2") '
            '(node (ref "J1") (pin "B5") (pinfunction "CC2") (pintype "bidirectional")) '
            '(node (ref "R5") (pin "1") (pintype "passive")))'
        )

    code = 8
    if tie_5v_to_gpio:
        nets.append(
            f'(net (code "{code}") (name "+5V") '
            '(node (ref "U1") (pin "10") (pinfunction "GPIO4") (pintype "bidirectional")))'
        )
        code += 1
    if pull_high_strap_gpio:
        nets.append(
            f'(net (code "{code}") (name "STRAP_SIG") '
            f'(node (ref "U1") (pin "14") (pinfunction "{pull_high_strap_gpio}") (pintype "bidirectional")) '
            '(node (ref "R_STRAP") (pin "2") (pintype "passive")))'
        )
        code += 1
    if share_spi_cs:
        nets.append(
            f'(net (code "{code}") (name "SPI_CS_SHARED") '
            '(node (ref "U3") (pin "10") (pinfunction "CS") (pintype "input")) '
            '(node (ref "U4") (pin "10") (pinfunction "CS") (pintype "input")))'
        )
        code += 1
    if add_dangling_net:
        nets.append(
            f'(net (code "{code}") (name "TYPO_NET_NAME") '
            '(node (ref "U1") (pin "25") (pinfunction "GPIO25") (pintype "bidirectional")))'
        )

    return "(export (version \"E\")\n  (components\n    " + "\n    ".join(comps) + "\n  )\n  (nets\n    " + "\n    ".join(nets) + "\n  )\n)\n"


MINIMAL_KICAD_SCH = """(kicad_sch
  (version 20231120)
  (generator "kicad_mcp_eval")
  (uuid "11111111-1111-4111-8111-111111111111")
  (paper "A4")
  (lib_symbols
    (symbol "Device:R"
      (pin_numbers hide)
      (pin_names (offset 0))
      (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
      )
    )
  )
  (symbol (lib_id "Device:R") (at 100 100 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "22222222-2222-4222-8222-222222222222")
    (property "Reference" "R1" (at 102 100 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 102 102 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "~" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "33333333-3333-4333-8333-333333333331"))
    (pin "2" (uuid "33333333-3333-4333-8333-333333333332"))
  )
  (symbol (lib_id "Device:R") (at 100 110.16 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "22222222-2222-4222-8222-222222222223")
    (property "Reference" "R2" (at 102 110 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 102 112 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 100 110 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "~" (at 100 110 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "33333333-3333-4333-8333-333333333333"))
    (pin "2" (uuid "33333333-3333-4333-8333-333333333334"))
  )
  (wire (pts (xy 100 103.81) (xy 100 106.35)) (stroke (width 0) (type default)) (uuid "44444444-4444-4444-8444-444444444441"))
  (label "+3V3" (at 100 96.19 0) (fields_autoplaced yes) (effects (font (size 1.27 1.27))) (uuid "55555555-5555-4555-8555-555555555551"))
  (label "V_MID" (at 100 105.08 0) (fields_autoplaced yes) (effects (font (size 1.27 1.27))) (uuid "55555555-5555-4555-8555-555555555552"))
  (label "GND" (at 100 113.97 0) (fields_autoplaced yes) (effects (font (size 1.27 1.27))) (uuid "55555555-5555-4555-8555-555555555553"))
  (sheet_instances (path "/" (page "1")))
)
"""


def run_case(results: list[EvalResult], eval_id: str, suite: str, fn: Any) -> None:
    t0 = time.monotonic()
    try:
        detail = fn()
        results.append(EvalResult(eval_id, suite, True, time.monotonic() - t0, str(detail)))
    except Exception as exc:
        results.append(EvalResult(eval_id, suite, False, time.monotonic() - t0, f"FAIL: {exc}"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden live evaluation suite for KiCad Headless MCP")
    parser.add_argument("--base-url", default="http://local-kicad-mcp:8000")
    parser.add_argument("--token-env", default="KICAD_MCP_BEARER_TOKEN")
    parser.add_argument("--local-work-dir", required=True, help="Local path inside shared workspace for temp eval artifacts")
    parser.add_argument("--mcp-work-dir", required=True, help="Same directory as visible to the MCP container")
    parser.add_argument("--pcb", default="", help="Optional real .kicad_pcb (container path) to include in Suite D DRC eval")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(f"ERROR: Environment variable {args.token_env} is empty.", file=sys.stderr)
        return 2

    local_dir = Path(args.local_work_dir)
    if local_dir.exists():
        shutil.rmtree(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    mcp_dir = args.mcp_work_dir.rstrip("/")

    client = MCPClient(args.base_url, token)
    client.initialize()

    results: list[EvalResult] = []

    # ==================== SUITE A: SPICE PHYSICAL GROUND TRUTH ====================
    def eval_a01() -> str:
        cir = "LiPo Divider\nVbat vbat 0 4.2\nR1 vbat adc 100k\nR2 adc 0 100k\n.end\n"
        res, is_err = client.call_tool("run_spice_simulation", {"netlist_content": cir, "analysis": "op", "probes": ["v(adc)", "i(vbat)"]})
        assert not is_err and res["passed"], f"sim failed: {res}"
        v_adc = res["metrics"]["v(adc)"]
        i_bat = abs(res["metrics"]["i(vbat)"])
        assert abs(v_adc - 2.100) <= 0.01, f"expected 2.100V, got {v_adc}"
        assert abs(i_bat - 21e-6) <= 1e-6, f"expected 21uA, got {i_bat}"
        return f"V_adc={v_adc:.4f}V (exact 2.100V), I={i_bat*1e6:.2f}uA"

    def eval_a02() -> str:
        cir = "EN Reset\nVdd vdd 0 PULSE(0 3.3 0.1m 10u 10u 20m 40m)\nRen vdd en 10k\nCen en 0 100n\n.end\n"
        plot_p = f"{mcp_dir}/a02_en_reset.png"
        res, is_err = client.call_tool("run_spice_simulation", {
            "netlist_content": cir, "analysis": "tran", "probes": ["v(vdd)", "v(en)"],
            "step": "20u", "stop": "6m", "plot_output_path": plot_p,
        })
        assert not is_err and res["passed"], f"sim failed: {res}"
        m = res["metrics"]["v(en)"]
        expected_tr = math.log(9.0) * 10e3 * 100e-9  # 2.1972 ms
        err_pct = abs(m["rise_time_10_90_s"] - expected_tr) / expected_tr * 100.0
        assert err_pct <= 3.0, f"rise time error {err_pct:.2f}% ({m['rise_time_10_90_s']} vs {expected_tr})"
        assert m["final"] >= 3.28, f"final {m['final']} < 3.28V"
        assert res["plot"]["size_bytes"] > 2000
        return f"t_rise={m['rise_time_10_90_s']*1e3:.3f}ms (theory 2.197ms, err {err_pct:.2f}%), PNG={res['plot']['size_bytes']}B"

    def eval_a03() -> str:
        cir = "Sensor LPF\nVin in 0 AC 1\nR1 in filt 1k\nC1 filt 0 100n\n.end\n"
        plot_p = f"{mcp_dir}/a03_lpf_ac.png"
        res, is_err = client.call_tool("run_spice_simulation", {
            "netlist_content": cir, "analysis": "ac", "probes": ["v(filt)"],
            "ac_variation": "dec", "ac_points": 30, "ac_fstart": "10", "ac_fstop": "100k",
            "plot_output_path": plot_p,
        })
        assert not is_err and res["passed"], f"sim failed: {res}"
        m = res["metrics"]["v(filt)"]
        expected_fc = 1.0 / (2.0 * math.pi * 1000.0 * 100e-9)  # 1591.55 Hz
        err_pct = abs(m["cutoff_3db_hz"] - expected_fc) / expected_fc * 100.0
        assert err_pct <= 2.0, f"fc error {err_pct:.2f}% ({m['cutoff_3db_hz']} vs {expected_fc})"
        assert abs(m["dc_or_start_gain_db"]) <= 0.1
        return f"fc={m['cutoff_3db_hz']:.1f}Hz (theory 1591.5Hz, err {err_pct:.2f}%), DC={m['dc_or_start_gain_db']:.4f}dB"

    def eval_a04() -> str:
        # WiFi TX burst: 3.3V source with 1.5 Ohm LDO/trace impedance + bulk cap under 450mA 1ms pulse
        def run_cap(cap_val: str) -> float:
            cir = (
                f"WiFi Burst ({cap_val})\n"
                "Vsrc src 0 3.3\n"
                "Rsrc src rail 1.5\n"
                f"Cbulk rail 0 {cap_val} IC=3.3\n"
                "Iwifi rail 0 PULSE(0.05 0.50 0.5m 10u 10u 1.0m 10m)\n"
                ".end\n"
            )
            res, is_err = client.call_tool("run_spice_simulation", {
                "netlist_content": cir, "analysis": "tran", "probes": ["v(rail)"],
                "step": "20u", "stop": "2.5m",
            })
            assert not is_err and res["passed"], f"sim failed for {cap_val}: {res}"
            return res["metrics"]["v(rail)"]["min"]

        vmin_good = run_cap("1000u")
        vmin_bad = run_cap("1u")
        # Analytical check: 3.3V - 0.05A*1.5Ω = 3.225V initial; 1000uF tau=1.5ms holds ~2.89V vs 1uF dropping to ~2.55V
        assert vmin_good > 2.85, f"1000uF should stay >2.85V, got {vmin_good}"
        assert vmin_bad < 2.65, f"1uF should brown-out <2.65V, got {vmin_bad}"
        assert (vmin_good - vmin_bad) > 0.25, f"Insufficient droop discrimination: {vmin_good} vs {vmin_bad}"
        return f"V_min(1000uF)={vmin_good:.3f}V (safe) vs V_min(1uF)={vmin_bad:.3f}V (brown-out caught, delta={vmin_good-vmin_bad:.3f}V)"

    def eval_a05() -> str:
        for payload in (
            "Bad1\nV1 a 0 3.3\n.control\nshell id\n.endc\n.end",
            'Bad2\n.include "/etc/passwd"\nV1 a 0 3.3\n.end',
            "Bad3\nV1 a 0 3.3\n.control\nwrdata /tmp/escape.txt v(a)\n.endc\n.end",
        ):
            res, is_err = client.call_tool("run_spice_simulation", {"netlist_content": payload, "analysis": "op"})
            assert is_err or (isinstance(res, dict) and not res.get("passed")), f"Security bypass! {res}"
        return "3/3 adversarial SPICE payloads blocked"

    run_case(results, "A01_spice_dc_divider", "A:SPICE", eval_a01)
    run_case(results, "A02_spice_en_rc_reset", "A:SPICE", eval_a02)
    run_case(results, "A03_spice_ac_lpf", "A:SPICE", eval_a03)
    run_case(results, "A04_spice_wifi_brownout", "A:SPICE", eval_a04)
    run_case(results, "A05_spice_security", "A:SPICE", eval_a05)

    # ==================== SUITE B: ATOPILE COMPILER & CONSTRAINTS ====================
    def eval_b01() -> str:
        p_mcp = f"{mcp_dir}/ato_clean"
        res_i, err_i = client.call_tool("ato_init_project", {"project_dir": p_mcp, "project_name": "eval_clean", "template": "esp32_sensor", "overwrite": True})
        assert not err_i and res_i["status"] == "ok"
        res_c, err_c = client.call_tool("ato_check", {"project_dir": p_mcp})
        assert not err_c and res_c["passed"] is True and len(res_c["warnings"]) == 0, f"clean ato failed: {res_c}"
        solved = res_c.get("constraint_solver", {}).get("builds", [{}])[0].get("parameters_solved", 0)
        return f"all stages + offline solver passed ({solved} params solved, 0 warnings)"

    def eval_b02() -> str:
        p_loc = local_dir / "ato_bad_assert"
        p_mcp = f"{mcp_dir}/ato_bad_assert"
        client.call_tool("ato_init_project", {"project_dir": p_mcp, "project_name": "eval_bad_assert", "template": "esp32_sensor", "overwrite": True})
        ato_file = p_loc / "main.ato"
        ato_file.write_text(ato_file.read_text().replace("r_sda.resistance = 4.7kohm +/- 5%", "r_sda.resistance = 100kohm +/- 5%"), encoding="utf-8")
        res_c, err_c = client.call_tool("ato_check", {"project_dir": p_mcp})
        assert not err_c and res_c["passed"] is False, f"expected constraint violation failure, got: {res_c}"
        return "Violated resistance assertion correctly failed build"

    def eval_b03() -> str:
        p_loc = local_dir / "ato_short"
        p_mcp = f"{mcp_dir}/ato_short"
        client.call_tool("ato_init_project", {"project_dir": p_mcp, "project_name": "eval_short", "template": "basic", "overwrite": True})
        ato_file = p_loc / "main.ato"
        ato_file.write_text(ato_file.read_text() + "\n    power.hv ~ power.lv\n", encoding="utf-8")
        res_c, err_c = client.call_tool("ato_check", {"project_dir": p_mcp})
        assert not err_c and res_c["passed"] is False, f"expected power short ERC failure, got: {res_c}"
        return "Direct power.hv~power.lv short caught by faebryk ERC"

    run_case(results, "B01_ato_clean_esp32_sensor", "B:atopile", eval_b01)
    run_case(results, "B02_ato_constraint_violation", "B:atopile", eval_b02)
    run_case(results, "B03_ato_power_short_erc", "B:atopile", eval_b03)

    # ==================== SUITE C: CIRCUIT RULES PRECISION & RECALL ====================
    def eval_c01() -> str:
        f_loc = local_dir / "c01_clean.net"
        f_loc.write_text(_make_clean_esp32_s3_netlist(), encoding="utf-8")
        res, is_err = client.call_tool("validate_circuit_rules", {"netlist_path": f"{mcp_dir}/c01_clean.net"})
        assert not is_err and res["passed"] is True
        assert res["summary"]["errors"] == 0 and res["summary"]["warnings"] == 0, f"false positives: {res['findings']}"
        return f"profile={res['effective_profile']}, 0 errors, 0 warnings (0% FP)"

    def eval_c02() -> str:
        mutations: list[tuple[str, dict[str, Any], str]] = [
            ("missing_scl_pullup", {"drop_scl_pullup": True}, "R003_I2C_PULLUPS"),
            ("sda_pull_to_gnd", {"sda_pull_to_gnd": True}, "R003_I2C_PULLUPS"),
            ("5v_on_esp32_gpio", {"tie_5v_to_gpio": True}, "R004_VOLTAGE_MISMATCH"),
            ("usbc_cc_shorted", {"short_usbc_cc": True}, "R005_USBC_CC_PULLDOWNS"),
            ("usbc_cc1_missing_pd", {"drop_usbc_cc1_pd": True}, "R005_USBC_CC_PULLDOWNS"),
            ("esp32_gpio12_high", {"esp_variant": "ESP32-WROOM-32", "pull_high_strap_gpio": "GPIO12"}, "R006_ESP_STRAPPING_PINS"),
            ("esp32s3_gpio45_high", {"esp_variant": "ESP32-S3-WROOM-1", "pull_high_strap_gpio": "GPIO45"}, "R006_ESP_STRAPPING_PINS"),
            ("esp32_en_floating", {"float_en": True}, "R007_ESP_EN_RESET"),
            ("spi_shared_cs", {"share_spi_cs": True}, "R008_SPI_BUS"),
            ("dangling_single_pin", {"add_dangling_net": True}, "R009_SINGLE_PIN_NETS"),
        ]
        caught = 0
        for label, kwargs, expected_rule in mutations:
            fname = f"mut_{label}.net"
            (local_dir / fname).write_text(_make_clean_esp32_s3_netlist(**kwargs), encoding="utf-8")
            res, is_err = client.call_tool("validate_circuit_rules", {"netlist_path": f"{mcp_dir}/{fname}"})
            assert not is_err, f"tool error on {label}: {res}"
            found_ids = {f["rule_id"] for f in res["findings"]}
            assert expected_rule in found_ids, f"MISSED {expected_rule} on {label}; got {found_ids}"
            caught += 1
        return f"{caught}/{len(mutations)} isolated single-fault bugs caught (100% recall)"

    run_case(results, "C01_clean_zero_false_positives", "C:Rules", eval_c01)
    run_case(results, "C02_single_fault_10x_recall", "C:Rules", eval_c02)

    # ==================== SUITE D: UNIFIED PIPELINE & REAL KICAD INTEGRATION ====================
    def eval_d01() -> str:
        sch_dir = local_dir / "kicad_sch_eval"
        sch_dir.mkdir(exist_ok=True)
        (sch_dir / "divider.kicad_sch").write_text(MINIMAL_KICAD_SCH, encoding="utf-8")
        sch_mcp = f"{mcp_dir}/kicad_sch_eval/divider.kicad_sch"

        erc, err1 = client.call_tool("run_erc_detailed", {"schematic_path": sch_mcp})
        assert not err1 and "summary" in erc, f"ERC failed: {erc}"

        exp, err2 = client.call_tool("export_spice_netlist", {"schematic_path": sch_mcp, "output_path": f"{mcp_dir}/kicad_sch_eval/divider.cir"})
        assert not err2 and exp["status"] == "ok" and exp["size_bytes"] > 20, f"SPICE export failed: {exp}"

        rc, err3 = client.call_tool("validate_circuit_rules", {"schematic_path": sch_mcp})
        assert not err3 and rc["summary"]["components"] == 2 and any(n.endswith("GND") for n in rc["summary"]["gnd_nets"]), f"Rules on .kicad_sch failed: {rc}"
        return f"KiCad .kicad_sch -> ERC + SPICE export ({exp['size_bytes']}B) + Rules (2 comps, +3V3/GND parsed)"

    def eval_d02() -> str:
        p_loc = local_dir / "full_pass_proj"
        p_mcp = f"{mcp_dir}/full_pass_proj"
        (p_loc / "sim").mkdir(parents=True, exist_ok=True)
        client.call_tool("ato_init_project", {"project_dir": p_mcp, "project_name": "full_pass", "template": "esp32_sensor", "overwrite": True})
        (p_loc / "board.net").write_text(_make_clean_esp32_s3_netlist(), encoding="utf-8")
        (p_loc / "sim" / "divider.cir").write_text("Divider\nV1 in 0 3.3\nR1 in out 10k\nR2 out 0 10k\n.end\n", encoding="utf-8")

        kwargs: dict[str, Any] = {
            "project_dir": p_mcp,
            "run_atopile": True,
            "run_erc": False,
            "run_circuit_rules": True,
            "run_spice": True,
            "run_drc": bool(args.pcb),
        }
        if args.pcb:
            kwargs["pcb_path"] = args.pcb
        res, is_err = client.call_tool("run_design_verification", kwargs)
        assert not is_err and res["overall_status"] == "pass" and res["summary"]["total_errors"] == 0 and res["summary"]["total_warnings"] == 0, f"Gate failed: {res}"
        return f"overall=pass, stages={res['summary']['executed_stages']}, 0 err / 0 warn"

    def eval_d03() -> str:
        p_loc = local_dir / "full_fail_proj"
        p_mcp = f"{mcp_dir}/full_fail_proj"
        (p_loc / "sim").mkdir(parents=True, exist_ok=True)
        client.call_tool("ato_init_project", {"project_dir": p_mcp, "project_name": "full_fail", "template": "esp32_sensor", "overwrite": True})
        # Fault 1: violated atopile assertion
        ato_f = p_loc / "main.ato"
        ato_f.write_text(ato_f.read_text().replace("r_en.resistance = 10kohm +/- 5%", "r_en.resistance = 1kohm +/- 5%"), encoding="utf-8")
        # Fault 2: missing I2C pull-up + floating EN in netlist
        (p_loc / "board.net").write_text(_make_clean_esp32_s3_netlist(drop_scl_pullup=True, float_en=True), encoding="utf-8")
        # Fault 3: singular/broken SPICE netlist (unreferenced model)
        (p_loc / "sim" / "broken.cir").write_text("Broken\nQ1 c b e NONEXISTENT_MODEL\n.end\n", encoding="utf-8")

        res, is_err = client.call_tool("run_design_verification", {
            "project_dir": p_mcp,
            "run_atopile": True,
            "run_erc": False,
            "run_circuit_rules": True,
            "run_spice": True,
            "run_drc": False,
        })
        assert not is_err and res["overall_status"] == "fail" and res["passed"] is False
        failed_stages = [k for k, v in res["stages"].items() if v["status"] == "fail"]
        assert set(failed_stages) == {"atopile_check", "circuit_rules", "spice_simulations"}, f"expected all 3 stages to fail, got {failed_stages}"
        action_stages = {a["stage"] for a in res["action_items"]}
        assert action_stages == {"atopile_check", "circuit_rules", "spice_simulations"}, f"action_items missing stage: {action_stages}"
        return f"overall=fail, all 3 faulty stages flagged with {len(res['action_items'])} actionable items"

    def eval_d04() -> str:
        for tool, arg in (
            ("validate_circuit_rules", {"netlist_path": "/etc/passwd"}),
            ("ato_check", {"project_dir": "/etc"}),
            ("run_spice_simulation", {"netlist_path": "/etc/passwd", "analysis": "op"}),
            ("run_design_verification", {"project_dir": "/etc"}),
        ):
            res, is_err = client.call_tool(tool, arg)
            txt = json.dumps(res) if not isinstance(res, str) else res
            assert is_err or "Access denied" in txt or "outside allowed workspace" in txt, f"Traversal allowed on {tool}: {txt}"
        return "4/4 new MCP tools enforced WorkspacePathGuard jailing"

    run_case(results, "D01_kicad_sch_erc_spice_rules", "D:Pipeline", eval_d01)
    run_case(results, "D02_unified_gate_clean_pass", "D:Pipeline", eval_d02)
    run_case(results, "D03_unified_gate_3fault_fail", "D:Pipeline", eval_d03)
    run_case(results, "D04_security_path_jailing", "D:Pipeline", eval_d04)

    if not args.keep_artifacts and local_dir.exists():
        shutil.rmtree(local_dir)

    passed_n = sum(1 for r in results if r.passed)
    total_n = len(results)
    print(f"\n=== KiCad Headless MCP Golden Evaluation Scorecard: {passed_n}/{total_n} PASSED ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.eval_id:<32} ({r.duration_s:5.2f}s) | {r.detail}")

    return 0 if passed_n == total_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
