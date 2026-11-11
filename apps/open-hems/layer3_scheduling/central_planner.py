"""
Layer 3: Central HEMS Dispatch Planner
======================================
The single source of truth dispatch optimization engine.
Produces an authoritative, unalterable CanonicalDispatchPlan from a CleanTelemetryFrame.

Strictly preserves all operational and physical directives:
- 350L DHW vat (0.407 kWh/K)
- Fysieke dag-prioriteit: overdag (10:00–16:00) altijd eerst dagrun/zonnebuffer (50°C of 60°C) vóór nachtrun
- Nachtdal tie-breaker naar 03:30u bij gelijke prijzen
- Dynamische spitsblokkade met P75/P85, Delta P >= €0.030, micro-piek filter (<30m) en harde wintercap van 150m (2,5u)
- Gestandaardiseerde 6-status taxonomie (forced_off, advised_off, normal, advised_on, forced_on, max_on)

Concurrency & ownership contract:
- The planner READS the in-flight DHW run commitment from the PlanStore but never writes it;
  the single owner is layer4_control.dhw_run_supervisor.DhwRunSupervisor.
- Hard peak lockouts are resolved once per plan into a per-slot set and handed to every
  consumer (DP optimizer, autonomous baseline, space heating, battery).
- Every DHW slot carries the stop temperature (target_temp_c) of the run it belongs to.
"""

import math
from typing import List, Dict, Any, Optional, Set
from models.canonical import (
    StandardizedState,
    get_state_metadata,
    DispatchPlanSlot,
    DHWPlanSummary,
    CanonicalDispatchPlan,
    DeviceSlotDispatch,
    Quality,
)
from layer3_scheduling.peak_detection import (
    detect_dynamic_price_peaks
)
from layer1_data_collection.sanitizer import CleanTelemetryFrame
from layer3_scheduling.plan_store import get_plan_store, PlanStore
from layer3_scheduling.tariff_provider import TariffProvider
from layer3_scheduling.dhw_specs import DhwTankSpec
from layer3_scheduling.dhw_shadow_logger import get_dhw_planner_mode, run_dhw_shadow_comparison
from layer3_scheduling.dhw_optimizer import solve, DhwOptimizerParams, result_from_u_plan
from layer3_scheduling.dhw_plan_adapter import adapt_optimizer_to_dhw_summary
from layer3_scheduling.dhw_policy import DHW_ENGINES, DhwPolicyParams, plan_dhw
from layer3_scheduling.dhw_policy_adapter import policy_result_to_summary

# Remaining-run estimate for an in-flight commitment (°C gained per 15-minute slot)
IN_FLIGHT_DEG_PER_SLOT = 2.2
# Hysteresis below the run target at which a DHW run counts as finished (shared with Layer 4)
DHW_TARGET_HYSTERESIS_C = 0.2
# Runs ending at or above this temperature are boost runs (MAX_ON)
BOOST_RUN_THRESHOLD_C = 52.0


class CentralPlanner:
    """Central deterministic dispatch planner for all HEMS energy vectors."""

    # Physical constants (User memory & thermodynamic calibration)
    DHW_TANK_LITERS = 350.0
    DHW_THERMAL_CAPACITY_KWH_PER_K = 0.407  # 350L * 4.184 kJ/(kg*K) / 3600
    DHW_STANDBY_LOSS_KW = 0.055             # ~1.3 kWh/24h standing loss

    @classmethod
    def _consolidate_dhw_runs(
        cls,
        planned_slots: List[int],
        max_gap_slots: int = 6,
        blocked_slots: Optional[Set[int]] = None
    ) -> List[int]:
        """
        Consolidates fragmented DHW runs occurring within a short idle window (gap <= max_gap_slots)
        into a single continuous cycle, preventing unnecessary compressor restarts. The later run is
        pulled forward to follow the earlier one (same number of heating slots). A run is never
        pulled into a blocked slot (hard or soft peak).
        """
        if not planned_slots:
            return []
        blocked = blocked_slots or set()
        sorted_slots = sorted(planned_slots)
        runs = []
        current_run = [sorted_slots[0]]
        for s in sorted_slots[1:]:
            if s == current_run[-1] + 1:
                current_run.append(s)
            else:
                runs.append(current_run)
                current_run = [s]
        runs.append(current_run)

        consolidated_runs = [runs[0]]
        for next_run in runs[1:]:
            prev_run = consolidated_runs[-1]
            gap = next_run[0] - prev_run[-1] - 1
            if 0 < gap <= max_gap_slots:
                new_run = list(range(prev_run[0], prev_run[-1] + 1 + len(next_run)))
                if not any(k in blocked for k in new_run[len(prev_run):]):
                    consolidated_runs[-1] = new_run
                    continue
            consolidated_runs.append(next_run)

        res = []
        for r in consolidated_runs:
            res.extend(r)
        return res

    @classmethod
    def _baseline_is_preferable(cls, base_res: Any, opt_res: Any, spec: DhwTankSpec,
                                params: DhwOptimizerParams, in_flight_slots: int = 0) -> bool:
        """
        The autonomous baseline replaces the optimizer only if it is cheaper on the same objective J
        AND satisfies the same comfort floor (t_comf + minimum margin). A plan that is cheaper only
        because it lets the tank drop below comfort is never adopted (review finding B3).
        """
        if in_flight_slots > 0:
            return False
        comfort_floor_c = spec.comfort_min_temp_c + float(getattr(params, "min_comfort_margin_c", 0.0))
        if base_res.min_temp_c < comfort_floor_c - 1e-3:
            return False
        return base_res.j_objective_eur < opt_res.j_objective_eur - 0.005

    @classmethod
    def _sensor_unavailable_dhw_summary(cls, dynamic_peaks: List[Dict[str, Any]]) -> DHWPlanSummary:
        """Elephant baseline summary used when the tank temperature is unknown (never invented)."""
        meta = get_state_metadata(StandardizedState.NORMAL)
        return DHWPlanSummary(
            planned_mode="normal",
            planned_mode_label="Tanktemperatuur onbekend — Daikin autonoom (Elephant baseline)",
            color_hex=meta.get("color_hex", "#94A3B8"),
            tailwind_class=meta.get("tailwind_text", "text-slate-400"),
            target_temp_c=50.0,
            run_start="Geen run",
            run_end="Geen run",
            run_duration_min=0,
            power_kw=0.0,
            total_stroom_kwh=0.0,
            spits_lockout_hours=round(sum(p.get("hard_duration_mins", 0) for p in dynamic_peaks if p.get("is_hard_lockout")) / 60.0, 1),
            dynamic_peaks=dynamic_peaks,
            unheated_trajectory=[],
            counterfactual_reason="Geen geldige tanktemperatuur: Open HEMS stuurt het boilervat niet en laat de Daikin autonoom regelen.",
            arbitrage_saving_eur=0.0,
            decision_details={"status": "SENSOR_UNAVAILABLE", "planned_mode": "normal"}
        )

    @classmethod
    def _battery_context_from_config(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        installed = any(
            d.get("type") in ("home_battery", "battery", "battery_storage") and d.get("installed", False) and d.get("enabled", False)
            for d in cfg.get("devices", []) if isinstance(d, dict)
        )
        return {
            "installed": installed,
            "simulate": bool(cfg.get("simulate_battery", False) or cfg.get("battery", {}).get("plan_simulation", True)),
            "soc_pct": None,
            "simulation_initial_soc_pct": float(cfg.get("battery", {}).get("simulation_initial_soc_pct", 50.0)),
        }

    @classmethod
    def _plan_battery(
        cls,
        cfg: Dict[str, Any],
        dispatch_slots: List[DispatchPlanSlot],
        hard_slots: Set[int],
        tp: TariffProvider,
        battery_context: Dict[str, Any],
        step_hours: float,
    ):
        """Priority 3: battery dispatch on the residual of baseload + DHW + space heating − solar."""
        from layer3_scheduling.battery_policy import BatteryPolicy, BatterySpec

        installed = bool(battery_context.get("installed"))
        simulate = bool(battery_context.get("simulate"))
        if not installed and not simulate:
            return None

        if installed:
            initial_soc = battery_context.get("soc_pct")  # live telemetry only; None => inactive plan
        else:
            initial_soc = float(battery_context.get("simulation_initial_soc_pct", 50.0))

        residual = [round(s.unallocated_kw + s.heating_kw + s.dhw_kw - s.solar_kw, 3) for s in dispatch_slots]
        prices = [s.price_eur for s in dispatch_slots]
        export_prices = [round(tp.calculate_export_value_from_import(p), 4) for p in prices]
        spec = BatterySpec.from_config(
            cfg,
            reserve_lookahead_slots=len(dispatch_slots),
            valley_lookahead_slots=len(dispatch_slots)
        )
        summary = BatteryPolicy.optimize(
            residual_demand_kw=residual,
            import_prices=prices,
            export_prices=export_prices,
            spec=spec,
            initial_soc_pct=initial_soc,
            step_hours=step_hours,
            forced_off_indices=set(hard_slots)
        )
        summary.is_simulation = not installed

        if summary.is_active:
            for s, b in zip(dispatch_slots, summary.slots):
                s.device_dispatches["home_battery"] = DeviceSlotDispatch(
                    device_id="home_battery",
                    device_type="battery",
                    mode_code=b.mode_code,
                    mode_label=b.mode_label,
                    electric_kw=b.power_kw,
                    payload={"soc_pct": b.soc_pct, "is_simulation": summary.is_simulation}
                )
                if installed:
                    # Real battery: its charge (+) / discharge (−) is part of the grid balance
                    s.net_import_kw = round(s.net_import_kw + b.power_kw, 3)
        return summary

    @classmethod
    def plan(
        cls,
        frame: CleanTelemetryFrame,
        current_dhw_temp: Optional[float] = 48.0,
        model_parameters: Optional[Dict[str, Any]] = None,
        tariffs: Optional[TariffProvider] = None,
        store: Optional[PlanStore] = None,
        past_continuous_lockout_mins: int = 0,
        mins_since_last_lockout: int = 999,
        dhw_spec: Optional[DhwTankSpec] = None,
        dhw_optimizer_params: Optional[DhwOptimizerParams] = None,
        dhw_compressor_running: bool = False,
        battery_context: Optional[Dict[str, Any]] = None,
        dhw_policy_params: Optional[DhwPolicyParams] = None,
        dhw_engine: Optional[str] = None,
    ) -> CanonicalDispatchPlan:
        """
        Executes central optimization and returns the single authoritative CanonicalDispatchPlan.

        current_dhw_temp: measured tank temperature, or None when the sensor is unavailable
          (DHW is then left to the Daikin's own thermostat; nothing is forced).
        dhw_compressor_running: True when telemetry (3-way valve + compressor power) shows the
          heat pump is heating DHW right now; the DP then decides whether to continue it.
        battery_context: {"installed", "simulate", "soc_pct", "simulation_initial_soc_pct"}.
        dhw_engine: "daikin_first" (ADR-006, default) or "dp" (ADR-004, fallback during the transition);
          defaults to cfg['dhw_policy']['engine'].
        """
        try:
            from api.secrets_store import CONFIG_FILE, load_json
            cfg = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
        except Exception:
            cfg = {}

        spec = dhw_spec if dhw_spec is not None else DhwTankSpec.from_config(cfg)

        if dhw_optimizer_params is None:
            dhw_optimizer_params = DhwOptimizerParams.from_config(cfg)
        if dhw_policy_params is None:
            dhw_policy_params = DhwPolicyParams.from_config(cfg)
        if dhw_engine is None:
            dhw_engine = str((cfg.get("dhw_policy", {}) or {}).get("engine", "daikin_first"))
        if dhw_engine not in DHW_ENGINES:
            dhw_engine = "daikin_first"

        if model_parameters is None:
            try:
                from api.secrets_store import PARAMS_FILE, load_json
                model_parameters = load_json(PARAMS_FILE) if PARAMS_FILE.exists() else {}
            except Exception:
                model_parameters = {}

        target_store = store or get_plan_store()
        tp = tariffs or TariffProvider.from_dict(cfg)
        now = frame.timestamp
        step_mins = frame.resolution_minutes
        slots = frame.slots
        n_slots = len(slots)
        step_hours = step_mins / 60.0

        if past_continuous_lockout_mins == 0 and frame.metadata:
            past_continuous_lockout_mins = frame.metadata.get("past_continuous_lockout_mins", 0)
        if mins_since_last_lockout == 999 and frame.metadata:
            mins_since_last_lockout = frame.metadata.get("mins_since_last_lockout", 999)

        # Timeline items for canonical peak detector
        timeline_items = []
        for s in slots:
            timeline_items.append({
                "idx": s.slot_idx,
                "dt": s.dt,
                "label": s.label,
                "price": s.price_all_in,
                "solar": s.solar_kw,
                "unalloc": s.unallocated_kw
            })

        # 1. Dynamic Spitsblokkades (Central Peak Detector with Winter Cap & Past Awareness)
        dynamic_peaks, slot_lockout_map = detect_dynamic_price_peaks(
            timeline_items=timeline_items,
            step_mins=step_mins,
            max_lockout_mins=150,  # Hard 2.5 hour winter comfort cap
            past_continuous_lockout_mins=past_continuous_lockout_mins,
            mins_since_last_lockout=mins_since_last_lockout
        )
        # Single per-slot truth for every consumer (DP, baseline, space heating, battery, dispatch)
        # Invariant: hard lockouts are strictly restricted to verified EPEX Day-Ahead slots.
        # Forecast slots (> Day-Ahead) remain informative only and never trigger forced lockouts.
        hard_slots: Set[int] = {
            k for k, v in slot_lockout_map.items()
            if v.get("is_hard_lockout") and getattr(slots[k], "price_quality", Quality.GOOD) != Quality.FORECAST
        }
        peak_slots: Set[int] = set(slot_lockout_map.keys())

        # 2. Simulate Counterfactual (Unheated) DHW Tank Trajectory using Calibrated DhwThermalModel
        from layer2_calibration.dhw_thermal_model import DhwThermalModel
        dhw_model = DhwThermalModel()

        # 3. DHW Boiler 350L Dispatch Engine
        planned_dhw_slots: List[int] = []
        autonomous_dhw_slots: Set[int] = set()
        slot_run_target: Dict[int, float] = {}
        dhw_kw_by_slot: Optional[List[float]] = None   # daikin_first: expected DHW power per slot from the policy
        planned_mode = "normal"
        daytime_arbitrage_audit: Dict[str, Any] = {}
        res_opt = None
        baseline_adopted = False
        validation_issues = list(frame.validation_errors)

        # Priority 0: DHW Circuit Disabled in Home Assistant (e.g. Vacation / Holiday / Off)
        if not getattr(frame, "is_dhw_enabled", True):
            dhw_summary = DHWPlanSummary(
                planned_mode="off",
                planned_mode_label="DHW Uitgeschakeld",
                color_hex="#64748B",
                tailwind_class="text-slate-500",
                target_temp_c=50.0,
                run_start="Geen run",
                run_end="Geen run",
                run_duration_min=0,
                power_kw=0.0,
                total_stroom_kwh=0.0,
                spits_lockout_hours=round(sum(p.get("hard_duration_mins", 0) for p in dynamic_peaks if p.get("is_hard_lockout")) / 60.0, 1),
                dynamic_peaks=dynamic_peaks,
                unheated_trajectory=[],
                counterfactual_reason="DHW circuit is uitgeschakeld in instellingen.",
                arbitrage_saving_eur=0.0,
                decision_details={"status": "OFF", "planned_mode": "off"}
            )
            planned_mode = "off"
        elif current_dhw_temp is None:
            # Priority 0b: no valid tank reading -> never plan on an invented temperature
            dhw_summary = cls._sensor_unavailable_dhw_summary(dynamic_peaks)
            validation_issues.append("DHW: tanktemperatuur onbekend; geen DHW-sturing in dit plan")
        elif dhw_engine == "daikin_first":
            # ADR-006: rule-based Daikin-first policy; the plan is the rollout of the rules.
            # The in-flight run (owned by Layer 4) is only read, as the starting state of the rollout.
            in_flight = target_store.get_in_flight_run()
            in_flight_target = float(in_flight.get("target_temp_c", spec.target_setpoint_c)) if in_flight else None
            policy_res = plan_dhw(
                slots=slots,
                t0_c=current_dhw_temp,
                hard_slots=hard_slots,
                dhw_model=dhw_model,
                tariff_provider=tp,
                spec=spec,
                model_parameters=model_parameters,
                params=dhw_policy_params,
                compressor_heating=dhw_compressor_running,
                in_flight_target_c=in_flight_target,
            )
            dhw_summary = policy_result_to_summary(
                policy_res, slots, current_dhw_temp, spec=spec, dynamic_peaks=dynamic_peaks,
                params=dhw_policy_params, hard_slots=hard_slots,
            )
            planned_mode = dhw_summary.planned_mode
            planned_dhw_slots = list(policy_res.forced_slots)
            autonomous_dhw_slots = set(policy_res.autonomous_slots)
            slot_run_target = {k: t for k, t in enumerate(policy_res.slot_targets) if t is not None}
            dhw_kw_by_slot = list(policy_res.slot_dhw_kw)
            daytime_arbitrage_audit = dhw_summary.decision_details or {}
        else:
            planner_mode = get_dhw_planner_mode(model_parameters)

            # Read-only view of the in-flight run commitment (owned by Layer 4)
            in_flight = target_store.get_in_flight_run()
            in_flight_slots = 0
            in_flight_target_c = spec.target_setpoint_c
            if in_flight:
                in_flight_target_c = float(in_flight.get("target_temp_c", spec.target_setpoint_c))
                if current_dhw_temp < in_flight_target_c - DHW_TARGET_HYSTERESIS_C:
                    delta_t_rem = in_flight_target_c - current_dhw_temp
                    in_flight_slots = max(1, min(6, math.ceil(delta_t_rem / IN_FLIGHT_DEG_PER_SLOT)))

            if in_flight_slots > 0:
                run_state0: Any = ("ON_MANDATORY", 1)
            elif dhw_compressor_running:
                # Compressor already heating DHW (autonomous or ours): DP decides to continue or stop
                run_state0 = ("ON_FREE", 0)
            else:
                run_state0 = ("OFF_FREE", 0)

            res_opt = solve(
                slots=slots,
                t0_c=current_dhw_temp,
                run_state0=run_state0,
                dhw_model=dhw_model,
                tariff_provider=tp,
                spec=spec,
                params=dhw_optimizer_params,
                dynamic_peaks=dynamic_peaks,
                model_parameters=model_parameters,
                in_flight_slots=in_flight_slots,
                in_flight_target_c=in_flight_target_c
            )

            # Autonomous baseline (WP7): the counterfactual "Open HEMS does nothing"
            from layer3_scheduling.dhw_baseline import simulate_autonomous
            base_res = simulate_autonomous(
                slots=slots,
                t0_c=current_dhw_temp,
                setpoint_c=spec.target_setpoint_c,
                auto_start_delta_c=spec.auto_start_delta_c,
                dhw_model=dhw_model,
                spec=spec,
                params=dhw_optimizer_params,
                model_parameters=model_parameters,
                hard_lockout_slots=hard_slots
            )

            # Guard: adopt the baseline only if it is cheaper AND meets the same comfort floor.
            # Adopting it means "do not intervene": no forced slots; the Daikin heats autonomously.
            if cls._baseline_is_preferable(base_res, res_opt, spec, dhw_optimizer_params, in_flight_slots):
                baseline_adopted = True
                autonomous_dhw_slots = {i for i, u in enumerate(base_res.u_plan) if u == 1 and i not in hard_slots}
                res_opt = result_from_u_plan(
                    slots=slots, u_plan=[0] * n_slots, t0_c=current_dhw_temp, spec=spec,
                    params=dhw_optimizer_params, tariff_provider=tp, dhw_model=dhw_model,
                    run_state0=run_state0, model_parameters=model_parameters
                )
                # Display the trajectory that will physically happen (autonomous thermostat)
                res_opt.trajectory["temperatures_c"] = base_res.temperatures_c
                res_opt.trajectory["temperatures_p05_c"] = base_res.temperatures_p05_c
                res_opt.trajectory["temperatures_p95_c"] = base_res.temperatures_p95_c
                res_opt.j_objective_eur = base_res.j_objective_eur
                res_opt.total_cost_eur = base_res.total_cost_eur
                res_opt.electricity_cost_eur = base_res.electricity_cost_eur
                res_opt.start_cost_eur = base_res.start_cost_eur
                res_opt.salvage_value_eur = base_res.salvage_value_eur
            else:
                # Consolidate fragmented runs, never across a peak, and re-simulate so that
                # summary, trajectory and dispatch describe the same plan.
                consolidated = cls._consolidate_dhw_runs(res_opt.planned_slots, max_gap_slots=6, blocked_slots=peak_slots)
                if set(consolidated) != set(res_opt.planned_slots):
                    u_cons = [1 if k in set(consolidated) else 0 for k in range(n_slots)]
                    res_opt = result_from_u_plan(
                        slots=slots, u_plan=u_cons, t0_c=current_dhw_temp, spec=spec,
                        params=dhw_optimizer_params, tariff_provider=tp, dhw_model=dhw_model,
                        run_state0=run_state0, model_parameters=model_parameters,
                        validation_issue=res_opt.validation_issue
                    )

            dhw_summary = adapt_optimizer_to_dhw_summary(
                opt_result=res_opt,
                slots=slots,
                t0_c=current_dhw_temp,
                run_state0=run_state0,
                dhw_model=dhw_model,
                tariff_provider=tp,
                spec=spec,
                params=dhw_optimizer_params,
                dynamic_peaks=dynamic_peaks,
                model_parameters=model_parameters
            )
            if baseline_adopted:
                dhw_summary.planned_mode_label = "Normaal — Daikin autonoom is goedkoper (geen ingreep)"
                if dhw_summary.decision_details is not None:
                    dhw_summary.decision_details["baseline_adopted"] = True

            planned_mode = dhw_summary.planned_mode
            planned_dhw_slots = list(res_opt.planned_slots)
            daytime_arbitrage_audit = dhw_summary.decision_details or {}

            for run in res_opt.runs:
                for k in range(run.start_idx, min(run.end_idx, n_slots)):
                    slot_run_target[k] = round(float(run.t_end_c), 1)

            if planner_mode == "shadow":
                shadow_record = run_dhw_shadow_comparison(
                    slots=slots,
                    current_dhw_temp=current_dhw_temp,
                    dynamic_peaks=dynamic_peaks,
                    arbiter_planned_slots=planned_dhw_slots,
                    dhw_model=dhw_model,
                    tariff_provider=tp,
                    spec=spec,
                    now_dt=now,
                    run_state0=run_state0
                )
                daytime_arbitrage_audit["shadow_comparison"] = shadow_record

        # Defensive: the DP is lockout-aware, so this must never drop anything.
        final_dhw_slots = [s_idx for s_idx in planned_dhw_slots if s_idx not in hard_slots]
        if len(final_dhw_slots) != len(planned_dhw_slots):
            validation_issues.append("DHW: geplande run viel in harde spitsblokkade en is verwijderd")
        final_dhw_set = set(final_dhw_slots)

        # 4. Space Heating: Daikin-in-the-loop forecast and pre-heat decisions (floor/room network)
        from layer3_scheduling.space_heating_policy import SpaceHeatingPolicy

        heating_plan = SpaceHeatingPolicy.plan_space_heating(
            outdoor_temps_c=[s.outdoor_temp_c for s in slots],
            prices_eur=[s.price_all_in for s in slots],
            solar_kw=[s.solar_kw for s in slots],
            active_dhw_slots=sorted(final_dhw_set | autonomous_dhw_slots),
            dynamic_peaks=dynamic_peaks,
            current_room_temp_c=frame.current_room_temp,
            current_floor_temp_c=frame.current_floor_temp,
            target_room_temp_c=frame.target_room_temp,
            wind_speeds_ms=frame.wind_speeds,
            is_heating_enabled=frame.is_space_heating_enabled,
            step_hours=step_hours,
            slot_lockout_map=slot_lockout_map,
            slot_datetimes=[s.dt for s in slots],
            solar_radiation_w_m2=[s.solar_rad_w_m2 for s in slots],
            thermostat_setpoint_c=frame.thermostat_setpoint,
            is_buffering=frame.is_buffering,
            unallocated_kw=[s.unallocated_kw for s in slots],
            tariff_provider=tp,
        )

        # 5. Assemble Canonical Dispatch Slots (with strict 6-state taxonomy)
        dispatch_slots: List[DispatchPlanSlot] = []
        traj = res_opt.trajectory.get("temperatures_c", []) if res_opt else []

        for i, s in enumerate(slots):
            p_val = s.price_all_in
            sol_val = s.solar_kw
            unalloc_val = s.unallocated_kw
            peak_info = slot_lockout_map.get(i)
            is_hard = i in hard_slots

            h_slot = heating_plan.slots[i] if i < len(heating_plan.slots) else None
            heating_kw = h_slot.heating_kw_el if h_slot else 0.0

            is_forced_dhw = i in final_dhw_set
            is_autonomous_dhw = (not is_forced_dhw) and (i in autonomous_dhw_slots) and not is_hard
            if dhw_kw_by_slot is not None:
                dhw_kw = dhw_kw_by_slot[i] if (is_forced_dhw or is_autonomous_dhw) and i < len(dhw_kw_by_slot) else 0.0
            elif (is_forced_dhw or is_autonomous_dhw) and current_dhw_temp is not None:
                t_k = traj[i] if i < len(traj) else current_dhw_temp
                out_t_k = float(getattr(s, "outdoor_temp_c", getattr(s, "outdoor_temp", 10.0)))
                dhw_kw = spec.get_electric_power_kw(t_k, outdoor_temp_c=out_t_k, params=model_parameters)
            else:
                dhw_kw = 0.0

            if dhw_kw > 0.0:
                # Daikin physical constraint: CV pauses during active DHW run
                heating_kw = 0.0

            run_target = slot_run_target.get(i) if is_forced_dhw else None

            # State Taxonomy Assignment (6 states)
            if is_hard:
                peak_info = peak_info or {"name": "Spitsblokkade", "max_price": p_val}
                state = StandardizedState.FORCED_OFF
                mode_lbl = f"Geforceerd uit (blok) — {peak_info['name']}"
                desc = f"Geforceerd uit ({s.label}): Prijspiek max €{peak_info['max_price']:.3f}/kWh. Compressor SG4/CV vergrendeld tegen piektarieven."
                heating_kw = 0.0
                dhw_kw = 0.0
                run_target = None
            elif is_forced_dhw:
                tgt = run_target if run_target is not None else spec.target_setpoint_c
                if tgt >= BOOST_RUN_THRESHOLD_C:
                    state = StandardizedState.MAX_ON
                    mode_lbl = f"Maximaal aan (doorverwarmen tot {tgt:.1f}°C)"
                    desc = f"Maximaal aan ({s.label}): Buffer doorverwarmen naar {tgt:.1f}°C · Vermogen {dhw_kw:.2f} kW elektrisch."
                else:
                    state = StandardizedState.FORCED_ON
                    mode_lbl = f"Geforceerd aan (verwarmen tot {tgt:.1f}°C)"
                    desc = f"Geforceerd aan ({s.label}): Verwarmen naar {tgt:.1f}°C · Vermogen {dhw_kw:.2f} kW elektrisch."
            elif h_slot and h_slot.is_preheat_active and not (peak_info and not is_forced_dhw):
                state = StandardizedState.ADVISED_ON
                mode_lbl = "Geadviseerd aan (Vloerbuffer Pre-Heat)"
                desc = f"Geadviseerd aan ({s.label}): Voordelig daltarief (€{p_val:.3f}/kWh). Betondekvloer wordt preventief voorverwarmd ({heating_kw} kW) om spitsblokkades comfortabel te overbruggen."
            elif peak_info and not is_forced_dhw:
                state = StandardizedState.ADVISED_OFF
                mode_lbl = f"Geadviseerd uit — {peak_info['name']}"
                desc = f"Geadviseerd uit ({s.label}): Verhoogd tarief (€{p_val:.3f}/kWh). Warmtepomp draait autonoom zonder verhoogd setpoint."
            elif is_autonomous_dhw:
                state = StandardizedState.NORMAL
                mode_lbl = "Normaal (Daikin verwarmt tapwater autonoom)"
                desc = f"Normaal ({s.label}): Verwachte autonome tapwaterrun van de Daikin · {dhw_kw:.2f} kW (geen ingreep van Open HEMS)."
            else:
                state = StandardizedState.NORMAL
                mode_lbl = "Normaal (Standby)"
                desc = f"Normaal ({s.label}): Vrijloopvenster (€{p_val:.3f}/kWh). Warmtepomp en boiler in normale werking."

            meta = get_state_metadata(state)
            net_import = round((unalloc_val + heating_kw + dhw_kw) - sol_val, 3)
            p_quality = getattr(s, "price_quality", Quality.GOOD)

            dispatch_slots.append(
                DispatchPlanSlot(
                    slot_idx=i,
                    time_label=s.label,
                    dt_iso=s.dt.isoformat(),
                    price_eur=s.price_all_in,
                    solar_kw=sol_val,
                    unallocated_kw=unalloc_val,
                    heating_kw=round(heating_kw, 2),
                    dhw_kw=round(dhw_kw, 2),
                    net_import_kw=net_import,
                    mode_code=state,
                    mode_label=mode_lbl,
                    color_hex=meta["color_hex"],
                    tailwind_class=meta["tailwind_text"],
                    description=desc,
                    target_temp_c=run_target,
                    price_quality=str(getattr(p_quality, "value", p_quality))
                )
            )

        # 6. Priority 3: Home battery on the residual load (only real battery affects net import)
        bat_ctx = battery_context if battery_context is not None else cls._battery_context_from_config(cfg)
        battery_summary = None
        try:
            battery_summary = cls._plan_battery(cfg, dispatch_slots, hard_slots, tp, bat_ctx, step_hours)
        except Exception as e_bat:
            validation_issues.append(f"Batterijplanning mislukt: {e_bat}")

        plan = CanonicalDispatchPlan(
            generated_at=now.isoformat(),
            horizon_hours=(n_slots * step_mins) / 60.0,
            resolution_mins=step_mins,
            is_fresh=frame.is_fresh,
            freshness_age_seconds=frame.freshness_age_seconds,
            slots=dispatch_slots,
            dhw_summary=dhw_summary,
            dynamic_peaks=dynamic_peaks,
            heating_summary=heating_plan,
            validation_issues=validation_issues,
            battery_summary=battery_summary,
            metadata={
                "aligned_grid_start": frame.metadata.get("aligned_grid_start"),
                "dhw_tank_liters": cls.DHW_TANK_LITERS,
                "daytime_arbitrage_audit": daytime_arbitrage_audit,
                "dhw_baseline_adopted": baseline_adopted,
                "dhw_engine": dhw_engine,
                "dhw_planned_mode": planned_mode,
                "hard_lockout_slot_count": len(hard_slots),
                "forecast_price_slot_count": sum(1 for s in dispatch_slots if s.price_quality != "good"),
                "solar_surplus_day_kwh": round(sum(max(0.0, s.solar_kw - s.unallocated_kw) * step_hours for s in slots), 2),
                "is_heating_season": heating_plan.is_heating_season,
                "season_status_label": heating_plan.season_status_label,
                "total_heating_kwh_el": heating_plan.total_heating_kwh_el,
                "total_heating_kwh_th": heating_plan.total_heating_kwh_th,
                "heating_average_cop": heating_plan.average_cop,
                "preheat_hours": heating_plan.preheat_hours,
                "lockout_hours": heating_plan.lockout_hours,
                "min_projected_room_temp_c": heating_plan.min_projected_room_temp_c,
                "max_projected_room_temp_c": heating_plan.max_projected_room_temp_c
            }
        )

        # Publish to the injected or default singleton store
        target_store.publish_plan(plan)

        return plan
