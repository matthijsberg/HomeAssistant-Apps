"""Clean async KiCad 9 CLI wrappers and report parsers."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

LAYER_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ROTATE_RE = re.compile(r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$")

VALID_RENDER_SIDES: frozenset[str] = frozenset({"top", "bottom", "left", "right", "front", "back"})
VALID_RENDER_QUALITIES: frozenset[str] = frozenset({"basic", "high", "user"})
VALID_RENDER_BACKGROUNDS: frozenset[str] = frozenset({"default", "transparent", "opaque"})


@dataclass
class CommandResult:
    """Result of executing a headless CLI subprocess."""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


def find_kicad_cli() -> str:
    """Locate the kicad-cli binary (preferring /usr/local/bin/kicad-cli wrapper)."""
    for candidate in ("/usr/local/bin/kicad-cli", "/usr/bin/kicad-cli"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("kicad-cli")
    if found:
        return found
    raise FileNotFoundError(
        "kicad-cli binary not found in PATH. Ensure KiCad 9.x is installed in the container."
    )


async def run_command(argv: list[str], timeout: int = 120) -> CommandResult:
    """Execute a subprocess asynchronously with UTF-8 English locale and bounded timeout."""
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(argv)}") from exc

    return CommandResult(
        argv=argv,
        returncode=proc.returncode or 0,
        stdout=stdout_b.decode("utf-8", errors="replace").strip(),
        stderr=stderr_b.decode("utf-8", errors="replace").strip(),
    )


async def get_kicad_version() -> str:
    """Return the installed kicad-cli version string, or 'unavailable'."""
    try:
        binary = find_kicad_cli()
        res = await run_command([binary, "--version"], timeout=15)
        if res.returncode == 0 and res.stdout:
            return res.stdout.splitlines()[0].strip()
        return f"error (rc={res.returncode}): {res.stderr}"
    except Exception as exc:
        return f"unavailable ({exc})"


def check_pcbnew_available() -> bool:
    """Return True if KiCad's Python pcbnew module can be imported."""
    try:
        import pcbnew  # type: ignore[import-not-found]

        return pcbnew is not None
    except Exception:
        return False


def validate_layer_names(layers: list[str]) -> list[str]:
    """Validate and normalize KiCad layer names."""
    cleaned = [layer.strip() for layer in layers if layer.strip()]
    if not cleaned:
        raise ValueError("At least one KiCad layer must be specified (e.g. 'F.Cu').")
    for layer in cleaned:
        if not LAYER_NAME_RE.match(layer):
            raise ValueError(f"Invalid KiCad layer name: '{layer}'")
    return cleaned


def parse_drc_json(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize a KiCad 9/10 DRC JSON report cleanly."""
    violations = report.get("violations", []) or []
    unconnected = report.get("unconnected_items", []) or []
    parity = report.get("schematic_parity", []) or []

    def _summarize(items: list[dict[str, Any]]) -> tuple[int, int, int, list[dict[str, Any]]]:
        errors = 0
        warnings = 0
        excluded = 0
        compact: list[dict[str, Any]] = []
        for item in items:
            is_excluded = bool(item.get("excluded", False))
            severity = str(item.get("severity", "error")).lower()
            if is_excluded:
                excluded += 1
            elif severity == "warning":
                warnings += 1
            else:
                errors += 1
            compact.append(
                {
                    "type": item.get("type", "unknown"),
                    "severity": severity,
                    "excluded": is_excluded,
                    "description": item.get("description", ""),
                    "items": [
                        {
                            "description": sub.get("description", ""),
                            "pos": sub.get("pos"),
                        }
                        for sub in (item.get("items") or [])[:4]
                    ],
                }
            )
        return errors, warnings, excluded, compact

    v_err, v_warn, v_excl, v_list = _summarize(violations)
    u_err, u_warn, u_excl, u_list = _summarize(unconnected)
    p_err, p_warn, p_excl, p_list = _summarize(parity)

    total_errors = v_err + u_err + p_err
    total_warnings = v_warn + u_warn + p_warn

    return {
        "passed": total_errors == 0,
        "kicad_version": report.get("kicad_version", ""),
        "source": report.get("source", ""),
        "date": report.get("date", ""),
        "summary": {
            "errors": total_errors,
            "warnings": total_warnings,
            "excluded": v_excl + u_excl + p_excl,
            "violations_count": len(violations),
            "unconnected_count": len(unconnected),
            "schematic_parity_count": len(parity),
        },
        "violations": v_list[:100],
        "unconnected_items": u_list[:100],
        "schematic_parity": p_list[:100],
    }


def parse_erc_json(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize a KiCad 9/10 ERC JSON report (handles both top-level and sheets[] layouts)."""
    all_violations: list[dict[str, Any]] = []
    for top_v in report.get("violations") or []:
        all_violations.append({"sheet": "/", **top_v})
    for sheet in report.get("sheets") or []:
        sheet_path = sheet.get("path", "/")
        for sv in sheet.get("violations") or []:
            all_violations.append({"sheet": sheet_path, **sv})

    errors = 0
    warnings = 0
    excluded = 0
    compact: list[dict[str, Any]] = []
    for item in all_violations:
        is_excluded = bool(item.get("excluded", False))
        severity = str(item.get("severity", "error")).lower()
        if is_excluded:
            excluded += 1
        elif severity == "warning":
            warnings += 1
        else:
            errors += 1
        compact.append(
            {
                "sheet": item.get("sheet", "/"),
                "type": item.get("type", "unknown"),
                "severity": severity,
                "excluded": is_excluded,
                "description": item.get("description", ""),
                "items": [
                    {
                        "description": sub.get("description", ""),
                        "pos": sub.get("pos"),
                    }
                    for sub in (item.get("items") or [])[:4]
                ],
            }
        )

    return {
        "passed": errors == 0,
        "kicad_version": report.get("kicad_version", ""),
        "source": report.get("source", ""),
        "date": report.get("date", ""),
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "excluded": excluded,
            "total": len(all_violations),
        },
        "violations": compact[:100],
    }


async def run_drc(
    pcb_path: Path,
    output_path: Path | None = None,
    schematic_parity: bool = False,
    all_track_errors: bool = True,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run `kicad-cli pcb drc --format json` and return a structured summary."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    out = output_path or pcb_path.with_name(f"{pcb_path.stem}_drc.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--units",
        "mm",
        "--output",
        str(out),
    ]
    if all_track_errors:
        argv.append("--all-track-errors")
    if schematic_parity:
        argv.append("--schematic-parity")
    argv.append(str(pcb_path))

    res = await run_command(argv, timeout=timeout)
    if not out.exists():
        raise RuntimeError(
            f"kicad-cli pcb drc failed (rc={res.returncode}) without writing report: "
            f"{res.stderr or res.stdout}"
        )

    raw_report = json.loads(out.read_text(encoding="utf-8"))
    parsed = parse_drc_json(raw_report)
    parsed["report_path"] = str(out)
    parsed["returncode"] = res.returncode
    return parsed


async def run_erc(
    schematic_path: Path,
    output_path: Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run `kicad-cli sch erc --format json` and return a structured summary."""
    if not schematic_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {schematic_path}")

    out = output_path or schematic_path.with_name(f"{schematic_path.stem}_erc.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "sch",
        "erc",
        "--format",
        "json",
        "--severity-all",
        "--units",
        "mm",
        "--output",
        str(out),
        str(schematic_path),
    ]
    res = await run_command(argv, timeout=timeout)
    if not out.exists():
        raise RuntimeError(
            f"kicad-cli sch erc failed (rc={res.returncode}) without writing report: "
            f"{res.stderr or res.stdout}"
        )

    raw_report = json.loads(out.read_text(encoding="utf-8"))
    parsed = parse_erc_json(raw_report)
    parsed["report_path"] = str(out)
    parsed["returncode"] = res.returncode
    return parsed


async def export_pcb_2d(
    pcb_path: Path,
    layers: list[str],
    output_dir: Path | None = None,
    mode: str = "single",
    rasterize_png: bool = True,
    dpi: int = 300,
    exclude_drawing_sheet: bool = True,
    black_and_white: bool = False,
    mirror: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Export PCB 2D layers to SVG (and optionally rasterize to PNG via rsvg-convert)."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")
    if mode not in {"single", "multi"}:
        raise ValueError("mode must be 'single' (combined SVG) or 'multi' (one SVG per layer).")
    if dpi < 72 or dpi > 1200:
        raise ValueError("dpi must be between 72 and 1200.")

    valid_layers = validate_layer_names(layers)
    out_dir = output_dir or (pcb_path.parent / f"{pcb_path.stem}_2d")
    out_dir.mkdir(parents=True, exist_ok=True)

    binary = find_kicad_cli()
    rsvg = shutil.which("rsvg-convert")
    generated: list[dict[str, Any]] = []

    layer_groups: list[tuple[str, list[str]]] = (
        [(f"{pcb_path.stem}_" + "_".join(valid_layers).replace(".", "_"), valid_layers)]
        if mode == "single"
        else [(f"{pcb_path.stem}_{layer.replace('.', '_')}", [layer]) for layer in valid_layers]
    )

    for stem, group in layer_groups:
        svg_path = out_dir / f"{stem}.svg"
        argv = [
            binary,
            "pcb",
            "export",
            "svg",
            "--output",
            str(svg_path),
            "--layers",
            ",".join(group),
            "--page-size-mode",
            "2",  # Fit page to board outline
        ]
        if exclude_drawing_sheet:
            argv.append("--exclude-drawing-sheet")
        if black_and_white:
            argv.append("--black-and-white")
        if mirror:
            argv.append("--mirror")
        argv.append(str(pcb_path))

        res = await run_command(argv, timeout=timeout)
        if res.returncode != 0 or not svg_path.exists():
            raise RuntimeError(
                f"kicad-cli pcb export svg failed for {group} (rc={res.returncode}): "
                f"{res.stderr or res.stdout}"
            )

        entry: dict[str, Any] = {
            "layers": group,
            "svg_path": str(svg_path),
            "svg_bytes": svg_path.stat().st_size,
        }

        if rasterize_png:
            if not rsvg:
                entry["png_error"] = "rsvg-convert not installed; SVG generated only."
            else:
                png_path = out_dir / f"{stem}.png"
                rsvg_res = await run_command(
                    [
                        rsvg,
                        "--dpi-x",
                        str(dpi),
                        "--dpi-y",
                        str(dpi),
                        "--background-color",
                        "#12161c",
                        "--output",
                        str(png_path),
                        str(svg_path),
                    ],
                    timeout=timeout,
                )
                if rsvg_res.returncode != 0 or not png_path.exists():
                    raise RuntimeError(
                        f"rsvg-convert failed for {svg_path.name} (rc={rsvg_res.returncode}): "
                        f"{rsvg_res.stderr or rsvg_res.stdout}"
                    )
                with Image.open(png_path) as img:
                    width, height = img.size
                entry["png_path"] = str(png_path)
                entry["png_bytes"] = png_path.stat().st_size
                entry["png_width"] = width
                entry["png_height"] = height

        generated.append(entry)

    return {
        "pcb_path": str(pcb_path),
        "output_dir": str(out_dir),
        "mode": mode,
        "files": generated,
    }


async def render_pcb_3d(
    pcb_path: Path,
    output_path: Path | None = None,
    side: str = "top",
    width: int = 1600,
    height: int = 900,
    quality: str = "basic",
    background: str = "opaque",
    rotate: str = "",
    perspective: bool = False,
    zoom: float | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    """Render a 3D PNG image of a PCB via `kicad-cli pcb render` (headless software OpenGL)."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")
    if side not in VALID_RENDER_SIDES:
        raise ValueError(f"Invalid side '{side}'. Valid: {sorted(VALID_RENDER_SIDES)}")
    if quality not in VALID_RENDER_QUALITIES:
        raise ValueError(f"Invalid quality '{quality}'. Valid: {sorted(VALID_RENDER_QUALITIES)}")
    if background not in VALID_RENDER_BACKGROUNDS:
        raise ValueError(
            f"Invalid background '{background}'. Valid: {sorted(VALID_RENDER_BACKGROUNDS)}"
        )
    if width < 100 or width > 4096 or height < 100 or height > 4096:
        raise ValueError("width and height must be between 100 and 4096 pixels.")
    if rotate and not ROTATE_RE.match(rotate.strip()):
        raise ValueError("rotate must match 'X,Y,Z' degrees, e.g. '-30,0,25'.")

    out = output_path or pcb_path.with_name(f"{pcb_path.stem}_3d_{side}.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "pcb",
        "render",
        "--output",
        str(out),
        "--side",
        side,
        "--width",
        str(width),
        "--height",
        str(height),
        "--quality",
        quality,
        "--background",
        background,
    ]
    if perspective:
        argv.append("--perspective")
    if rotate.strip():
        argv.extend(["--rotate", rotate.strip()])
    if zoom is not None:
        argv.extend(["--zoom", str(zoom)])
    argv.append(str(pcb_path))

    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(
            f"kicad-cli pcb render failed (rc={res.returncode}): {res.stderr or res.stdout}"
        )

    with Image.open(out) as img:
        img_w, img_h = img.size

    return {
        "pcb_path": str(pcb_path),
        "output_path": str(out),
        "side": side,
        "quality": quality,
        "width": img_w,
        "height": img_h,
        "bytes": out.stat().st_size,
    }


async def export_pcb_drill(
    pcb_path: Path,
    output_dir: Path | None = None,
    generate_map: bool = True,
    map_format: str = "pdf",
    timeout: int = 120,
) -> dict[str, Any]:
    """Export Excellon drill files (and optional drill map) via `kicad-cli pcb export drill`."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")
    if map_format not in {"pdf", "svg", "gerberx2", "ps", "dxf"}:
        raise ValueError(f"Unsupported map_format '{map_format}'.")

    out_dir = output_dir or (pcb_path.parent / f"{pcb_path.stem}_drill")
    out_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "pcb",
        "export",
        "drill",
        "--output",
        f"{out_dir}/",
        "--format",
        "excellon",
        "--drill-origin",
        "absolute",
        "--excellon-units",
        "mm",
        "--excellon-oval-format",
        "alternate",
    ]
    if generate_map:
        argv.extend(["--generate-map", "--map-format", map_format])
    argv.append(str(pcb_path))

    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(
            f"kicad-cli pcb export drill failed (rc={res.returncode}): {res.stderr or res.stdout}"
        )

    files = sorted(str(p) for p in out_dir.iterdir() if p.is_file())
    return {
        "pcb_path": str(pcb_path),
        "output_dir": str(out_dir),
        "files": files,
        "count": len(files),
    }


async def export_fabrication_bundle(
    pcb_path: Path,
    output_dir: Path | None = None,
    layers: list[str] | None = None,
    include_pos: bool = True,
    create_zip: bool = True,
    timeout: int = 120,
) -> dict[str, Any]:
    """Export Gerbers + Excellon drills + optional CPL position CSV (+ optional zip bundle)."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    out_dir = output_dir or (pcb_path.parent / f"{pcb_path.stem}_fab")
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = find_kicad_cli()

    gerber_argv = [
        binary,
        "pcb",
        "export",
        "gerbers",
        "--output",
        f"{out_dir}/",
        "--no-protel-ext",
    ]
    if layers:
        gerber_argv.extend(["--layers", ",".join(validate_layer_names(layers))])
    gerber_argv.append(str(pcb_path))

    g_res = await run_command(gerber_argv, timeout=timeout)
    if g_res.returncode != 0:
        raise RuntimeError(
            f"kicad-cli pcb export gerbers failed (rc={g_res.returncode}): {g_res.stderr or g_res.stdout}"
        )

    drill_info = await export_pcb_drill(pcb_path, output_dir=out_dir, generate_map=False, timeout=timeout)

    pos_path: Path | None = None
    if include_pos:
        pos_path = out_dir / f"{pcb_path.stem}-pos.csv"
        p_res = await run_command(
            [
                binary,
                "pcb",
                "export",
                "pos",
                "--output",
                str(pos_path),
                "--format",
                "csv",
                "--units",
                "mm",
                "--side",
                "both",
                str(pcb_path),
            ],
            timeout=timeout,
        )
        if p_res.returncode != 0:
            raise RuntimeError(
                f"kicad-cli pcb export pos failed (rc={p_res.returncode}): {p_res.stderr or p_res.stdout}"
            )

    zip_path: Path | None = None
    fab_files = sorted(p for p in out_dir.iterdir() if p.is_file() and p.suffix != ".zip")
    if create_zip:
        zip_path = out_dir / f"{pcb_path.stem}_gerbers.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in fab_files:
                if item.name.endswith("-pos.csv"):
                    continue
                zf.write(item, arcname=item.name)

    return {
        "pcb_path": str(pcb_path),
        "output_dir": str(out_dir),
        "files": [str(p) for p in fab_files],
        "drill_files_count": drill_info["count"],
        "pos_csv": str(pos_path) if pos_path and pos_path.exists() else None,
        "gerber_zip": str(zip_path) if zip_path and zip_path.exists() else None,
    }


async def export_schematic_bom(
    schematic_path: Path,
    output_path: Path | None = None,
    fields: str = "Reference,Value,Footprint,${QUANTITY},${DNP}",
    timeout: int = 120,
) -> dict[str, Any]:
    """Export a Bill of Materials (CSV) from a KiCad schematic via `kicad-cli sch export bom`."""
    if not schematic_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {schematic_path}")

    out = output_path or schematic_path.with_name(f"{schematic_path.stem}_bom.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "sch",
        "export",
        "bom",
        "--output",
        str(out),
        "--fields",
        fields,
        "--group-by",
        "Value,Footprint,${DNP}",
        str(schematic_path),
    ]
    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(
            f"kicad-cli sch export bom failed (rc={res.returncode}): {res.stderr or res.stdout}"
        )

    lines = out.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "schematic_path": str(schematic_path),
        "output_path": str(out),
        "rows": max(0, len(lines) - 1),
        "preview": lines[:15],
    }


async def export_pcb_step(
    pcb_path: Path,
    output_path: Path | None = None,
    board_only: bool = False,
    subst_models: bool = True,
    timeout: int = 300,
) -> dict[str, Any]:
    """Export a mechanical 3D STEP model via `kicad-cli pcb export step`."""
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    out = output_path or pcb_path.with_suffix(".step")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        find_kicad_cli(),
        "pcb",
        "export",
        "step",
        "--output",
        str(out),
        "--force",
    ]
    if board_only:
        argv.append("--board-only")
    if subst_models:
        argv.append("--subst-models")
    argv.append(str(pcb_path))

    res = await run_command(argv, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(
            f"kicad-cli pcb export step failed (rc={res.returncode}): {res.stderr or res.stdout}"
        )

    return {
        "pcb_path": str(pcb_path),
        "output_path": str(out),
        "bytes": out.stat().st_size,
    }
