"""First-class headless KiCad 9 CLI tools registered on the shared FastMCP server."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from . import __version__
from . import atopile_cli as ato
from . import circuit_rules as rules
from . import kicad_cli as cli
from . import pipeline as pipe
from . import spice_sim as spice
from .config import AppConfig
from .security import WorkspacePathGuard


def register_extra_tools(mcp: FastMCP, config: AppConfig, guard: WorkspacePathGuard) -> None:
    """Register headless KiCad 9, ngspice, atopile, circuit-rule & pipeline MCP tools."""

    @mcp.tool()
    async def kicad_health() -> str:
        """Return runtime health and versions for KiCad CLI, pcbnew, ngspice, atopile, and workspace config."""
        version = await cli.get_kicad_version()
        ngspice_ver = await spice.get_ngspice_version()
        ato_ver = await ato.get_atopile_version()
        payload = {
            "status": "ok",
            "app_version": __version__,
            "kicad_cli_version": version,
            "pcbnew_available": cli.check_pcbnew_available(),
            "ngspice_version": ngspice_ver,
            "atopile_version": ato_ver,
            "workspace_root": str(guard.workspace_root),
            "allowed_roots": [str(r) for r in guard.allowed_roots],
            "read_only": config.read_only,
            "allow_network_packages": config.allow_network_packages,
        }
        return json.dumps(payload, indent=2)

    @mcp.tool()
    async def list_workspace_projects(directory: str = "", max_results: int = 100) -> str:
        """Discover KiCad, atopile, and SPICE files (.kicad_pro, .kicad_pcb, .kicad_sch, ato.yaml, .ato, .cir, .sp, .net) inside the workspace."""
        root = guard.resolve_and_validate(directory) if directory.strip() else guard.workspace_root
        if not root.exists():
            return json.dumps({"root": str(root), "exists": False, "files": []}, indent=2)

        exts = {".kicad_pro", ".kicad_pcb", ".kicad_sch", ".ato", ".cir", ".sp", ".net"}
        found: list[dict[str, str]] = []
        for path in sorted(root.rglob("*")):
            if len(found) >= max_results:
                break
            if path.is_file() and (path.suffix in exts or path.name == "ato.yaml"):
                found.append(
                    {
                        "type": "ato_yaml" if path.name == "ato.yaml" else path.suffix.lstrip("."),
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

    # ---- Design-as-Code (atopile) tools ----

    @mcp.tool()
    async def ato_init_project(
        project_dir: str,
        project_name: str,
        template: str = "esp32_sensor",
        overwrite: bool = False,
    ) -> str:
        """Scaffold a clean atopile project (ato.yaml + main.ato) using template 'esp32_sensor' or 'basic'."""
        target = guard.resolve_and_validate(project_dir)
        result = ato.ato_init_project(
            project_dir=target,
            project_name=project_name,
            template=template,
            overwrite=overwrite,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def ato_add_package(
        project_dir: str,
        packages: list[str],
        upgrade: bool = False,
    ) -> str:
        """Add one or more atopile packages to an ato.yaml project (subject to allow_network_packages)."""
        target = guard.resolve_and_validate(project_dir)
        result = await ato.ato_add_package(
            project_dir=target,
            packages=packages,
            upgrade=upgrade,
            allow_network=config.allow_network_packages,
            timeout=config.sim_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def ato_check(
        project_dir: str,
        build_names: list[str] | None = None,
    ) -> str:
        """Run 100% offline atopile electrical, interface-graph, and constraint verification on a project."""
        target = guard.resolve_and_validate(project_dir)
        result = await ato.ato_check(
            project_dir=target,
            build_names=build_names,
            timeout=config.sim_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def ato_build(
        project_dir: str,
        build_names: list[str] | None = None,
        targets: list[str] | None = None,
        exclude_targets: list[str] | None = None,
        frozen: bool = False,
        offline_check_only: bool = False,
    ) -> str:
        """Run atopile build on a project directory and list generated KiCad layout/BOM artifacts."""
        target = guard.resolve_and_validate(project_dir)
        result = await ato.ato_build(
            project_dir=target,
            build_names=build_names,
            targets=targets,
            exclude_targets=exclude_targets,
            frozen=frozen,
            offline_check_only=offline_check_only,
            timeout=max(config.sim_timeout_seconds, 180),
        )
        return json.dumps(result, indent=2)

    # ---- Deterministic Electrical & MCU Domain Rule Validator ----

    @mcp.tool()
    async def validate_circuit_rules(
        schematic_path: str = "",
        netlist_path: str = "",
        pcb_path: str = "",
        profile: str = "auto",
        rules_path: str = "",
    ) -> str:
        """Validate a KiCad schematic (.kicad_sch), S-expr netlist (.net), or PCB (.kicad_pcb) against deterministic electrical/ESP32/sensor rules."""
        sch = guard.resolve_and_validate(schematic_path) if schematic_path.strip() else None
        net = guard.resolve_and_validate(netlist_path) if netlist_path.strip() else None
        pcb = guard.resolve_and_validate(pcb_path) if pcb_path.strip() else None
        rpath = guard.resolve_and_validate(rules_path) if rules_path.strip() else None
        result = await rules.validate_circuit_file(
            schematic_path=sch,
            netlist_path=net,
            pcb_path=pcb,
            profile=profile,
            rules_path=rpath,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    # ---- Analog / Mixed-Signal SPICE Simulation (ngspice) ----

    @mcp.tool()
    async def export_spice_netlist(
        schematic_path: str,
        output_path: str = "",
        format_mode: str = "spice",
    ) -> str:
        """Export a KiCad schematic (.kicad_sch) to a SPICE netlist (.cir) via kicad-cli."""
        sch = guard.resolve_and_validate(schematic_path)
        out = guard.resolve_and_validate(output_path) if output_path.strip() else None
        result = await spice.export_spice_netlist(
            schematic_path=sch,
            output_path=out,
            format_mode=format_mode,
            timeout=config.cli_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def run_spice_simulation(
        netlist_path: str = "",
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
        plot_output_path: str = "",
        plot_title: str = "",
    ) -> str:
        """Run headless ngspice simulation ('op', 'tran', 'ac', or 'raw') and optionally render a Pillow PNG waveform plot."""
        npath = guard.resolve_and_validate(netlist_path) if netlist_path.strip() else None
        ppath = guard.resolve_and_validate(plot_output_path) if plot_output_path.strip() else None
        result = await spice.run_spice_simulation(
            netlist_path=npath,
            netlist_content=netlist_content,
            analysis=analysis,
            probes=probes,
            step=step,
            stop=stop,
            start=start,
            ac_variation=ac_variation,
            ac_points=ac_points,
            ac_fstart=ac_fstart,
            ac_fstop=ac_fstop,
            plot_output_path=ppath,
            plot_title=plot_title,
            guard=guard,
            timeout=config.sim_timeout_seconds,
        )
        return json.dumps(result, indent=2)

    # ---- Unified Agent Verification Gate ----

    @mcp.tool()
    async def run_design_verification(
        project_dir: str,
        ato_dir: str = "",
        schematic_path: str = "",
        netlist_path: str = "",
        pcb_path: str = "",
        rules_path: str = "",
        spice_netlists: list[str] | None = None,
        profile: str = "auto",
        run_atopile: bool = True,
        run_erc: bool = True,
        run_circuit_rules: bool = True,
        run_spice: bool = True,
        run_drc: bool = True,
        schematic_parity: bool = False,
        generate_spice_plots: bool = True,
    ) -> str:
        """Run the full electronics verification gate (atopile -> KiCad ERC -> circuit rules -> ngspice -> KiCad DRC) in one call."""
        pdir = guard.resolve_and_validate(project_dir)
        adir = guard.resolve_and_validate(ato_dir) if ato_dir.strip() else None
        sch = guard.resolve_and_validate(schematic_path) if schematic_path.strip() else None
        net = guard.resolve_and_validate(netlist_path) if netlist_path.strip() else None
        pcb = guard.resolve_and_validate(pcb_path) if pcb_path.strip() else None
        rpath = guard.resolve_and_validate(rules_path) if rules_path.strip() else None
        slist = (
            [guard.resolve_and_validate(item) for item in spice_netlists if item.strip()]
            if spice_netlists is not None
            else None
        )
        result = await pipe.run_design_verification(
            project_dir=pdir,
            ato_dir=adir,
            schematic_path=sch,
            netlist_path=net,
            pcb_path=pcb,
            rules_path=rpath,
            spice_netlists=slist,
            profile=profile,
            run_atopile=run_atopile,
            run_erc=run_erc,
            run_circuit_rules=run_circuit_rules,
            run_spice=run_spice,
            run_drc=run_drc,
            schematic_parity=schematic_parity,
            generate_spice_plots=generate_spice_plots,
            guard=guard,
            cli_timeout=config.cli_timeout_seconds,
            sim_timeout=config.sim_timeout_seconds,
        )
        return json.dumps(result, indent=2)
