#!/usr/bin/env python3
"""
Reproductions for docs/reviews/2026-10-09-control-logic-review.md
=================================================================
Each check prints the observed behaviour for one finding. Pure in-process, no network,
no Home Assistant, no writes. Written against the pre-fix code; after the fixes it shows the
corrected behaviour (the pinned versions live in tests/unit/test_review_2026_10_09_regressions.py).
Run from the repository root:

    PYTHONPATH=. python3 docs/reviews/2026-10-09-repro.py

Requires numpy + scipy (same as production). Suitable as a starting point for
regression tests under tests/ once the findings are fixed (invert the assertions).
"""

import itertools
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from layer2_calibration.calibrator import ModelCalibrationEngine  # noqa: E402
from layer2_calibration.dhw_thermal_model import DhwThermalModel  # noqa: E402
from layer3_scheduling.dhw_baseline import simulate_autonomous  # noqa: E402
from layer3_scheduling.dhw_optimizer import DhwOptimizerParams, solve  # noqa: E402
from layer3_scheduling.dhw_specs import DhwTankSpec  # noqa: E402
from layer3_scheduling.peak_detection import detect_dynamic_price_peaks  # noqa: E402
from layer4_control.room_thermostat_buffer import RoomThermostatBufferController  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
TAP_MODEL = DhwThermalModel(profile_path="/nonexistent")  # deterministic built-in tap profile


def winter_slots(start: datetime, n: int = 96):
    """Synthetic winter day: evening peak 17-20h, small morning peak, cheap night."""
    slots = []
    for i in range(n):
        dt = start + timedelta(minutes=15 * i)
        h = dt.hour + dt.minute / 60
        price = 0.24 + (0.22 if 17 <= h < 20 else 0) + (0.06 if 7 <= h < 9 else 0) - (0.05 if 1 <= h < 5 else 0)
        slots.append(SimpleNamespace(slot_idx=i, dt=dt, label=dt.strftime("%H:%M"), price_all_in=price,
                                     solar_kw=0.0, unallocated_kw=0.4, outdoor_temp_c=3.0))
    return slots


def peaks_for(slots):
    items = [{"idx": s.slot_idx, "dt": s.dt, "label": s.label, "price": s.price_all_in,
              "solar": s.solar_kw, "unalloc": s.unallocated_kw} for s in slots]
    return detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150)


def check_b1_dp_ignores_lockouts():
    print("\n[B1] DP receives peak objects in the CentralPlanner format (no 'slot_idx')")
    for start_h, t0 in ((17, 41.5), (18, 42.0)):
        slots = winter_slots(datetime(2026, 1, 14, start_h, 0, tzinfo=AMS))
        peaks, slot_map = peaks_for(slots)
        hard = {k for k, v in slot_map.items() if v.get("is_hard_lockout")}
        res = solve(slots=slots, t0_c=t0, dhw_model=TAP_MODEL, params=DhwOptimizerParams(), dynamic_peaks=peaks)
        inside = sorted(set(res.planned_slots) & hard)
        dispatched = [k for k in res.planned_slots if k not in hard]  # CentralPlanner post-strip
        print(f"  start {start_h}:00 tank {t0}°C: DP run inside hard lockout {[slots[k].label for k in inside]}"
              f" -> dispatched after strip {[slots[k].label for k in dispatched[:4]]}")


def check_b3_baseline_guard_feasibility():
    print("\n[B3] Baseline adoption guard compares J without a comfort-feasibility check")
    spec, p = DhwTankSpec(), DhwOptimizerParams()
    from layer3_scheduling.central_planner import CentralPlanner
    has_guard = hasattr(CentralPlanner, "_baseline_is_preferable")
    adopted = breaches = adopted_new = 0
    for start_h, t0 in itertools.product(range(0, 24, 2), (42.0, 45.0, 48.0, 50.0)):
        slots = winter_slots(datetime(2026, 1, 14, start_h, 0, tzinfo=AMS), n=192)
        opt = solve(slots=slots, t0_c=t0, dhw_model=TAP_MODEL, spec=spec, params=p)
        base = simulate_autonomous(slots=slots, t0_c=t0, setpoint_c=50.0, auto_start_delta_c=10.0,
                                   dhw_model=TAP_MODEL, spec=spec, params=p)
        if base.j_objective_eur < opt.j_objective_eur - 0.005:  # pre-fix guard (J only)
            adopted += 1
            breaches += base.min_temp_c < spec.comfort_min_temp_c
        if has_guard and CentralPlanner._baseline_is_preferable(base, opt, spec, p):
            adopted_new += 1
    print(f"  pre-fix rule: baseline adopted in {adopted}/48 scenarios; {breaches} of those dip below 40.0°C")
    if has_guard:
        print(f"  fixed guard (cost AND comfort): baseline adopted in {adopted_new}/48 scenarios")


def check_b4_suboptimal_warning_false_alarm():
    print("\n[B4] 'Solver suboptimal in delay' compares against infeasible fallbacks")
    feasible_better = infeasible_better = total = 0
    for start_h, t0 in itertools.product(range(0, 24, 2), (42.0, 45.0, 48.0)):
        slots = winter_slots(datetime(2026, 1, 14, start_h, 0, tzinfo=AMS))
        opt = solve(slots=slots, t0_c=t0, dhw_model=TAP_MODEL, params=DhwOptimizerParams())
        if not opt.runs:
            continue
        total += 1
        delay = solve(slots=slots, t0_c=t0, dhw_model=TAP_MODEL, params=DhwOptimizerParams(),
                      dynamic_peaks=[{"slot_idx": k, "is_hard_lockout": True} for k in range(opt.runs[0].end_idx)])
        if delay.j_objective_eur < opt.j_objective_eur - 0.005:
            if delay.validation_issue:
                infeasible_better += 1
            else:
                feasible_better += 1
    print(f"  of {total} scenarios: feasible alternative beats DP = {feasible_better}, "
          f"comfort-violating fallback 'beats' DP = {infeasible_better}")


def check_e1_degenerate_regression():
    print("\n[E1] learned_forecaster 3-D OLS uses collinear regressors [dt, dt*0.1, pv/10]")
    import random
    random.seed(1)
    cal = ModelCalibrationEngine(config_path="/nonexistent", params_path="/nonexistent")
    for true_kwh_per_k_day in (5.0, 9.0):
        X, Y = [], []
        for _ in range(40):
            dt, pv = random.uniform(5, 20), random.uniform(0, 25)
            X.append([dt, dt * 0.1, pv / 10.0])
            Y.append(true_kwh_per_k_day * dt - 0.4 * pv + random.gauss(0, 2))
        beta = cal.solve_ols_3x3(X, Y)
        if beta is None:
            print(f"  true UA {true_kwh_per_k_day * 1000 / 24:.0f} W/K -> solver refuses the singular design (fixed: no fake fallback)")
        else:
            print(f"  true UA {true_kwh_per_k_day * 1000 / 24:.0f} W/K -> 'calibrated' UA {beta[0] * 1000 / 24:.1f} W/K (beta={beta})")


def check_a4_dst_fallback():
    print("\n[A4] DST fall-back 2026-10-25: intra-zone datetime arithmetic ignores fold")
    last_plan = datetime(2026, 10, 25, 0, 59, 30, tzinfo=timezone.utc).astimezone(AMS)  # 02:59:30 CEST
    now = datetime(2026, 10, 25, 1, 0, 30, tzinfo=timezone.utc).astimezone(AMS)        # 02:00:30 CET
    age = (now - last_plan).total_seconds()
    print(f"  plan cache age = {age:.0f}s -> '< 60' cache hit: {age < 60} (repeats for ~59 min)")
    grid = [datetime(2026, 10, 25, 1, 45, tzinfo=AMS) + timedelta(minutes=15 * i) for i in range(7)]
    gaps = [int((grid[i + 1].astimezone(timezone.utc) - grid[i].astimezone(timezone.utc)).total_seconds() // 60)
            for i in range(len(grid) - 1)]
    print(f"  sanitizer-style wall-clock grid real gaps (min): {gaps}")


def check_c1_c2_room_thermostat():
    print("\n[C1/C2] Room thermostat buffer controller")
    t = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    c = RoomThermostatBufferController(default_baseline_c=20.5)
    print(f"  user sets 21.5°C, no preheat since start -> watchdog writes {c.watchdog_check(21.5, now=t)}")
    c = RoomThermostatBufferController(default_baseline_c=20.5)
    elevated = c.request_preheat(20.4, 21.5, now=t)
    print(f"  restart while elevated at 21.5°C -> baseline captured {c.baseline_temp_c}, elevated to {elevated}")
    c, now = RoomThermostatBufferController(), datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    for _ in range(2):
        c.request_preheat(20.0, 20.5, now=now)
        now += timedelta(hours=1)
        c.request_release(now=now)
        now += timedelta(hours=1)
    c.watchdog_check(21.0, now=now)
    now += timedelta(hours=1)
    c.request_preheat(20.0, 20.5, now=now)
    print("  2 cycles + 1 watchdog revert + preheat -> release after 1h/6h/12h:",
          [c.request_release(now=now + timedelta(hours=h)) for h in (1, 6, 12)])


if __name__ == "__main__":
    check_b1_dp_ignores_lockouts()
    check_b3_baseline_guard_feasibility()
    check_b4_suboptimal_warning_false_alarm()
    check_e1_degenerate_regression()
    check_a4_dst_fallback()
    check_c1_c2_room_thermostat()
