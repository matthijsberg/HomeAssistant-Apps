"""Headless ngspice simulation, KiCad SPICE export, and pure-Pillow waveform plotter."""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .kicad_cli import find_kicad_cli, run_command
from .security import WorkspacePathGuard

VALID_ANALYSES: frozenset[str] = frozenset({"op", "tran", "ac", "raw"})
VALID_AC_VARIATIONS: frozenset[str] = frozenset({"dec", "oct", "lin"})
VALID_SPICE_FORMATS: frozenset[str] = frozenset({"spice", "spicemodel"})

# Block shell escapes and uncontrolled file writes inside SPICE netlists.
FORBIDDEN_CONTROL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*shell\b", re.IGNORECASE), "ngspice 'shell' command is forbidden"),
    (re.compile(r"^\s*os\b", re.IGNORECASE), "ngspice 'os' command is forbidden"),
    (re.compile(r"^\s*system\b", re.IGNORECASE), "ngspice 'system' command is forbidden"),
    (re.compile(r"^\s*rusage\s+.*>", re.IGNORECASE), "shell redirection is forbidden"),
    (re.compile(r"^\s*source\s+", re.IGNORECASE), "ngspice 'source' directive is forbidden"),
    (re.compile(r"^\s*(write|wrdata|gnuplot|hardcopy)\b", re.IGNORECASE), "uncontrolled ngspice file write is forbidden"),
    (re.compile(r"`[^`]+`"), "backtick command substitution is forbidden"),
)

INCLUDE_DIRECTIVE_RE = re.compile(
    r"^\s*\.(include|inc|lib)\s+(['\"]?)([^'\"\s]+)\2(.*)$",
    re.IGNORECASE,
)
SAFE_SPICE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-+]+$")
SAFE_PROBE_RE = re.compile(r"^[A-Za-z0-9_.\-+#()@:]+$")

PLOT_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 114, 178),    # blue
    (213, 94, 0),     # vermilion
    (0, 158, 115),    # green
    (204, 121, 167),  # magenta
    (230, 159, 0),    # orange
    (86, 180, 233),   # sky
)


def find_ngspice() -> str:
    """Locate the ngspice binary."""
    for candidate in ("/usr/bin/ngspice", "/usr/local/bin/ngspice"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("ngspice")
    if found:
        return found
    raise FileNotFoundError(
        "ngspice binary not found in PATH. Install `ngspice` in the container."
    )


async def get_ngspice_version() -> str:
    """Return installed ngspice version string, or 'unavailable'."""
    try:
        binary = find_ngspice()
        res = await run_command([binary, "--version"], timeout=15)
        combined = "\n".join(part for part in (res.stdout, res.stderr) if part)
        for line in combined.splitlines():
            m = re.search(r"ngspice[- ]+([0-9]+(?:\.[0-9]+)*)", line, re.IGNORECASE)
            if m:
                return f"ngspice {m.group(1)}"
        first = combined.splitlines()[0].strip() if combined else ""
        return first or f"error (rc={res.returncode})"
    except Exception as exc:
        return f"unavailable ({exc})"


def format_si(value: float, unit: str = "") -> str:
    """Format a float cleanly with SI engineering prefixes."""
    if not math.isfinite(value):
        return f"{value}{unit}"
    if value == 0.0:
        return f"0{unit}"
    abs_v = abs(value)
    prefixes = [
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "u"),
        (1e-9, "n"),
        (1e-12, "p"),
    ]
    for scale, prefix in prefixes:
        if abs_v >= scale:
            scaled = value / scale
            if abs(scaled) >= 100:
                return f"{scaled:.1f}{prefix}{unit}"
            if abs(scaled) >= 10:
                return f"{scaled:.2f}{prefix}{unit}"
            return f"{scaled:.3f}{prefix}{unit}"
    return f"{value:.2e}{unit}"


def sanitize_spice_netlist(
    netlist_text: str,
    guard: WorkspacePathGuard | None = None,
    base_dir: Path | None = None,
) -> str:
    """Validate a SPICE netlist against shell escapes and out-of-workspace includes."""
    if not netlist_text or not netlist_text.strip():
        raise ValueError("SPICE netlist content cannot be empty.")
    if "\x00" in netlist_text:
        raise ValueError("Null byte in SPICE netlist is not allowed.")

    cleaned_lines: list[str] = []
    for lineno, line in enumerate(netlist_text.splitlines(), 1):
        for pat, reason in FORBIDDEN_CONTROL_PATTERNS:
            if pat.search(line):
                raise ValueError(f"Blocked unsafe SPICE line {lineno}: {reason}")

        inc_match = INCLUDE_DIRECTIVE_RE.match(line)
        if inc_match and guard is not None:
            directive, _quote, raw_inc_path, trailing = inc_match.groups()
            inc_candidate = Path(raw_inc_path)
            if not inc_candidate.is_absolute() and base_dir is not None:
                inc_candidate = base_dir / inc_candidate
            validated = guard.resolve_and_validate(str(inc_candidate))
            cleaned_lines.append(f'.{directive} "{validated}"{trailing}')
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _normalize_probe(probe: str) -> str:
    cleaned = probe.strip()
    if not cleaned:
        raise ValueError("Probe expression cannot be empty.")
    if not SAFE_PROBE_RE.match(cleaned):
        raise ValueError(f"Invalid SPICE probe expression: '{probe}'")
    if not re.match(r"^[viVI]\(", cleaned) and not cleaned.startswith("@"):
        return f"v({cleaned})"
    return cleaned


def _validate_spice_param(value: str, name: str) -> str:
    cleaned = value.strip()
    if not cleaned or not SAFE_SPICE_TOKEN_RE.match(cleaned):
        raise ValueError(f"Invalid SPICE parameter '{name}': '{value}'")
    return cleaned


def _strip_end_and_control(netlist_text: str) -> str:
    """Remove trailing .end (and existing .control blocks when injecting managed analysis)."""
    lines = netlist_text.splitlines()
    result: list[str] = []
    in_control = False
    for line in lines:
        stripped = line.strip().lower()
        if stripped == ".control":
            in_control = True
            continue
        if stripped == ".endc":
            in_control = False
            continue
        if in_control:
            continue
        if stripped == ".end":
            continue
        result.append(line)
    return "\n".join(result)


def build_managed_spice_deck(
    netlist_text: str,
    analysis: str,
    probes: list[str],
    wrdata_path: Path,
    step: str = "10u",
    stop: str = "10m",
    start: str = "0",
    ac_variation: str = "dec",
    ac_points: int = 20,
    ac_fstart: str = "10",
    ac_fstop: str = "1Meg",
) -> tuple[str, list[str]]:
    """Build a headless ngspice deck with deterministic .control output extraction."""
    mode = analysis.strip().lower()
    if mode not in VALID_ANALYSES:
        raise ValueError(f"Unsupported analysis '{analysis}'. Must be one of {sorted(VALID_ANALYSES)}.")

    if mode == "raw":
        deck = netlist_text.rstrip()
        if not re.search(r"^\s*\.end\s*$", deck, re.IGNORECASE | re.MULTILINE):
            deck += "\n.end"
        return deck + "\n", []

    base_body = _strip_end_and_control(netlist_text)
    norm_probes = [_normalize_probe(p) for p in probes if p.strip()]

    control_lines = [
        ".control",
        "set noaskquit",
        "set wr_vecnames",
        "set wr_singlescale",
    ]

    if mode == "op":
        control_lines.append("op")
        if norm_probes:
            control_lines.append(f"wrdata {wrdata_path} {' '.join(norm_probes)}")
        else:
            control_lines.append("print all")
    elif mode == "tran":
        if not norm_probes:
            raise ValueError("Transient ('tran') simulation requires at least one probe (e.g. ['v(out)']).")
        s_step = _validate_spice_param(step, "step")
        s_stop = _validate_spice_param(stop, "stop")
        s_start = _validate_spice_param(start, "start")
        control_lines.append(f"tran {s_step} {s_stop} {s_start}")
        control_lines.append(f"wrdata {wrdata_path} {' '.join(norm_probes)}")
    elif mode == "ac":
        if not norm_probes:
            raise ValueError("AC ('ac') simulation requires at least one probe (e.g. ['v(out)']).")
        var = ac_variation.strip().lower()
        if var not in VALID_AC_VARIATIONS:
            raise ValueError(f"Invalid ac_variation '{ac_variation}'. Choose dec, oct, or lin.")
        if ac_points < 1 or ac_points > 5000:
            raise ValueError("ac_points must be between 1 and 5000.")
        f1 = _validate_spice_param(ac_fstart, "ac_fstart")
        f2 = _validate_spice_param(ac_fstop, "ac_fstop")
        db_exprs = [f"db({p})" for p in norm_probes]
        control_lines.append(f"ac {var} {ac_points} {f1} {f2}")
        control_lines.append(f"wrdata {wrdata_path} {' '.join(db_exprs)}")

    control_lines.extend(["quit 0", ".endc", ".end"])
    deck = base_body.rstrip() + "\n\n" + "\n".join(control_lines) + "\n"
    return deck, norm_probes


def parse_wrdata_file(wrdata_path: Path, expected_probes: list[str]) -> tuple[list[float], dict[str, list[float]]]:
    """Parse ngspice `wrdata` (with `wr_vecnames` + `wr_singlescale`) into x and per-probe series."""
    if not wrdata_path.exists():
        return [], {}
    lines = [ln.strip() for ln in wrdata_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines:
        return [], {}

    # Detect header line (contains non-numeric tokens)
    headers: list[str] = []
    start_idx = 0
    first_tokens = lines[0].split()
    try:
        [float(tok) for tok in first_tokens]
    except ValueError:
        headers = first_tokens
        start_idx = 1

    rows: list[list[float]] = []
    for ln in lines[start_idx:]:
        parts = ln.split()
        try:
            rows.append([float(tok) for tok in parts])
        except ValueError:
            continue

    if not rows:
        return [], {}

    num_cols = len(rows[0])
    # With wr_singlescale: col 0 = scale (time/freq/index), cols 1..N = vectors
    # Without singlescale or for op: col pairs or 1+N columns
    if num_cols == 1 + len(expected_probes):
        x_vals = [r[0] for r in rows]
        series: dict[str, list[float]] = {}
        for idx, probe in enumerate(expected_probes, start=1):
            series[probe] = [r[idx] for r in rows]
        return x_vals, series

    if num_cols == 2 * len(expected_probes) and len(expected_probes) >= 1:
        # Pair format: x0 y0 x1 y1 ...
        x_vals = [r[0] for r in rows]
        series = {}
        for idx, probe in enumerate(expected_probes):
            series[probe] = [r[2 * idx + 1] for r in rows]
        return x_vals, series

    # Generic fallback using header names
    x_vals = [r[0] for r in rows]
    series = {}
    for col in range(1, num_cols):
        name = headers[col] if col < len(headers) else f"col_{col}"
        series[name] = [r[col] for r in rows]
    return x_vals, series


def parse_op_stdout(stdout: str) -> dict[str, float]:
    """Extract operating point `name = value` entries from ngspice `print all` stdout."""
    results: dict[str, float] = {}
    pat = re.compile(r"^\s*([A-Za-z0-9_.\-+#()@:]+)\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$")
    for line in stdout.splitlines():
        m = pat.match(line)
        if m:
            try:
                results[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
    return results


def compute_transient_metrics(x_vals: list[float], y_vals: list[float]) -> dict[str, Any]:
    """Compute engineering metrics for a transient waveform."""
    if not x_vals or not y_vals or len(x_vals) != len(y_vals):
        return {"samples": 0}
    y_min = min(y_vals)
    y_max = max(y_vals)
    y_mean = sum(y_vals) / len(y_vals)
    span = y_max - y_min
    initial = y_vals[0]
    final = y_vals[-1]

    # Estimate 10%-90% rise time if waveform rises cleanly by > 5% of span
    rise_time_s: float | None = None
    if span > 1e-9 and (final - initial) > 0.5 * span:
        v10 = initial + 0.1 * (final - initial)
        v90 = initial + 0.9 * (final - initial)
        t10: float | None = None
        t90: float | None = None
        for t, v in zip(x_vals, y_vals, strict=False):
            if t10 is None and v >= v10:
                t10 = t
            if t10 is not None and v >= v90:
                t90 = t
                break
        if t10 is not None and t90 is not None and t90 >= t10:
            rise_time_s = round(t90 - t10, 12)

    return {
        "samples": len(y_vals),
        "t_start_s": x_vals[0],
        "t_stop_s": x_vals[-1],
        "initial": round(initial, 6),
        "final": round(final, 6),
        "min": round(y_min, 6),
        "max": round(y_max, 6),
        "mean": round(y_mean, 6),
        "vpp_ripple": round(span, 6),
        "rise_time_10_90_s": rise_time_s,
    }


def compute_ac_metrics(freqs: list[float], db_vals: list[float]) -> dict[str, Any]:
    """Compute engineering metrics for an AC frequency response (dB)."""
    if not freqs or not db_vals or len(freqs) != len(db_vals):
        return {"samples": 0}
    max_db = max(db_vals)
    min_db = min(db_vals)
    dc_db = db_vals[0]
    cutoff_3db_hz: float | None = None
    target_db = max_db - 3.0
    for i in range(1, len(freqs)):
        if db_vals[i - 1] >= target_db >= db_vals[i]:
            # Linear interpolation in log-frequency space
            dv = db_vals[i - 1] - db_vals[i]
            frac = (db_vals[i - 1] - target_db) / dv if dv > 1e-12 else 0.0
            f_prev = max(freqs[i - 1], 1e-12)
            f_curr = max(freqs[i], 1e-12)
            cutoff_3db_hz = round(10 ** (math.log10(f_prev) + frac * (math.log10(f_curr) - math.log10(f_prev))), 4)
            break

    return {
        "samples": len(db_vals),
        "freq_min_hz": freqs[0],
        "freq_max_hz": freqs[-1],
        "dc_or_start_gain_db": round(dc_db, 4),
        "max_gain_db": round(max_db, 4),
        "min_gain_db": round(min_db, 4),
        "cutoff_3db_hz": cutoff_3db_hz,
    }


def plot_waveform_png(
    x_vals: list[float],
    series: dict[str, list[float]],
    output_path: Path,
    title: str = "SPICE Simulation",
    x_unit: str = "s",
    y_unit: str = "V",
    x_log: bool = False,
    width: int = 1200,
    height: int = 680,
) -> dict[str, Any]:
    """Render a crisp multi-trace engineering waveform PNG using pure Pillow (zero matplotlib bloat)."""
    if not x_vals or not series:
        raise ValueError("Cannot plot empty waveform data.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), (250, 251, 253))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    pad_left = 92
    pad_right = 36
    pad_top = 56
    pad_bottom = 92
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    # Compute X range
    if x_log:
        pos_x = [max(v, 1e-12) for v in x_vals]
        x_lo = math.log10(min(pos_x))
        x_hi = math.log10(max(pos_x))
        if abs(x_hi - x_lo) < 1e-12:
            x_hi = x_lo + 1.0
    else:
        x_lo = min(x_vals)
        x_hi = max(x_vals)
        if abs(x_hi - x_lo) < 1e-12:
            x_hi = x_lo + 1.0

    # Compute Y range across all traces
    all_y = [v for vals in series.values() for v in vals if math.isfinite(v)]
    y_min = min(all_y)
    y_max = max(all_y)
    if abs(y_max - y_min) < 1e-12:
        margin = abs(y_max) * 0.1 if y_max != 0 else 1.0
        y_lo = y_min - margin
        y_hi = y_max + margin
    else:
        margin = (y_max - y_min) * 0.08
        y_lo = y_min - margin
        y_hi = y_max + margin

    def map_x(val: float) -> float:
        tx = math.log10(max(val, 1e-12)) if x_log else val
        return pad_left + ((tx - x_lo) / (x_hi - x_lo)) * plot_w

    def map_y(val: float) -> float:
        return pad_top + plot_h - ((val - y_lo) / (y_hi - y_lo)) * plot_h

    # Plot background & border
    draw.rectangle([pad_left, pad_top, pad_left + plot_w, pad_top + plot_h], fill=(255, 255, 255), outline=(170, 178, 190), width=1)

    # Title
    draw.text((pad_left, 18), title, fill=(24, 32, 48), font=font)

    # Horizontal gridlines & Y ticks
    y_ticks = 6
    for i in range(y_ticks + 1):
        frac = i / y_ticks
        yv = y_lo + frac * (y_hi - y_lo)
        py = int(round(map_y(yv)))
        draw.line([(pad_left, py), (pad_left + plot_w, py)], fill=(230, 234, 240), width=1)
        label = format_si(yv, y_unit) if y_unit != "dB" else f"{yv:.1f} dB"
        draw.text((10, py - 6), label, fill=(65, 74, 90), font=font)

    # Vertical gridlines & X ticks
    x_ticks = 6
    for i in range(x_ticks + 1):
        frac = i / x_ticks
        tx = x_lo + frac * (x_hi - x_lo)
        xv = (10 ** tx) if x_log else tx
        px = int(round(pad_left + frac * plot_w))
        draw.line([(px, pad_top), (px, pad_top + plot_h)], fill=(230, 234, 240), width=1)
        label = format_si(xv, x_unit)
        draw.text((px - 22, pad_top + plot_h + 10), label, fill=(65, 74, 90), font=font)

    # Draw traces
    legend_x = pad_left
    legend_y = height - 48
    for idx, (name, y_vals) in enumerate(series.items()):
        color = PLOT_COLORS[idx % len(PLOT_COLORS)]
        pts: list[tuple[float, float]] = []
        # Downsample very dense traces for fast crisp drawing
        stride = max(1, len(x_vals) // 2400)
        for i in range(0, min(len(x_vals), len(y_vals)), stride):
            if math.isfinite(x_vals[i]) and math.isfinite(y_vals[i]):
                pts.append((map_x(x_vals[i]), map_y(y_vals[i])))
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=2)
        elif len(pts) == 1:
            px, py = pts[0]
            draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=color)

        # Legend entry
        draw.rectangle([legend_x, legend_y + 2, legend_x + 16, legend_y + 12], fill=color)
        unit_disp = " dB" if y_unit == "dB" else y_unit
        lo_s = f"{min(y_vals):.2f}{unit_disp}" if y_unit == "dB" else format_si(min(y_vals), y_unit)
        hi_s = f"{max(y_vals):.2f}{unit_disp}" if y_unit == "dB" else format_si(max(y_vals), y_unit)
        leg_text = f"{name} [{lo_s}..{hi_s}]"
        draw.text((legend_x + 22, legend_y), leg_text, fill=(24, 32, 48), font=font)
        legend_x += max(210, len(leg_text) * 7 + 36)
        if legend_x > width - 220:
            legend_x = pad_left
            legend_y += 18

    img.save(output_path, format="PNG")
    return {
        "path": str(output_path),
        "width": width,
        "height": height,
        "size_bytes": output_path.stat().st_size,
        "traces": list(series.keys()),
    }


async def export_spice_netlist(
    schematic_path: Path,
    output_path: Path | None = None,
    format_mode: str = "spice",
    timeout: int = 120,
) -> dict[str, Any]:
    """Export a KiCad schematic (.kicad_sch) to a SPICE netlist via kicad-cli."""
    if not schematic_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {schematic_path}")
    fmt = format_mode.strip().lower()
    if fmt not in VALID_SPICE_FORMATS:
        raise ValueError(f"Invalid format_mode '{format_mode}'. Choose 'spice' or 'spicemodel'.")

    out = output_path or schematic_path.with_suffix(".cir")
    out.parent.mkdir(parents=True, exist_ok=True)
    binary = find_kicad_cli()
    argv = [
        binary,
        "sch",
        "export",
        "netlist",
        "--format",
        fmt,
        "--output",
        str(out),
        str(schematic_path),
    ]
    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(f"SPICE netlist export failed (rc={res.returncode}): {res.stderr or res.stdout}")
    return {
        "status": "ok",
        "schematic_path": str(schematic_path),
        "output_path": str(out),
        "format": fmt,
        "size_bytes": out.stat().st_size,
    }


async def run_spice_simulation(
    netlist_path: Path | None = None,
    netlist_content: str = "",
    analysis: str = "op",
    probes: list[str] | None = None,
    step: str = "10u",
    stop: str = "10m",
    start: str = "0",
    ac_variation: str = "dec",
    ac_points: int = 20,
    ac_fstart: str = "10",
    ac_fstop: str = "1Meg",
    plot_output_path: Path | None = None,
    plot_title: str = "",
    guard: WorkspacePathGuard | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run headless ngspice simulation on a netlist file or inline SPICE content."""
    base_dir: Path | None = None
    source_label = "inline"
    if netlist_path is not None:
        if not netlist_path.exists():
            raise FileNotFoundError(f"SPICE netlist not found: {netlist_path}")
        raw_netlist = netlist_path.read_text(encoding="utf-8")
        base_dir = netlist_path.parent
        source_label = str(netlist_path)
    elif netlist_content.strip():
        raw_netlist = netlist_content
    else:
        raise ValueError("Provide either 'netlist_path' or 'netlist_content'.")

    sanitized = sanitize_spice_netlist(raw_netlist, guard=guard, base_dir=base_dir)
    binary = find_ngspice()
    mode = analysis.strip().lower()

    with tempfile.TemporaryDirectory(prefix="kicad_mcp_spice_") as tmpdir:
        tmp = Path(tmpdir)
        deck_path = tmp / "sim.cir"
        wrdata_path = tmp / "results.dat"

        deck_text, norm_probes = build_managed_spice_deck(
            netlist_text=sanitized,
            analysis=mode,
            probes=probes or [],
            wrdata_path=wrdata_path,
            step=step,
            stop=stop,
            start=start,
            ac_variation=ac_variation,
            ac_points=ac_points,
            ac_fstart=ac_fstart,
            ac_fstop=ac_fstop,
        )
        deck_path.write_text(deck_text, encoding="utf-8")

        res = await run_command([binary, "-b", str(deck_path)], timeout=timeout)
        combined_err = "\n".join(p for p in (res.stderr, res.stdout) if p)
        sim_errors = [
            ln.strip()
            for ln in combined_err.splitlines()
            if re.search(r"\b(error|fatal|aborted|singular matrix|no such vector)\b", ln, re.IGNORECASE)
        ]

        payload: dict[str, Any] = {
            "passed": res.returncode == 0 and len(sim_errors) == 0,
            "source": source_label,
            "analysis": mode,
            "returncode": res.returncode,
            "probes": norm_probes,
            "errors": sim_errors[:20],
            "metrics": {},
        }

        if mode == "op":
            if norm_probes and wrdata_path.exists():
                _x, series = parse_wrdata_file(wrdata_path, norm_probes)
                payload["metrics"] = {k: round(v[-1], 6) for k, v in series.items() if v}
            else:
                payload["metrics"] = parse_op_stdout(res.stdout)
        elif mode == "tran":
            x_vals, series = parse_wrdata_file(wrdata_path, norm_probes)
            payload["metrics"] = {
                probe: compute_transient_metrics(x_vals, y_vals)
                for probe, y_vals in series.items()
            }
            if plot_output_path is not None and x_vals and series:
                payload["plot"] = plot_waveform_png(
                    x_vals=x_vals,
                    series=series,
                    output_path=plot_output_path,
                    title=plot_title or f"Transient Simulation ({Path(source_label).name})",
                    x_unit="s",
                    y_unit="V",
                    x_log=False,
                )
        elif mode == "ac":
            x_vals, series = parse_wrdata_file(wrdata_path, norm_probes)
            payload["metrics"] = {
                probe: compute_ac_metrics(x_vals, y_vals)
                for probe, y_vals in series.items()
            }
            if plot_output_path is not None and x_vals and series:
                payload["plot"] = plot_waveform_png(
                    x_vals=x_vals,
                    series=series,
                    output_path=plot_output_path,
                    title=plot_title or f"AC Frequency Response ({Path(source_label).name})",
                    x_unit="Hz",
                    y_unit="dB",
                    x_log=True,
                )
        else:
            payload["metrics"] = parse_op_stdout(res.stdout)

        if not payload["passed"]:
            payload["stdout_tail"] = "\n".join(res.stdout.splitlines()[-30:])
            payload["stderr_tail"] = "\n".join(res.stderr.splitlines()[-30:])

        return payload
