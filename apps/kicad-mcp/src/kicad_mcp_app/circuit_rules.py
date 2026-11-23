"""Deterministic KiCad netlist parser and electrical/MCU domain rule validator."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .kicad_cli import find_kicad_cli, run_command

VALID_PROFILES: frozenset[str] = frozenset(
    {"auto", "generic", "esp32", "esp32-s3", "esp32-c3", "esp32-c6", "sensor-node"}
)

GND_NET_RE = re.compile(r"^(/?)(gnd|gndd|gnda|agnd|dgnd|pgnd|vss|com|0v)$", re.IGNORECASE)
POWER_NET_RE = re.compile(
    r"^(/?)(\+?[0-9]+(\.[0-9]+)?v[a-z0-9_]*|vcc[a-z0-9_]*|vdd[a-z0-9_]*|vbat[a-z0-9_]*|vbus[a-z0-9_]*|vin[a-z0-9_]*|vsys[a-z0-9_]*|3v3[a-z0-9_]*|5v[a-z0-9_]*|1v8[a-z0-9_]*|12v[a-z0-9_]*)$",
    re.IGNORECASE,
)
HIGH_VOLTAGE_5V_RE = re.compile(r"(^|[/_+\-])(5v|5v0|vbus|usb_5v|12v|24v)($|[/_a-z0-9])", re.IGNORECASE)
RAIL_3V3_RE = re.compile(r"(^|[/_+\-])(3v3|3\.3v|vdd_3v3|vcc_3v3)($|[/_a-z0-9])", re.IGNORECASE)
UNCONNECTED_NET_RE = re.compile(r"^(unconnected-|nc$|/nc$|.*_nc$)", re.IGNORECASE)

# Known ESP32-family strapping pins & boot-mode risk notes.
ESP_STRAPPING_PINS: dict[str, dict[str, str]] = {
    "esp32": {
        "GPIO0": "Boot mode (LOW enters download mode); avoid hard pulldown without boot button.",
        "GPIO2": "Must be floating/LOW for serial download; avoid hard pullup.",
        "GPIO12": "MTDI selects internal flash voltage (HIGH sets 1.8V and breaks 3.3V flash!).",
        "GPIO15": "MTDO controls ROM boot log output; avoid conflicting hard pulls.",
    },
    "esp32-s3": {
        "GPIO0": "Boot mode (LOW enters download mode); avoid hard pulldown without boot button.",
        "GPIO3": "JTAG signal source strapping pin; check pull state.",
        "GPIO45": "VDD_SPI voltage select (HIGH selects 1.8V and breaks 3.3V flash!).",
        "GPIO46": "ROM print / download boot strapping pin (must not be pulled HIGH at boot).",
    },
    "esp32-c3": {
        "GPIO2": "Must be HIGH at boot for normal SPI flash boot.",
        "GPIO8": "Must be HIGH during download boot; keep pulled up or safe.",
        "GPIO9": "Boot mode (LOW enters download mode); avoid hard pulldown without boot button.",
    },
    "esp32-c6": {
        "GPIO8": "Boot strapping pin; keep compatible with normal/download boot.",
        "GPIO9": "Boot mode (LOW enters download mode); avoid hard pulldown without boot button.",
        "GPIO15": "JTAG strapping pin; verify pull state.",
    },
}

SI_MULTIPLIERS: dict[str, float] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "r": 1.0,
    "R": 1.0,
    "k": 1e3,
    "K": 1e3,
    "meg": 1e6,
    "M": 1e6,
    "g": 1e9,
    "G": 1e9,
}


@dataclass
class Component:
    ref: str
    value: str
    footprint: str = ""
    lib: str = ""
    part: str = ""
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class NetNode:
    ref: str
    pin: str
    pinfunction: str = ""
    pintype: str = ""


@dataclass
class Net:
    code: str
    name: str
    nodes: list[NetNode] = field(default_factory=list)


@dataclass
class NetlistModel:
    source: str
    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)

    def nets_for_component(self, ref: str) -> list[tuple[Net, NetNode]]:
        hits: list[tuple[Net, NetNode]] = []
        for net in self.nets.values():
            for node in net.nodes:
                if node.ref == ref:
                    hits.append((net, node))
        return hits


@dataclass
class RuleFinding:
    rule_id: str
    severity: str  # "error" | "warning" | "info"
    title: str
    message: str
    nets: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "nets": self.nets,
            "components": self.components,
            "recommendation": self.recommendation,
        }


def parse_eng_value(raw: str) -> float | None:
    """Parse engineering component values like '4.7k', '4k7', '5.1kΩ', '100nF', '10u', '5R1'."""
    if not raw:
        return None
    text = raw.strip().split()[0]
    text = re.sub(r"(ohms?|ohm|Ω|farads?|f|h|v|a)$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None

    # European R/k/K/M/u/n/p inline decimal notation (e.g. 4k7, 4K7, 5R1, 2u2)
    m_inline = re.fullmatch(r"([0-9]+)(meg|[pnuµμmrRkKMG])([0-9]+)", text)
    if m_inline:
        whole, prefix, frac = m_inline.groups()
        mult = SI_MULTIPLIERS.get(prefix)
        if mult is not None:
            return float(f"{whole}.{frac}") * mult

    m_std = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(meg|[pnuµμmrRkKMG])?", text)
    if m_std:
        num_s, prefix = m_std.groups()
        num = float(num_s)
        if not prefix:
            return num
        mult = SI_MULTIPLIERS.get(prefix)
        if mult is not None:
            return num * mult
    return None


def parse_sexpr(text: str) -> list[Any]:
    """Minimal recursive S-expression parser for KiCad netlist (.net) files."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            buf: list[str] = []
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1  # consume closing quote
            tokens.append('"' + "".join(buf) + '"')
            continue
        start = i
        while i < n and not text[i].isspace() and text[i] not in "()":
            i += 1
        tokens.append(text[start:i])

    idx = 0

    def _read() -> Any:
        nonlocal idx
        if idx >= len(tokens):
            raise ValueError("Unexpected EOF while parsing S-expression.")
        tok = tokens[idx]
        idx += 1
        if tok == "(":
            lst: list[Any] = []
            while idx < len(tokens) and tokens[idx] != ")":
                lst.append(_read())
            if idx >= len(tokens):
                raise ValueError("Unclosed '(' in S-expression.")
            idx += 1  # consume ')'
            return lst
        if tok == ")":
            raise ValueError("Unexpected ')' in S-expression.")
        if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
            return tok[1:-1]
        return tok

    out: list[Any] = []
    while idx < len(tokens):
        out.append(_read())
    return out


def _find_children(node: list[Any], tag: str) -> list[list[Any]]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _child_scalar(node: list[Any], tag: str, default: str = "") -> str:
    for c in node[1:]:
        if isinstance(c, list) and len(c) >= 2 and c[0] == tag and isinstance(c[1], str):
            return c[1]
    return default


def parse_kicad_netlist(netlist_text: str, source: str = "netlist") -> NetlistModel:
    """Parse a KiCad S-expression netlist string into a structured NetlistModel."""
    parsed = parse_sexpr(netlist_text)
    if not parsed or not isinstance(parsed[0], list) or parsed[0][0] != "export":
        raise ValueError("Invalid KiCad S-expression netlist (expected top-level '(export ...)').")
    root = parsed[0]
    model = NetlistModel(source=source)

    for comps_block in _find_children(root, "components"):
        for comp in _find_children(comps_block, "comp"):
            ref = _child_scalar(comp, "ref")
            if not ref:
                continue
            value = _child_scalar(comp, "value")
            footprint = _child_scalar(comp, "footprint")
            lib = ""
            part = ""
            for ls in _find_children(comp, "libsource"):
                lib = _child_scalar(ls, "lib")
                part = _child_scalar(ls, "part")
            props: dict[str, str] = {}
            for prop in _find_children(comp, "property"):
                pname = _child_scalar(prop, "name")
                pval = _child_scalar(prop, "value")
                if pname:
                    props[pname] = pval
            model.components[ref] = Component(
                ref=ref,
                value=value,
                footprint=footprint,
                lib=lib,
                part=part,
                properties=props,
            )

    for nets_block in _find_children(root, "nets"):
        for net_expr in _find_children(nets_block, "net"):
            code = _child_scalar(net_expr, "code")
            name = _child_scalar(net_expr, "name")
            nodes: list[NetNode] = []
            for nd in _find_children(net_expr, "node"):
                n_ref = _child_scalar(nd, "ref")
                n_pin = _child_scalar(nd, "pin")
                if n_ref:
                    nodes.append(
                        NetNode(
                            ref=n_ref,
                            pin=n_pin,
                            pinfunction=_child_scalar(nd, "pinfunction"),
                            pintype=_child_scalar(nd, "pintype"),
                        )
                    )
            if name:
                model.nets[name] = Net(code=code, name=name, nodes=nodes)

    return model


def parse_kicad_pcb_netlist(pcb_text: str, source: str = "pcb") -> NetlistModel:
    """Extract a NetlistModel directly from a KiCad 7/8/9 .kicad_pcb file (for PCB-first workflows)."""
    parsed = parse_sexpr(pcb_text)
    if not parsed or not isinstance(parsed[0], list) or parsed[0][0] != "kicad_pcb":
        raise ValueError("Invalid KiCad PCB file (expected top-level '(kicad_pcb ...)').")
    root = parsed[0]
    model = NetlistModel(source=source)

    # Top-level (net <code_str> "<name>")
    for net_expr in _find_children(root, "net"):
        if len(net_expr) >= 3 and isinstance(net_expr[1], str) and isinstance(net_expr[2], str):
            code, name = net_expr[1], net_expr[2]
            if name:
                model.nets[name] = Net(code=code, name=name, nodes=[])

    # Top-level (footprint "<fp_name>" ... (property "Reference" "U1") (pad "1" ... (net 7 "SHLD1")))
    for fp in _find_children(root, "footprint"):
        fp_name = fp[1] if len(fp) >= 2 and isinstance(fp[1], str) else ""
        ref = ""
        val = ""
        for prop in _find_children(fp, "property"):
            if len(prop) >= 3 and isinstance(prop[1], str) and isinstance(prop[2], str):
                if prop[1] == "Reference":
                    ref = prop[2]
                elif prop[1] == "Value":
                    val = prop[2]
        # KiCad 7 fallback: (fp_text reference "U1" ...)
        for fpt in _find_children(fp, "fp_text"):
            if len(fpt) >= 3 and isinstance(fpt[1], str) and isinstance(fpt[2], str):
                if fpt[1] == "reference" and not ref:
                    ref = fpt[2]
                elif fpt[1] == "value" and not val:
                    val = fpt[2]
        if not ref:
            continue
        model.components[ref] = Component(ref=ref, value=val, footprint=fp_name, part=val or fp_name)

        seen_pad_nets: set[tuple[str, str]] = set()
        for pad in _find_children(fp, "pad"):
            pad_num = pad[1] if len(pad) >= 2 and isinstance(pad[1], str) else ""
            if not pad_num:
                continue
            for pnet in _find_children(pad, "net"):
                if len(pnet) >= 3 and isinstance(pnet[1], str) and isinstance(pnet[2], str):
                    ncode, nname = pnet[1], pnet[2]
                    if not nname:
                        continue
                    key = (pad_num, nname)
                    if key in seen_pad_nets:
                        continue
                    seen_pad_nets.add(key)
                    if nname not in model.nets:
                        model.nets[nname] = Net(code=ncode, name=nname, nodes=[])
                    model.nets[nname].nodes.append(NetNode(ref=ref, pin=pad_num))

    return model


def is_gnd_net(name: str, extra_gnd: set[str] | None = None) -> bool:
    if extra_gnd and name in extra_gnd:
        return True
    return bool(GND_NET_RE.match(name.strip()))


def is_power_net(name: str, extra_power: set[str] | None = None) -> bool:
    if extra_power and name in extra_power:
        return True
    return bool(POWER_NET_RE.match(name.strip()))


def detect_esp_variant(model: NetlistModel) -> str | None:
    """Detect ESP32 chip family from component values/libparts."""
    blob = " ".join(f"{c.value} {c.part} {c.lib}" for c in model.components.values()).lower()
    if "esp32-s3" in blob or "esp32s3" in blob:
        return "esp32-s3"
    if "esp32-c6" in blob or "esp32c6" in blob:
        return "esp32-c6"
    if "esp32-c3" in blob or "esp32c3" in blob:
        return "esp32-c3"
    if "esp32" in blob:
        return "esp32"
    return None


def _is_resistor(comp: Component) -> bool:
    return bool(re.match(r"^R[0-9_]", comp.ref, re.IGNORECASE))


def _is_capacitor(comp: Component) -> bool:
    return bool(re.match(r"^C[0-9_]", comp.ref, re.IGNORECASE))


def _is_active_ic(comp: Component) -> bool:
    if not re.match(r"^U[0-9_]", comp.ref, re.IGNORECASE):
        return False
    # Exclude passive/mechanical/test symbols sometimes prefixed U
    return "testpoint" not in comp.part.lower()


def _is_esp_component(comp: Component) -> bool:
    return "esp32" in f"{comp.value} {comp.part} {comp.lib}".lower()


def _other_net_of_two_pin(model: NetlistModel, ref: str, current_net: str) -> str | None:
    nets = [net.name for net, _node in model.nets_for_component(ref) if net.name != current_net]
    return nets[0] if nets else None


def load_rules_config(rules_path: Path | None) -> dict[str, Any]:
    """Load optional per-project rules.yaml overrides."""
    if rules_path is None:
        return {}
    if not rules_path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_path}")
    raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def evaluate_circuit_rules(
    model: NetlistModel,
    profile: str = "auto",
    rules_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all deterministic electrical & domain validation rules on a parsed NetlistModel."""
    cfg = rules_cfg or {}
    req_profile = str(cfg.get("profile", profile)).strip().lower()
    if req_profile not in VALID_PROFILES:
        raise ValueError(f"Invalid profile '{req_profile}'. Choose one of {sorted(VALID_PROFILES)}.")

    detected_esp = detect_esp_variant(model)
    effective_profile = detected_esp if (req_profile == "auto" and detected_esp) else (
        "generic" if req_profile == "auto" else req_profile
    )

    disabled = {str(r).upper() for r in (cfg.get("disabled_rules") or [])}
    severity_overrides = {str(k).upper(): str(v).lower() for k, v in (cfg.get("severity_overrides") or {}).items()}
    extra_gnd = set(cfg.get("extra_gnd_nets") or [])
    extra_power = set(cfg.get("extra_power_nets") or [])
    i2c_min_ohm = float(cfg.get("i2c_pullup_min_ohm", 1000.0))
    i2c_max_ohm = float(cfg.get("i2c_pullup_max_ohm", 20000.0))

    findings: list[RuleFinding] = []

    def add_finding(finding: RuleFinding) -> None:
        rid = finding.rule_id.upper()
        if rid in disabled:
            return
        if rid in severity_overrides:
            finding.severity = severity_overrides[rid]
        findings.append(finding)

    gnd_nets = [n for n in model.nets if is_gnd_net(n, extra_gnd)]
    power_nets = [n for n in model.nets if is_power_net(n, extra_power) and not is_gnd_net(n, extra_gnd)]

    # --- R001: Power Rail Presence ---
    if not gnd_nets:
        add_finding(
            RuleFinding(
                rule_id="R001_POWER_RAILS",
                severity="error",
                title="No ground (GND) net detected",
                message="Netlist has no recognized ground net (GND/VSS/AGND/DGND).",
                recommendation="Add a ground reference net (e.g. GND) connected to all return pins.",
            )
        )
    if not power_nets:
        add_finding(
            RuleFinding(
                rule_id="R001_POWER_RAILS",
                severity="warning",
                title="No positive supply rail detected",
                message="Netlist has no recognized positive supply net (3V3/5V/VCC/VDD/VBUS/VBAT).",
                recommendation="Verify power net naming or add custom rails in rules.yaml (extra_power_nets).",
            )
        )

    # --- R002: IC Decoupling Capacitors ---
    decoupled_rails: set[str] = set()
    for comp in model.components.values():
        if not _is_capacitor(comp):
            continue
        comp_nets = {net.name for net, _nd in model.nets_for_component(comp.ref)}
        if any(is_gnd_net(n, extra_gnd) for n in comp_nets):
            for n in comp_nets:
                if is_power_net(n, extra_power) and not is_gnd_net(n, extra_gnd):
                    decoupled_rails.add(n)

    for comp in model.components.values():
        if not _is_active_ic(comp):
            continue
        ic_power_rails = {
            net.name
            for net, node in model.nets_for_component(comp.ref)
            if is_power_net(net.name, extra_power)
            and not is_gnd_net(net.name, extra_gnd)
            and (
                "power" in node.pintype.lower()
                or any(tok in node.pinfunction.lower() for tok in ("vcc", "vdd", "3v3", "vin", "vbat", "vsys"))
                or not node.pinfunction
            )
        }
        missing_rails = sorted(r for r in ic_power_rails if r not in decoupled_rails)
        if missing_rails:
            add_finding(
                RuleFinding(
                    rule_id="R002_IC_DECOUPLING",
                    severity="warning",
                    title=f"Missing decoupling capacitor on {comp.ref} ({comp.value})",
                    message=f"Active IC {comp.ref} draws from rail(s) {missing_rails} with no capacitor connected between that rail and GND.",
                    nets=missing_rails,
                    components=[comp.ref],
                    recommendation="Place a 100 nF ceramic decoupling capacitor close to each IC VDD/VCC pin.",
                )
            )

    # --- R003: I2C Pull-Ups & Bus Health ---
    i2c_nets: list[str] = []
    for net in model.nets.values():
        net_l = net.name.lower()
        pin_has_i2c = any(
            re.search(r"\b(sda|scl)\b", nd.pinfunction, re.IGNORECASE)
            for nd in net.nodes
        )
        if re.search(r"(^|[/_])(i2c[0-9]*_?)?(sda|scl)($|[/_0-9])", net_l) or pin_has_i2c:
            i2c_nets.append(net.name)

    for net_name in sorted(set(i2c_nets)):
        net = model.nets[net_name]
        pullups: list[tuple[Component, str, float | None]] = []
        pulldowns: list[Component] = []
        for nd in net.nodes:
            comp = model.components.get(nd.ref)
            if comp and _is_resistor(comp):
                other = _other_net_of_two_pin(model, comp.ref, net_name)
                if other and is_power_net(other, extra_power) and not is_gnd_net(other, extra_gnd):
                    pullups.append((comp, other, parse_eng_value(comp.value)))
                elif other and is_gnd_net(other, extra_gnd):
                    pulldowns.append(comp)

        if pulldowns:
            add_finding(
                RuleFinding(
                    rule_id="R003_I2C_PULLUPS",
                    severity="error",
                    title=f"I2C line '{net_name}' pulled down to GND",
                    message=f"Resistor(s) {[c.ref for c in pulldowns]} connect I2C line '{net_name}' to GND instead of a positive rail.",
                    nets=[net_name],
                    components=[c.ref for c in pulldowns],
                    recommendation="I2C is open-drain: pull SDA/SCL UP to VDD (typically 2.2 kΩ – 10 kΩ), never down to GND.",
                )
            )
        if not pullups:
            add_finding(
                RuleFinding(
                    rule_id="R003_I2C_PULLUPS",
                    severity="error",
                    title=f"Missing I2C pull-up resistor on '{net_name}'",
                    message=f"I2C bus net '{net_name}' has no pull-up resistor to a positive supply rail.",
                    nets=[net_name],
                    recommendation="Add a 2.2 kΩ – 10 kΩ pull-up resistor from this line to the bus VDD rail (e.g. 3V3).",
                )
            )
        else:
            for comp, rail, ohms in pullups:
                if ohms is not None and (ohms < i2c_min_ohm or ohms > i2c_max_ohm):
                    add_finding(
                        RuleFinding(
                            rule_id="R003_I2C_PULLUPS",
                            severity="warning",
                            title=f"I2C pull-up {comp.ref} ({comp.value}) out of typical range on '{net_name}'",
                            message=f"Pull-up {comp.ref} to {rail} is {ohms:.0f} Ω (recommended {i2c_min_ohm:.0f}–{i2c_max_ohm:.0f} Ω).",
                            nets=[net_name, rail],
                            components=[comp.ref],
                            recommendation="Use 2.2 kΩ – 4.7 kΩ for 400 kHz Fast Mode or 4.7 kΩ – 10 kΩ for 100 kHz Standard Mode.",
                        )
                    )

    # --- R004: 5V-to-3.3V Voltage Domain Mismatch ---
    for comp in model.components.values():
        if not _is_esp_component(comp):
            continue
        for net, nd in model.nets_for_component(comp.ref):
            if HIGH_VOLTAGE_5V_RE.search(net.name):
                add_finding(
                    RuleFinding(
                        rule_id="R004_VOLTAGE_MISMATCH",
                        severity="error",
                        title=f"5V/high-voltage net '{net.name}' directly connected to 3.3V MCU {comp.ref}",
                        message=f"Pin {nd.pin} ({nd.pinfunction or 'unnamed'}) of {comp.ref} ({comp.value}) is tied directly to '{net.name}'. ESP32 pins are 3.3V max (not 5V tolerant).",
                        nets=[net.name],
                        components=[comp.ref],
                        recommendation="Power ESP32 through a 3.3V regulator (LDO/buck) and level-shift any 5V signals.",
                    )
                )

    # --- R005: USB-C CC1 / CC2 5.1 kΩ Pull-Downs ---
    for comp in model.components.values():
        comp_pins = model.nets_for_component(comp.ref)
        cc1_nets = [net.name for net, nd in comp_pins if re.fullmatch(r"cc1", nd.pinfunction.strip(), re.IGNORECASE)]
        cc2_nets = [net.name for net, nd in comp_pins if re.fullmatch(r"cc2", nd.pinfunction.strip(), re.IGNORECASE)]
        if not (cc1_nets or cc2_nets):
            continue
        if cc1_nets and cc2_nets and cc1_nets[0] == cc2_nets[0]:
            add_finding(
                RuleFinding(
                    rule_id="R005_USBC_CC_PULLDOWNS",
                    severity="error",
                    title=f"USB-C {comp.ref} CC1 and CC2 are shorted together on '{cc1_nets[0]}'",
                    message="Sharing one pull-down resistor between CC1 and CC2 breaks e-marked USB-C to USB-C cables.",
                    nets=[cc1_nets[0]],
                    components=[comp.ref],
                    recommendation="Give CC1 and CC2 separate dedicated 5.1 kΩ pull-down resistors to GND.",
                )
            )
        for label, c_nets in (("CC1", cc1_nets), ("CC2", cc2_nets)):
            if not c_nets:
                continue
            cname = c_nets[0]
            cnet = model.nets[cname]
            pd_resistors = []
            for nd in cnet.nodes:
                r_comp = model.components.get(nd.ref)
                if r_comp and _is_resistor(r_comp):
                    other = _other_net_of_two_pin(model, r_comp.ref, cname)
                    if other and is_gnd_net(other, extra_gnd):
                        pd_resistors.append((r_comp, parse_eng_value(r_comp.value)))
            if not pd_resistors:
                add_finding(
                    RuleFinding(
                        rule_id="R005_USBC_CC_PULLDOWNS",
                        severity="error",
                        title=f"USB-C {comp.ref} {label} missing 5.1 kΩ pull-down to GND",
                        message=f"Net '{cname}' on {comp.ref} ({label}) has no pull-down resistor to GND; USB-C power sources will not supply VBUS.",
                        nets=[cname],
                        components=[comp.ref],
                        recommendation="Connect a dedicated 5.1 kΩ (1%) resistor from this CC pin to GND.",
                    )
                )
            else:
                for r_comp, ohms in pd_resistors:
                    if ohms is not None and not (4500.0 <= ohms <= 5700.0):
                        add_finding(
                            RuleFinding(
                                rule_id="R005_USBC_CC_PULLDOWNS",
                                severity="warning",
                                title=f"USB-C {label} pull-down {r_comp.ref} ({r_comp.value}) is not 5.1 kΩ",
                                message=f"Expected ~5.1 kΩ (Rd) on {comp.ref} {label}, found {ohms:.0f} Ω.",
                                nets=[cname],
                                components=[comp.ref, r_comp.ref],
                                recommendation="Replace with 5.1 kΩ (1% or 5%) per USB Type-C specification.",
                            )
                        )

    # --- R006 & R007: ESP32 Strapping Pins & EN/CHIP_PU RC Reset ---
    if effective_profile in ESP_STRAPPING_PINS:
        strap_map = ESP_STRAPPING_PINS[effective_profile]
        esp_comps = [c for c in model.components.values() if _is_esp_component(c)]
        for esp in esp_comps:
            en_checked = False
            for net, nd in model.nets_for_component(esp.ref):
                pfunc_up = nd.pinfunction.upper()
                # Check strapping pins
                for gpio_key, risk_note in strap_map.items():
                    if re.search(rf"\b{gpio_key}\b", pfunc_up) or re.search(rf"\b{gpio_key.replace('GPIO', 'IO')}\b", pfunc_up):
                        if is_gnd_net(net.name, extra_gnd) or is_power_net(net.name, extra_power):
                            add_finding(
                                RuleFinding(
                                    rule_id="R006_ESP_STRAPPING_PINS",
                                    severity="error",
                                    title=f"{esp.ref} strapping pin {gpio_key} hard-tied to rail '{net.name}'",
                                    message=f"{esp.ref} pin {nd.pin} ({nd.pinfunction}) is directly tied to '{net.name}'. {risk_note}",
                                    nets=[net.name],
                                    components=[esp.ref],
                                    recommendation="Use a 10 kΩ resistor (not a dead short) if biasing a strapping pin, and double-check boot table.",
                                )
                            )
                        else:
                            # Check GPIO12 / GPIO45 pulled high via resistor (breaks 3.3V flash!)
                            if gpio_key in {"GPIO12", "GPIO45"}:
                                for other_nd in net.nodes:
                                    rc = model.components.get(other_nd.ref)
                                    if rc and _is_resistor(rc):
                                        other_end = _other_net_of_two_pin(model, rc.ref, net.name)
                                        if other_end and is_power_net(other_end, extra_power):
                                            add_finding(
                                                RuleFinding(
                                                    rule_id="R006_ESP_STRAPPING_PINS",
                                                    severity="error",
                                                    title=f"{esp.ref} flash-voltage strapping pin {gpio_key} pulled HIGH by {rc.ref}",
                                                    message=f"{risk_note} Pull-up {rc.ref} ({rc.value}) to '{other_end}' forces 1.8V flash mode.",
                                                    nets=[net.name, other_end],
                                                    components=[esp.ref, rc.ref],
                                                    recommendation="Remove pull-up or move signal to a non-strapping GPIO.",
                                                )
                                            )

                # Check EN / CHIP_PU reset circuit
                if re.search(r"\b(EN|CHIP_PU|CHIP_EN)\b", pfunc_up):
                    en_checked = True
                    has_pullup = False
                    has_cap_gnd = False
                    for other_nd in net.nodes:
                        c = model.components.get(other_nd.ref)
                        if not c:
                            continue
                        other_end = _other_net_of_two_pin(model, c.ref, net.name)
                        if _is_resistor(c) and other_end and is_power_net(other_end, extra_power) and not is_gnd_net(other_end, extra_gnd):
                            has_pullup = True
                        if _is_capacitor(c) and other_end and is_gnd_net(other_end, extra_gnd):
                            has_cap_gnd = True
                    if not has_pullup:
                        add_finding(
                            RuleFinding(
                                rule_id="R007_ESP_EN_RESET",
                                severity="error",
                                title=f"{esp.ref} EN/CHIP_PU net '{net.name}' missing pull-up resistor",
                                message=f"{esp.ref} reset pin ({nd.pinfunction}) on net '{net.name}' has no pull-up resistor to 3V3; chip will not boot reliably.",
                                nets=[net.name],
                                components=[esp.ref],
                                recommendation="Add a 10 kΩ pull-up resistor from EN to 3V3 and a 100 nF – 1 μF capacitor to GND.",
                            )
                        )
                    elif not has_cap_gnd:
                        add_finding(
                            RuleFinding(
                                rule_id="R007_ESP_EN_RESET",
                                severity="warning",
                                title=f"{esp.ref} EN/CHIP_PU net '{net.name}' missing RC delay capacitor to GND",
                                message=f"{esp.ref} EN has a pull-up but no capacitor to GND for power-on reset delay.",
                                nets=[net.name],
                                components=[esp.ref],
                                recommendation="Add a 100 nF – 1 μF capacitor from EN to GND per Espressif hardware design guidelines.",
                            )
                        )
            if not en_checked:
                # Check if EN net exists by name at least
                pass

    # --- R008: SPI Shared CS Check ---
    for net in model.nets.values():
        cs_ics = [
            nd.ref
            for nd in net.nodes
            if re.search(r"\b(cs|csn|ss|nss|chip_select)\b", nd.pinfunction, re.IGNORECASE)
            and nd.ref in model.components
            and _is_active_ic(model.components[nd.ref])
            and not _is_esp_component(model.components[nd.ref])
        ]
        if len(set(cs_ics)) > 1:
            add_finding(
                RuleFinding(
                    rule_id="R008_SPI_BUS",
                    severity="error",
                    title=f"Multiple SPI slave ICs share Chip-Select net '{net.name}'",
                    message=f"Active ICs {sorted(set(cs_ics))} all connect their CS/SS pin to '{net.name}', causing bus contention on MISO.",
                    nets=[net.name],
                    components=sorted(set(cs_ics)),
                    recommendation="Route a dedicated GPIO chip-select net to each SPI slave device.",
                )
            )

    # --- R009: Single-Pin Dangling Nets ---
    for net in model.nets.values():
        if UNCONNECTED_NET_RE.match(net.name):
            continue
        if len(net.nodes) == 1:
            nd = net.nodes[0]
            if nd.pintype.lower() == "no_connect":
                continue
            add_finding(
                RuleFinding(
                    rule_id="R009_SINGLE_PIN_NETS",
                    severity="warning",
                    title=f"Single-pin dangling net '{net.name}'",
                    message=f"Net '{net.name}' only connects to {nd.ref} pin {nd.pin} ({nd.pinfunction or 'unnamed'}). Possible net-label typo or unconnected signal.",
                    nets=[net.name],
                    components=[nd.ref],
                    recommendation="Verify net spelling, connect the missing destination, or mark pin NC if intentional.",
                )
            )

    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")

    return {
        "passed": errors == 0,
        "source": model.source,
        "requested_profile": req_profile,
        "effective_profile": effective_profile,
        "detected_esp_variant": detected_esp,
        "summary": {
            "components": len(model.components),
            "nets": len(model.nets),
            "power_nets": sorted(power_nets),
            "gnd_nets": sorted(gnd_nets),
            "errors": errors,
            "warnings": warnings,
            "info": infos,
        },
        "findings": [f.to_dict() for f in findings],
    }


async def export_kicad_netlist_sexpr(
    schematic_path: Path,
    output_path: Path,
    timeout: int = 120,
) -> Path:
    """Export a KiCad S-expression netlist (.net) from a schematic via kicad-cli."""
    if not schematic_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {schematic_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    binary = find_kicad_cli()
    argv = [
        binary,
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadsexpr",
        "--output",
        str(output_path),
        str(schematic_path),
    ]
    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"KiCad netlist export failed (rc={res.returncode}): {res.stderr or res.stdout}")
    return output_path


async def validate_circuit_file(
    schematic_path: Path | None = None,
    netlist_path: Path | None = None,
    pcb_path: Path | None = None,
    profile: str = "auto",
    rules_path: Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Validate a KiCad schematic (.kicad_sch), netlist (.net), or PCB (.kicad_pcb) against domain rules."""
    rules_cfg = load_rules_config(rules_path)
    if netlist_path is not None:
        if not netlist_path.exists():
            raise FileNotFoundError(f"Netlist file not found: {netlist_path}")
        text = netlist_path.read_text(encoding="utf-8")
        model = parse_kicad_netlist(text, source=str(netlist_path))
        return evaluate_circuit_rules(model, profile=profile, rules_cfg=rules_cfg)

    if schematic_path is not None:
        with tempfile.TemporaryDirectory(prefix="kicad_mcp_rules_") as tmpdir:
            tmp_net = Path(tmpdir) / f"{schematic_path.stem}.net"
            await export_kicad_netlist_sexpr(schematic_path, tmp_net, timeout=timeout)
            text = tmp_net.read_text(encoding="utf-8")
            model = parse_kicad_netlist(text, source=str(schematic_path))
            return evaluate_circuit_rules(model, profile=profile, rules_cfg=rules_cfg)

    if pcb_path is not None:
        if not pcb_path.exists():
            raise FileNotFoundError(f"PCB file not found: {pcb_path}")
        text = pcb_path.read_text(encoding="utf-8")
        model = parse_kicad_pcb_netlist(text, source=str(pcb_path))
        return evaluate_circuit_rules(model, profile=profile, rules_cfg=rules_cfg)

    raise ValueError("Provide 'schematic_path', 'netlist_path', or 'pcb_path'.")
