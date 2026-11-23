"""Unit tests for ngspice netlist sanitizer, deck builder, parsers, and Pillow waveform plotter."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PIL import Image

from kicad_mcp_app.security import PathSecurityError, WorkspacePathGuard
from kicad_mcp_app.spice_sim import (
    build_managed_spice_deck,
    compute_ac_metrics,
    compute_transient_metrics,
    format_si,
    parse_op_stdout,
    parse_wrdata_file,
    plot_waveform_png,
    sanitize_spice_netlist,
)


def test_sanitize_blocks_shell_escapes_and_out_of_workspace_include(tmp_path: Path) -> None:
    guard = WorkspacePathGuard(workspace_root=tmp_path, allowed_roots=[tmp_path])

    for bad in (
        "V1 in 0 3.3\n.control\nshell rm -rf /\n.endc\n.end",
        "V1 in 0 3.3\n.control\nwrdata /tmp/pwn.txt v(in)\n.endc\n.end",
        "V1 in 0 3.3\n.control\n`id`\n.endc\n.end",
    ):
        with pytest.raises(ValueError, match="Blocked unsafe SPICE"):
            sanitize_spice_netlist(bad, guard=guard, base_dir=tmp_path)

    with pytest.raises(PathSecurityError):
        sanitize_spice_netlist('.include "/etc/passwd"\nV1 in 0 3.3\n.end', guard=guard, base_dir=tmp_path)

    # Valid workspace include resolves cleanly
    model_file = tmp_path / "models.lib"
    model_file.write_text("* dummy\n", encoding="utf-8")
    cleaned = sanitize_spice_netlist('.include "models.lib"\nV1 in 0 3.3\n.end', guard=guard, base_dir=tmp_path)
    assert str(model_file.resolve()) in cleaned


def test_build_managed_spice_deck_modes(tmp_path: Path) -> None:
    base = "RC test\nV1 in 0 3.3\nR1 in out 10k\nC1 out 0 100n\n.end\n"
    wr = tmp_path / "out.dat"

    deck_op, probes_op = build_managed_spice_deck(base, "op", ["out"], wr)
    assert probes_op == ["v(out)"]
    assert "wrdata" in deck_op and "op\n" in deck_op

    deck_tr, probes_tr = build_managed_spice_deck(base, "tran", ["v(out)", "in"], wr, step="10u", stop="5m")
    assert probes_tr == ["v(out)", "v(in)"]
    assert "tran 10u 5m 0" in deck_tr

    deck_ac, _ = build_managed_spice_deck(base, "ac", ["v(out)"], wr, ac_variation="dec", ac_points=25)
    assert "ac dec 25 10 1Meg" in deck_ac
    assert "db(v(out))" in deck_ac

    with pytest.raises(ValueError, match="requires at least one probe"):
        build_managed_spice_deck(base, "tran", [], wr)


def test_parsers_and_metrics_and_pillow_plot(tmp_path: Path) -> None:
    # Simulate an RC step response (tau = 1 ms, Vdd = 3.3 V)
    wr = tmp_path / "tran.dat"
    rows = ["time v(out)"]
    for i in range(101):
        t = i * 5e-5
        v = 3.3 * (1.0 - math.exp(-t / 0.001))
        rows.append(f"{t:.8e} {v:.8e}")
    wr.write_text("\n".join(rows), encoding="utf-8")

    x, series = parse_wrdata_file(wr, ["v(out)"])
    assert len(x) == 101
    metrics = compute_transient_metrics(x, series["v(out)"])
    assert metrics["samples"] == 101
    assert metrics["min"] == pytest.approx(0.0, abs=1e-4)
    assert metrics["final"] == pytest.approx(3.3 * (1 - math.exp(-5.0)), abs=1e-3)
    # 10%-90% rise time of RC is ln(9) * tau ≈ 2.197 ms
    assert metrics["rise_time_10_90_s"] is not None
    assert 0.0019 <= metrics["rise_time_10_90_s"] <= 0.0024

    png_path = tmp_path / "rc_plot.png"
    plot_info = plot_waveform_png(x, series, png_path, title="EN RC Reset", x_unit="s", y_unit="V")
    assert png_path.exists()
    assert plot_info["size_bytes"] > 2000
    with Image.open(png_path) as im:
        assert im.size == (1200, 680)

    # AC response metrics + log plot
    freqs = [10 ** (1 + i * 0.1) for i in range(51)]
    fc = 1000.0
    dbs = [-10.0 * math.log10(1.0 + (f / fc) ** 2) for f in freqs]
    ac_m = compute_ac_metrics(freqs, dbs)
    assert ac_m["cutoff_3db_hz"] is not None
    assert 900.0 <= ac_m["cutoff_3db_hz"] <= 1100.0

    ac_png = tmp_path / "ac_plot.png"
    plot_waveform_png(freqs, {"v(out)": dbs}, ac_png, title="Low-pass Filter", x_unit="Hz", y_unit="dB", x_log=True)
    assert ac_png.exists()

    # OP stdout parser
    op = parse_op_stdout("v(out) = 1.650000e+00\nv1#branch = -1.650000e-04\n")
    assert op["v(out)"] == pytest.approx(1.65)
    assert op["v1#branch"] == pytest.approx(-1.65e-4)
    assert format_si(0.0047, "s") == "4.700ms"
