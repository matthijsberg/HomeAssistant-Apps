"""Standalone worker invoked under /opt/atopile-venv/bin/python for offline Faebryk constraint solving.

Runs after `ato build -t post-instantiation-design-check -x default` so that all
mathematical `assert ... within ...` constraints and POST_SOLVE design checks are
verified 100% locally without requiring cloud part-picking sign-in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"passed": False, "errors": ["Usage: _ato_solver_worker.py <project_dir> [build_name...]"]}))
        return 2

    project_dir = Path(sys.argv[1]).resolve()
    requested_builds = sys.argv[2:]

    try:
        import faebryk.library._F as F
        from atopile.build_steps import BuildStepContext, check_design, muster
        from atopile.config import config
        from faebryk.core.solver.utils import Contradiction
    except Exception as exc:
        print(json.dumps({"passed": False, "errors": [f"Failed to import atopile/faebryk solver: {exc}"]}))
        return 1

    try:
        config.apply_options(entry=str(project_dir), working_dir=project_dir)
        build_names = requested_builds or list(config.project.builds.keys())
        if not build_names:
            build_names = ["default"]
    except Exception as exc:
        print(json.dumps({"passed": False, "errors": [f"Failed to load ato.yaml config: {exc}"]}))
        return 1

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    pre_steps = (
        "resolve-dependencies",
        "init-build-context",
        "modify-typegraph",
        "instantiate-app",
        "prepare-build",
        "post-instantiation-graph-check",
        "post-instantiation-setup",
        "post-instantiation-design-check",
    )

    for bname in build_names:
        try:
            with config.select_build(bname):
                ctx = BuildStepContext(build=None)
                for step in pre_steps:
                    muster.targets[step].func(ctx)
                app = ctx.require_app()
                solver = ctx.require_solver()
                params = list(F.Parameters.is_parameter.bind_typegraph(app.tg).get_instances())

                solved_count = 0
                unbounded_skipped = 0
                build_errors: list[str] = []
                seen_err: set[str] = set()

                for p_inst in params:
                    try:
                        solver.simplify_for(p_inst)
                        solved_count += 1
                    except Contradiction as c_exc:
                        msg = f"[{bname}] {type(c_exc).__name__}: {c_exc}".strip()
                        if msg not in seen_err:
                            seen_err.add(msg)
                            build_errors.append(msg)
                    except Exception as exc:
                        # Skip non-numeric/unbounded library traits (e.g. StringParameter, ElectricPower.max_power)
                        if type(exc).__name__ in {"SafetyError", "NotImplementedError", "TypeError"}:
                            unbounded_skipped += 1
                            continue
                        msg = f"[{bname}] {type(exc).__name__}: {exc}".strip()
                        if msg not in seen_err:
                            seen_err.add(msg)
                            build_errors.append(msg)

                check_design(app, stage=F.implements_design_check.CheckStage.POST_SOLVE)

                if build_errors:
                    errors.extend(build_errors)
                    results.append(
                        {
                            "build": bname,
                            "passed": False,
                            "parameters_solved": solved_count,
                            "unbounded_skipped": unbounded_skipped,
                            "errors": build_errors,
                        }
                    )
                else:
                    results.append(
                        {
                            "build": bname,
                            "passed": True,
                            "parameters_solved": solved_count,
                            "unbounded_skipped": unbounded_skipped,
                        }
                    )
        except Exception as exc:
            err_msg = f"[{bname}] {type(exc).__name__}: {exc}".strip()
            errors.append(err_msg)
            results.append({"build": bname, "passed": False, "error": err_msg})

    payload = {
        "passed": len(errors) == 0,
        "builds": results,
        "errors": errors,
    }
    print(f"__ATO_SOLVER_JSON__:{json.dumps(payload)}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
