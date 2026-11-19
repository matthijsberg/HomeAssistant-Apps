"""First-class headless KiCad 9 CLI tools registered on the shared FastMCP server."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from . import __version__
from . import kicad_cli as cli
from .config import AppConfig
from .security import WorkspacePathGuard


def register_extra_tools(mcp: FastMCP, config: AppConfig, guard: WorkspacePathGuard) -> None:
    """Register headless KiCad 9 CLI tools alongside upstream Seeed-Studio tools."""

    @mcp.tool()
    async def kicad_health() -> str:
        """Return KiCad Headless MCP runtime health, kicad-cli version, pcbnew status, and workspace config."""
        version = await cli.get_kicad_version()
        payload = {
            "status": "ok",
            "app_version": __version__,
            "kicad_cli_version": version,
            "pcbnew_available": cli.check_pcbnew_available(),
            "workspace_root": str(guard.workspace_root),
            "allowed_roots": [str(r) for r in guard.allowed_roots],
            "read_only": config.read_only,
        }
        return json.dumps(payload, indent=2)

    @mcp.tool()
    async def list_workspace_projects(directory: str = "", max_results: int = 100) -> str:
        """Discover KiCad files (.kicad_pro, .kicad_pcb, .kicad_sch) inside the workspace."""
        root = guard.resolve_and_validate(directory) if directory.strip() else guard.workspace_root
        if not root.exists():
            return json.dumps({"root": str(root), "exists": False, "files": []}, indent=2)

        exts = {".kicad_pro", ".kicad_pcb", ".kicad_sch"}
        found: list[dict[str, str]] = []
        for path in sorted(root.rglob("*")):
            if len(found) >= max_results:
                break
            if path.is_file() and path.suffix in exts:
                found.append(
                    {
                        "type": path.suffix.lstrip("."),
                        "path": str(path),
                        "relative": str(path.relative_to(root)),
                    }
                )
        return json.dumps({"root": str(root), "count": len(found), "files": found}, indent=2)

    @mcp.tool()
    async def run_drc_detailed(
        pcb_path: str,
        output_path: str = "",
        schematic_parity: bool = False,
        all_track_errors: bool = True,
    ) -> str:
        """Run KiCad 9 headless DRC (`kicad-cli pcb drc --format json`) and return structured violations."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await cli.run_drc(
            pcb_path=pcb,
            output_path=out,
            schematic_parity=schematic_parity,
            all_track_errors=all_track_errors,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def run_erc_detailed(
        schematic_path: str,
        output_path: str = "",
    ) -> str:
        """Run KiCad 9 headless ERC (`kicad-cli sch erc --format json`) and return structured violations."""
        sch = guard.resolve_and_validate(schematic_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await cli.run_erc(
            schematic_path=sch,
            output_path=out,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def export_pcb_2d(
        pcb_path: str,
        layers: list[str] | None = None,
        output_dir: str = "",
        mode: str = "multi",
        rasterize_png: bool = True,
        dpi: int = 300,
        exclude_drawing_sheet: bool = True,
        black_and_white: bool = False,
        mirror: bool = False,
    ) -> str:
        """Export 2D PCB layers (e.g. F.Cu, B.Cu, F.SilkS, B.SilkS, Edge.Cuts) to SVG and high-DPI PNG."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_dir) if output_dir.strip() else None
        target_layers = layers or ["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"]
        result = await cli.export_pcb_2d(
            pcb_path=pcb,
            layers=target_layers,
            output_dir=out,
            mode=mode,
            rasterize_png=rasterize_png,
            dpi=dpi,
            exclude_drawing_sheet=exclude_drawing_sheet,
            black_and_white=black_and_white,
            mirror=mirror,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def render_pcb_3d_view(
        pcb_path: str,
        output_path: str = "",
        side: str = "top",
        width: int = 1600,
        height: int = 900,
        quality: str = "basic",
        background: str = "opaque",
        rotate: str = "",
        perspective: bool = False,
        zoom: float | None = None,
    ) -> str:
        """Render a 3D PNG view of a PCB headless via `kicad-cli pcb render` and return the output path & metadata."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await cli.render_pcb_3d(
            pcb_path=pcb,
            output_path=out,
            side=side,
            width=width,
            height=height,
            quality=quality,
            background=background,
            rotate=rotate,
            perspective=perspective,
            zoom=zoom,
            timeout=config.render_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def export_pcb_drill_files(
        pcb_path: str,
        output_dir: str = "",
        generate_map: bool = True,
        map_format: str = "pdf",
    ) -> str:
        """Export Excellon drill files (.drl) and optional drill map via `kicad-cli pcb export drill`."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_dir) if output_dir.strip() else None
        result = await cli.export_pcb_drill(
            pcb_path=pcb,
            output_dir=out,
            generate_map=generate_map,
            map_format=map_format,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def export_fab_bundle(
        pcb_path: str,
        output_dir: str = "",
        layers: list[str] | None = None,
        include_pos: bool = True,
        create_zip: bool = True,
    ) -> str:
        """Export complete fabrication output: Gerbers + Excellon drill + optional CPL CSV + Gerber ZIP."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_dir) if output_dir.strip() else None
        result = await cli.export_fabrication_bundle(
            pcb_path=pcb,
            output_dir=out,
            layers=layers,
            include_pos=include_pos,
            create_zip=create_zip,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def export_bom_csv(
        schematic_path: str,
        output_path: str = "",
        fields: str = "Reference,Value,Footprint,${QUANTITY},${DNP}",
    ) -> str:
        """Export a grouped Bill of Materials CSV from a KiCad schematic via `kicad-cli sch export bom`."""
        sch = guard.resolve_and_validate(schematic_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await cli.export_schematic_bom(
            schematic_path=sch,
            output_path=out,
            fields=fields,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def export_step_model(
        pcb_path: str,
        output_path: str = "",
        board_only: bool = False,
        subst_models: bool = True,
    ) -> str:
        """Export a mechanical 3D STEP model via `kicad-cli pcb export step` for Fusion 360 / FreeCAD."""
        pcb = guard.resolve_and_validate(pcb_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await cli.export_pcb_step(
            pcb_path=pcb,
            output_path=out,
            board_only=board_only,
            subst_models=subst_models,
            timeout=max(config.cli_timeout_seconds, 300),
        )
        return json.dumps(result, indent=2)
