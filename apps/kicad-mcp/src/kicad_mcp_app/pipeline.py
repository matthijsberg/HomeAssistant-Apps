"""Unified end-to-end electronics design verification pipeline for AI agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import atopile_cli as ato
from . import circuit_rules as rules
from . import kicad_cli as kcli
from . import spice_sim as spice
from .security import WorkspacePathGuard

SKIP_DIRS: frozenset[str] = frozenset({".git", ".ato", ".venv", "__pycache__", "node_modules", "build", "output"})


def _discover_first(root: Path, suffixes: tuple[str, ...]) -> Path | None:
    """Prefer top-level project files, then deterministic shallowest match outside build/cache dirs."""
    if not root.exists():
        return None
    candidates: list[Path] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        rel_parts = item.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if item.name.endswith("-backups") or "backup" in item.name.lower():
            continue
        if item.suffix.lower() in suffixes:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (len(p.relative_to(root).parts), str(p)))
    return candidates[0]


def _discover_spice_netlists(root: Path, max_files: int = 10) -> list[Path]:
    """Discover SPICE testbench files (.cir, .sp) in sim/, spice/, or project root."""
    if not root.exists():
        return []
    found: list[Path] = []
    for search_dir in (root / "sim", root / "spice", root):
        if not search_dir.exists() or not search_dir.is_dir():
            continue
        for item in sorted(search_dir.iterdir()):
            if item.is_file() and item.suffix.lower() in {".cir", ".sp"} and item not in found:
                found.append(item)
                if len(found) >= max_files:
                    return found
    return found


async def run_design_verification(
    project_dir: Path,
    ato_dir: Path | None = None,
    schematic_path: Path | None = None,
    netlist_path: Path | None = None,
    pcb_path: Path | None = None,
    rules_path: Path | None = None,
    spice_netlists: list[Path] | None = None,
    profile: str = "auto",
    run_atopile: bool = True,
    run_erc: bool = True,
    run_circuit_rules: bool = True,
    run_spice: bool = True,
    run_drc: bool = True,
    schematic_parity: bool = False,
    generate_spice_plots: bool = True,
    guard: WorkspacePathGuard | None = None,
    cli_timeout: int = 120,
    sim_timeout: int = 120,
) -> dict[str, Any]:
    """Execute the full electronics verification gate and aggregate results into pass/warn/fail."""
    if not project_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # Auto-discover missing inputs cleanly
    resolved_ato_dir = ato_dir if ato_dir is not None else (project_dir if (project_dir / "ato.yaml").exists() else None)
    resolved_sch = schematic_path or _discover_first(project_dir, (".kicad_sch",))
    resolved_net = netlist_path or _discover_first(project_dir, (".net",))
    resolved_pcb = pcb_path or _discover_first(project_dir, (".kicad_pcb",))
    resolved_rules = rules_path
    if resolved_rules is None:
        for name in ("rules.yaml", "circuit_rules.yaml"):
            cand = project_dir / name
            if cand.exists():
                resolved_rules = cand
                break
    resolved_spice = spice_netlists if spice_netlists is not None else _discover_spice_netlists(project_dir)

    stages: dict[str, dict[str, Any]] = {}
    action_items: list[dict[str, str]] = []

    # 1. atopile offline electrical & constraint check
    if not run_atopile or resolved_ato_dir is None or not (resolved_ato_dir / "ato.yaml").exists():
        stages["atopile_check"] = {
            "status": "skipped",
            "reason": "No ato.yaml present or stage disabled.",
            "errors": 0,
            "warnings": 0,
        }
    else:
        try:
            res = await ato.ato_check(project_dir=resolved_ato_dir, timeout=sim_timeout)
            err_n = 0 if res["passed"] else max(1, len(res.get("errors") or []))
            warn_n = len(res.get("warnings") or [])
            stages["atopile_check"] = {
                "status": "fail" if err_n else ("warn" if warn_n else "pass"),
                "errors": err_n,
                "warnings": warn_n,
                "details": res,
            }
            for e in (res.get("errors") or [])[:5]:
                action_items.append({"stage": "atopile_check", "severity": "error", "message": e})
        except FileNotFoundError as exc:
            stages["atopile_check"] = {
                "status": "skipped",
                "reason": str(exc),
                "errors": 0,
                "warnings": 0,
            }
        except Exception as exc:
            stages["atopile_check"] = {
                "status": "fail",
                "errors": 1,
                "warnings": 0,
                "error": str(exc),
            }
            action_items.append({"stage": "atopile_check", "severity": "error", "message": str(exc)})

    # 2. KiCad ERC
    if not run_erc or resolved_sch is None:
        stages["kicad_erc"] = {
            "status": "skipped",
            "reason": "No .kicad_sch file present or stage disabled.",
            "errors": 0,
            "warnings": 0,
        }
    else:
        try:
            res = await kcli.run_erc(schematic_path=resolved_sch, timeout=cli_timeout)
            err_n = int(res["summary"]["errors"])
            warn_n = int(res["summary"]["warnings"])
            stages["kicad_erc"] = {
                "status": "fail" if err_n else ("warn" if warn_n else "pass"),
                "errors": err_n,
                "warnings": warn_n,
                "details": res,
            }
            for v in (res.get("violations") or [])[:5]:
                if not v.get("excluded"):
                    action_items.append(
                        {
                            "stage": "kicad_erc",
                            "severity": v.get("severity", "error"),
                            "message": f"[{v.get('type')}] {v.get('description')}",
                        }
                    )
        except Exception as exc:
            stages["kicad_erc"] = {"status": "fail", "errors": 1, "warnings": 0, "error": str(exc)}
            action_items.append({"stage": "kicad_erc", "severity": "error", "message": str(exc)})

    # 3. Deterministic Circuit / MCU Rule Checker
    if not run_circuit_rules or (resolved_sch is None and resolved_net is None and resolved_pcb is None):
        stages["circuit_rules"] = {
            "status": "skipped",
            "reason": "No .kicad_sch, .net, or .kicad_pcb file present or stage disabled.",
            "errors": 0,
            "warnings": 0,
        }
    else:
        try:
            use_sch = resolved_sch if resolved_net is None else None
            use_pcb = resolved_pcb if (resolved_net is None and resolved_sch is None) else None
            res = await rules.validate_circuit_file(
                schematic_path=use_sch,
                netlist_path=resolved_net,
                pcb_path=use_pcb,
                profile=profile,
                rules_path=resolved_rules,
                timeout=cli_timeout,
            )
            err_n = int(res["summary"]["errors"])
            warn_n = int(res["summary"]["warnings"])
            stages["circuit_rules"] = {
                "status": "fail" if err_n else ("warn" if warn_n else "pass"),
                "errors": err_n,
                "warnings": warn_n,
                "details": res,
            }
            for f in (res.get("findings") or [])[:10]:
                action_items.append(
                    {
                        "stage": "circuit_rules",
                        "severity": f["severity"],
                        "message": f"[{f['rule_id']}] {f['title']} — {f['recommendation']}",
                    }
                )
        except Exception as exc:
            stages["circuit_rules"] = {"status": "fail", "errors": 1, "warnings": 0, "error": str(exc)}
            action_items.append({"stage": "circuit_rules", "severity": "error", "message": str(exc)})

    # 4. ngspice Simulations
    if not run_spice or not resolved_spice:
        stages["spice_simulations"] = {
            "status": "skipped",
            "reason": "No .cir/.sp testbenches found or stage disabled.",
            "errors": 0,
            "warnings": 0,
        }
    else:
        sim_results: list[dict[str, Any]] = []
        sim_errors = 0
        for cir in resolved_spice:
            try:
                # Inspect file for existing .tran/.ac/.control directives; run 'raw' if present else 'op'
                raw_text = cir.read_text(encoding="utf-8", errors="replace")
                has_directive = any(
                    line.strip().lower().startswith((".tran", ".ac", ".dc", ".op", ".control"))
                    for line in raw_text.splitlines()
                )
                mode = "raw" if has_directive else "op"
                plot_path = (
                    (project_dir / "sim_plots" / f"{cir.stem}.png")
                    if (generate_spice_plots and mode in {"tran", "ac"})
                    else None
                )
                res = await spice.run_spice_simulation(
                    netlist_path=cir,
                    analysis=mode,
                    plot_output_path=plot_path,
                    guard=guard,
                    timeout=sim_timeout,
                )
                sim_results.append(res)
                if not res["passed"]:
                    sim_errors += 1
                    action_items.append(
                        {
                            "stage": "spice_simulations",
                            "severity": "error",
                            "message": f"SPICE failed on {cir.name}: {'; '.join(res.get('errors') or ['non-zero exit'])}",
                        }
                    )
            except Exception as exc:
                sim_errors += 1
                sim_results.append({"source": str(cir), "passed": False, "errors": [str(exc)]})
                action_items.append(
                    {"stage": "spice_simulations", "severity": "error", "message": f"{cir.name}: {exc}"}
                )
        stages["spice_simulations"] = {
            "status": "fail" if sim_errors else "pass",
            "errors": sim_errors,
            "warnings": 0,
            "count": len(sim_results),
            "results": sim_results,
        }

    # 5. KiCad DRC
    if not run_drc or resolved_pcb is None:
        stages["kicad_drc"] = {
            "status": "skipped",
            "reason": "No .kicad_pcb file present or stage disabled.",
            "errors": 0,
            "warnings": 0,
        }
    else:
        try:
            res = await kcli.run_drc(
                pcb_path=resolved_pcb,
                schematic_parity=schematic_parity,
                all_track_errors=True,
                timeout=cli_timeout,
            )
            err_n = int(res["summary"]["errors"])
            warn_n = int(res["summary"]["warnings"])
            stages["kicad_drc"] = {
                "status": "fail" if err_n else ("warn" if warn_n else "pass"),
                "errors": err_n,
                "warnings": warn_n,
                "details": res,
            }
            for v in (res.get("violations") or [])[:5]:
                if not v.get("excluded"):
                    action_items.append(
                        {
                            "stage": "kicad_drc",
                            "severity": v.get("severity", "error"),
                            "message": f"[{v.get('type')}] {v.get('description')}",
                        }
                    )
        except Exception as exc:
            stages["kicad_drc"] = {"status": "fail", "errors": 1, "warnings": 0, "error": str(exc)}
            action_items.append({"stage": "kicad_drc", "severity": "error", "message": str(exc)})

    total_errors = sum(int(st.get("errors", 0)) for st in stages.values())
    total_warnings = sum(int(st.get("warnings", 0)) for st in stages.values())
    executed = [name for name, st in stages.items() if st["status"] != "skipped"]

    if total_errors > 0:
        overall_status = "fail"
    elif total_warnings > 0:
        overall_status = "warn"
    else:
        overall_status = "pass"

    return {
        "overall_status": overall_status,
        "passed": total_errors == 0,
        "project_dir": str(project_dir),
        "discovered": {
            "ato_dir": str(resolved_ato_dir) if resolved_ato_dir else None,
            "schematic_path": str(resolved_sch) if resolved_sch else None,
            "netlist_path": str(resolved_net) if resolved_net else None,
            "pcb_path": str(resolved_pcb) if resolved_pcb else None,
            "rules_path": str(resolved_rules) if resolved_rules else None,
            "spice_netlists": [str(p) for p in resolved_spice],
        },
        "summary": {
            "executed_stages": executed,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        },
        "stages": stages,
        "action_items": action_items[:30],
    }
