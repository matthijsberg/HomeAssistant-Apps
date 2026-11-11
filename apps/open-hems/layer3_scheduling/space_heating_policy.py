"""
Layer 3: Space Heating & Floor Thermal Buffer Policy
===================================================
Predicts what the Daikin does with the house over the planning horizon, and decides when Open HEMS
pre-heats (room setpoint offset) ahead of hard peak lockouts.

Model (grey-box fit on winter 2025-26, knowledge/architecture/space-heating-model.md):
1. Building: 2-node network. Room node (the Madoka reading, incl. walls and furniture) and a light floor
   node, coupled by R_floor_room. 77 % of the heat-pump output enters the floor, the rest reaches the room
   directly (LT radiators). Losses UA*(T_room - T_out) with wind infiltration, internal gains and solar
   gain on global horizontal irradiance.
2. Daikin: closed-loop behaviour, not a schedule. The mean heat output per slot follows
   clip(K * (base + slope*T_out + gain*(setpoint - T_room) - T_floor), 0, Q_max): weather-compensated
   with strong room feedback. Compressor cycling below the minimum modulation averages out per slot.
3. COP: measured (P1P2 heat / Inepro electricity) per outdoor temperature, including defrost.
4. Levers: hard peak lockout (SG forced off) -> no heat. Pre-heat (advised_on) -> room setpoint +1 K for
   0-4 h before a hard lockout, chosen per lockout as the cheapest option that keeps the room within
   comfort; "no pre-heat" is always a candidate. Soft peak advice is SG2 normal for the Daikin.
5. Summer lockout, DHW hydraulic interlock (no CV heat during DHW runs).
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime
import json
import math
from pathlib import Path

from models.canonical import SpaceHeatingSlotResult, SpaceHeatingPlanSummary


class SpaceHeatingPolicy:
    # --- Building network (winter 2025-26 fit with UA fixed to the calibrated envelope value)
    UA_BUILDING_KW_PER_K = 0.3100          # fallback; the live value comes from heatpump_model_parameters.json
    C_ROOM_KWH_PER_K = 12.8                # room node: air, walls, furniture (Madoka reference)
    C_FLOOR_KWH_PER_K = 3.75               # screed node (time constant R*C ~3.2 h)
    R_FLOOR_ROOM_K_PER_KW = 0.85
    FLOOR_HEAT_SHARE = 0.77                # share of heat-pump output entering the floor
    INTERNAL_GAINS_KW = 0.68
    SOLAR_APERTURE_M2 = 6.8                # kW_th per kW/m2 of global horizontal irradiance
    PV_KW_PER_KW_M2_GHI = 4.5              # only to approximate GHI from PV kW when no irradiance is given
    WIND_INFILTRATION_COEFF_KW_PER_K_PER_MS = 0.015  # 15 W/K per m/s wind above 2 m/s
    C_WIND_W_PER_K_MS_BOUNDS = (1.0, 60.0)  # plausible band; values outside are treated as a unit error
    SUBSTEP_HOURS = 0.25 / 6               # integration and controller step (2.5 min)
    _warned_param_keys: set = set()

    # --- Daikin closed-loop behaviour (mean heat output per slot)
    DAIKIN_LWT_BASE_C = 28.66
    DAIKIN_LWT_OUTDOOR_SLOPE = -0.192
    DAIKIN_ROOM_GAIN_K_PER_K = 8.0
    DAIKIN_EMITTER_KW_PER_K = 1.57
    DAIKIN_MAX_HEAT_KW = 7.0            # low-and-slow settings (2026-11): sustained CV draw tops out ~1.6-2.0 kW_el
    # Measured seasonal COP per outdoor temperature (heat / electricity, defrost included)
    COP_CURVE = ((-2.0, 2.42), (2.0, 2.64), (6.0, 3.56), (10.0, 4.52), (14.0, 5.48))
    COP_BOUNDS = (1.8, 6.0)

    # --- Compressor electrical modulation & startup profile (re-fitted 2026-11-11 on 2026-11-05..11 low-and-slow runs:
    #     plateau 0.70-0.95 kW_el, surge 1.0-2.6 kW_el decaying with tau ~1.5 slots, sustained max ~1.6-2.0 kW_el)
    MOD_FLOOR_MIN_W = 650.0                # minimum steady compressor power floor (W)
    MOD_FLOOR_MAX_W = 2000.0               # upper bound on temperature-dependent floor (W)
    MOD_FLOOR_REF_10C_W = 700.0            # modulation floor at 10 C outdoor (W)
    MOD_FLOOR_SLOPE_W_PER_K = 30.0         # floor increase per K below 10 C (W/K)
    STARTUP_PEAK_MIN_W = 950.0             # minimum startup peak power in mild weather (W)
    STARTUP_PEAK_MAX_W = 2600.0            # maximum startup peak power in frost weather (W)
    STARTUP_PEAK_REF_10C_W = 1050.0        # startup peak at 10 C outdoor (W)
    STARTUP_PEAK_SLOPE_W_PER_K = 60.0      # startup peak increase per K below 10 C (W/K)
    STEADY_MAX_POWER_W = 1900.0            # maximum continuous CV electrical power (W)
    SLOT1_SURGE_WEIGHT = 0.10              # fraction of startup surge in slot 1 (0-15m); rest is floor
    SURGE_DECAY_SLOTS = 1.5                # exponential decay time constant (in 15m slots) after slot 2
    THERMO_OFF_CUTOFF_W = 350.0            # thermo-off electrical cutoff when room >= target - margin (W)
    THERMO_OFF_ROOM_MARGIN_C = 0.15        # room margin below target where thermo-off applies (K)

    # --- Comfort & levers
    TARGET_ROOM_TEMP_C = 20.0
    MIN_COMFORT_DELTA_C = 0.5      # max allowed drop below target during a lockout
    MAX_PREHEAT_OVERSHOOT_C = 1.2  # nominal rise above target from pre-heat without solar spike
    MAX_PREHEAT_DELTA_ABOVE_BASE_C = 3.0  # max setpoint/room offset when floor is still cool (<26.5C)
    MAX_PREHEAT_SAFETY_TEMP_C = 23.5      # absolute upper room pre-heat ceiling
    MAX_PREHEAT_FLOOR_TEMP_C = 26.5       # floor saturation threshold for pre-heating
    MAX_FLOOR_TEMP_C = 28.0        # upper hardware safety limit for underfloor heating
    SUMMER_LOCKOUT_OUTDOOR_C = 16.0
    PREHEAT_OFFSET_C = 1.0         # room setpoint offset applied by RoomThermostatBufferController
    PREHEAT_CANDIDATE_HOURS = (0.0, 1.0, 2.0, 3.0, 4.0)
    PREHEAT_LEAD_GAP_HOURS = (1.0, 2.0, 3.0, 4.0)
    PREHEAT_MIN_SAVING_EUR = 0.05  # pre-heat only when it beats "no pre-heat" by at least this much
    COMFORT_PENALTY_EUR_PER_KH = 8.0
    MAX_BRIDGE_COST_PREMIUM_RATIO = 1.25  # allow holding a run across a single block when thermal cost is <= 1.25x reference

    # Legacy Carnot parameters (only for calculate_carnot_cop, kept for callers that still use it)
    FLOW_TEMP_CV_C = 35.0
    CARNOT_EFFICIENCY = 0.42

    _HP_PARAM_SPECS = (
        ("mod_floor_min_w", "MOD_FLOOR_MIN_W", 400.0, 1500.0),
        ("mod_floor_max_w", "MOD_FLOOR_MAX_W", 1000.0, 3500.0),
        ("mod_floor_ref_10c_w", "MOD_FLOOR_REF_10C_W", 400.0, 1800.0),
        ("mod_floor_slope_w_per_k", "MOD_FLOOR_SLOPE_W_PER_K", 0.0, 150.0),
        ("startup_peak_min_w", "STARTUP_PEAK_MIN_W", 600.0, 2500.0),
        ("startup_peak_max_w", "STARTUP_PEAK_MAX_W", 1200.0, 4500.0),
        ("startup_peak_ref_10c_w", "STARTUP_PEAK_REF_10C_W", 600.0, 2500.0),
        ("startup_peak_slope_w_per_k", "STARTUP_PEAK_SLOPE_W_PER_K", 0.0, 200.0),
        ("steady_max_power_w", "STEADY_MAX_POWER_W", 1500.0, 5500.0),
        ("slot1_surge_weight", "SLOT1_SURGE_WEIGHT", 0.0, 1.0),
        ("surge_decay_slots", "SURGE_DECAY_SLOTS", 0.5, 10.0),
        ("thermo_off_cutoff_w", "THERMO_OFF_CUTOFF_W", 100.0, 800.0),
        ("thermo_off_room_margin_c", "THERMO_OFF_ROOM_MARGIN_C", 0.0, 0.5),
        ("emitter_kw_per_k", "DAIKIN_EMITTER_KW_PER_K", 0.5, 3.0),
        ("max_heat_kw", "DAIKIN_MAX_HEAT_KW", 3.0, 12.0),
        ("max_bridge_cost_premium_ratio", "MAX_BRIDGE_COST_PREMIUM_RATIO", 1.0, 2.0),
    )

    @classmethod
    def get_active_parameters(cls) -> Dict[str, Any]:
        """Live envelope and heat-pump modulation parameters from heatpump_model_parameters.json with fallback to class constants."""
        params_file = Path("/config/heatpump_model_parameters.json")
        ua = cls.UA_BUILDING_KW_PER_K
        c_wind = cls.WIND_INFILTRATION_COEFF_KW_PER_K_PER_MS
        hp_vals: Dict[str, float] = {k: float(getattr(cls, attr)) for k, attr, _, _ in cls._HP_PARAM_SPECS}
        if params_file.exists():
            try:
                p = json.loads(params_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                if "parse" not in cls._warned_param_keys:
                    cls._warned_param_keys.add("parse")
                    print(f"[WARN] SpaceHeatingPolicy: cannot read {params_file}: {e}; using defaults")
                p = {}
            b = p.get("building", {}) if isinstance(p, dict) else {}
            try:
                ua_w = b.get("ua_base_w_per_k")
                if ua_w is not None and float(ua_w) > 0:
                    ua = float(ua_w) / 1000.0  # W/K to kW/K
            except (TypeError, ValueError):
                pass
            c_wind_w = b.get("c_wind_w_per_k_ms")
            try:
                if c_wind_w is not None:
                    lo, hi = cls.C_WIND_W_PER_K_MS_BOUNDS
                    if lo <= float(c_wind_w) <= hi:
                        c_wind = float(c_wind_w) / 1000.0  # W/(K*m/s) to kW/(K*m/s)
                    elif "c_wind_w_per_k_ms" not in cls._warned_param_keys:
                        cls._warned_param_keys.add("c_wind_w_per_k_ms")
                        print(f"[WARN] SpaceHeatingPolicy: building.c_wind_w_per_k_ms={c_wind_w} outside "
                              f"[{lo}, {hi}] W/(K·m/s); using default {cls.WIND_INFILTRATION_COEFF_KW_PER_K_PER_MS * 1000:.0f}")
            except (TypeError, ValueError):
                pass
            hp = p.get("heat_pump", {}) if isinstance(p, dict) else {}
            if isinstance(hp, dict):
                for key, attr, lo_b, hi_b in cls._HP_PARAM_SPECS:
                    raw_v = hp.get(key)
                    if raw_v is not None:
                        try:
                            fv = float(raw_v)
                            if lo_b <= fv <= hi_b:
                                hp_vals[key] = fv
                        except (TypeError, ValueError):
                            pass
        res = {"ua_kw_per_k": ua, "c_wind_kw_per_k_ms": c_wind}
        res.update(hp_vals)
        return res

    # ------------------------------------------------------------------ physics
    @classmethod
    def calculate_cop(cls, outdoor_temp_c: float) -> float:
        """Measured heat-pump COP for space heating at this outdoor temperature (linear interpolation)."""
        pts = cls.COP_CURVE
        t = float(outdoor_temp_c)
        if t <= pts[0][0]:
            (t0, c0), (t1, c1) = pts[0], pts[1]
        elif t >= pts[-1][0]:
            (t0, c0), (t1, c1) = pts[-2], pts[-1]
        else:
            k = next(i for i in range(len(pts) - 1) if pts[i][0] <= t <= pts[i + 1][0])
            (t0, c0), (t1, c1) = pts[k], pts[k + 1]
        cop = c0 + (c1 - c0) * (t - t0) / (t1 - t0)
        lo, hi = cls.COP_BOUNDS
        return round(max(lo, min(hi, cop)), 2)

    @classmethod
    def calculate_run_power_kw(
        cls,
        outdoor_temp_c: float,
        slot_in_run: int = 1,
        q_drive_th_kw: float = 0.0,
        params: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculates electrical compressor power (kW_el) incorporating the physical
        modulation floor and startup envelope calibrated on 2026-11-05..11 low-and-slow telemetry.
        """
        act_p = params if params is not None else cls.get_active_parameters()
        floor_min_kw = act_p.get("mod_floor_min_w", cls.MOD_FLOOR_MIN_W) / 1000.0
        floor_max_kw = act_p.get("mod_floor_max_w", cls.MOD_FLOOR_MAX_W) / 1000.0
        floor_ref_kw = act_p.get("mod_floor_ref_10c_w", cls.MOD_FLOOR_REF_10C_W) / 1000.0
        floor_slope_kw = act_p.get("mod_floor_slope_w_per_k", cls.MOD_FLOOR_SLOPE_W_PER_K) / 1000.0

        peak_min_kw = act_p.get("startup_peak_min_w", cls.STARTUP_PEAK_MIN_W) / 1000.0
        peak_max_kw = act_p.get("startup_peak_max_w", cls.STARTUP_PEAK_MAX_W) / 1000.0
        peak_ref_kw = act_p.get("startup_peak_ref_10c_w", cls.STARTUP_PEAK_REF_10C_W) / 1000.0
        peak_slope_kw = act_p.get("startup_peak_slope_w_per_k", cls.STARTUP_PEAK_SLOPE_W_PER_K) / 1000.0

        steady_max_kw = act_p.get("steady_max_power_w", cls.STEADY_MAX_POWER_W) / 1000.0
        slot1_w = act_p.get("slot1_surge_weight", cls.SLOT1_SURGE_WEIGHT)
        decay_slots = max(0.5, act_p.get("surge_decay_slots", cls.SURGE_DECAY_SLOTS))

        p_floor = max(floor_min_kw, min(floor_max_kw, floor_ref_kw - floor_slope_kw * (outdoor_temp_c - 10.0)))
        p_peak = max(peak_min_kw, min(peak_max_kw, peak_ref_kw - peak_slope_kw * (outdoor_temp_c - 10.0)))
        cop = cls.calculate_cop(outdoor_temp_c)
        p_drive = q_drive_th_kw / max(1.0, cop) if q_drive_th_kw > 0 else p_floor
        p_steady = max(p_floor, min(steady_max_kw, p_drive))
        p_surge = max(p_peak, p_steady)

        if slot_in_run <= 1:
            return round((1.0 - slot1_w) * p_floor + slot1_w * p_surge, 2)
        elif slot_in_run == 2:
            return round(p_surge, 2)
        else:
            decay = math.exp(-(slot_in_run - 2) / decay_slots)
            p = p_steady + (p_surge - p_steady) * decay
            return round(p, 2)

    @classmethod
    def daikin_heat_output_kw(
        cls,
        outdoor_temp_c: float,
        setpoint_c: float,
        t_room: float,
        t_floor: float,
        heat_limits: Optional[Tuple[float, float]] = None,
    ) -> float:
        """
        Mean heat output the Daikin delivers to the CV circuit in this state (kW_th).
        heat_limits = (emitter_kw_per_k, max_heat_kw) from get_active_parameters(); class constants otherwise.
        """
        emitter_kw_per_k, max_heat_kw = heat_limits if heat_limits is not None else (
            cls.DAIKIN_EMITTER_KW_PER_K, cls.DAIKIN_MAX_HEAT_KW)
        drive = (cls.DAIKIN_LWT_BASE_C + cls.DAIKIN_LWT_OUTDOOR_SLOPE * outdoor_temp_c
                 + cls.DAIKIN_ROOM_GAIN_K_PER_K * (setpoint_c - t_room) - t_floor)
        return max(0.0, min(max_heat_kw, emitter_kw_per_k * drive))

    @classmethod
    def _advance_thermal_state(
        cls,
        t_room: float,
        t_floor: float,
        q_heat_th_kw: float,
        q_gain_room_kw: float,
        t_out: float,
        ua_kw_per_k: float,
        step_hours: float,
        floor_share: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Advances the floor/room network with a fixed heat input over step_hours; returns (t_room, t_floor).
        q_gain_room_kw are the gains entering the room node (internal + solar). The state is never rounded.
        """
        f = cls.FLOOR_HEAT_SHARE if floor_share is None else floor_share
        n_sub = max(1, math.ceil(step_hours / cls.SUBSTEP_HOURS - 1e-9))
        h = step_hours / n_sub
        for _ in range(n_sub):
            q_floor_to_room = (t_floor - t_room) / cls.R_FLOOR_ROOM_K_PER_KW
            q_loss = ua_kw_per_k * max(0.0, t_room - t_out)
            t_floor += (f * q_heat_th_kw - q_floor_to_room) / cls.C_FLOOR_KWH_PER_K * h
            t_room += (q_floor_to_room + (1.0 - f) * q_heat_th_kw + q_gain_room_kw - q_loss) / cls.C_ROOM_KWH_PER_K * h
        return t_room, t_floor

    @classmethod
    def _simulate_slot(
        cls,
        t_room: float,
        t_floor: float,
        heating_allowed: bool,
        setpoint_c: float,
        q_gain_room_kw: float,
        t_out: float,
        ua_kw_per_k: float,
        step_hours: float,
        heat_limits: Optional[Tuple[float, float]] = None,
    ) -> Tuple[float, float, float]:
        """One slot with the Daikin in the loop (re-evaluated every sub-step); returns (t_room, t_floor, mean Q_th)."""
        n_sub = max(1, math.ceil(step_hours / cls.SUBSTEP_HOURS - 1e-9))
        h = step_hours / n_sub
        q_sum = 0.0
        for _ in range(n_sub):
            q = cls.daikin_heat_output_kw(t_out, setpoint_c, t_room, t_floor, heat_limits) if heating_allowed else 0.0
            q_sum += q
            t_room, t_floor = cls._advance_thermal_state(t_room, t_floor, q, q_gain_room_kw, t_out, ua_kw_per_k, h)
        return t_room, t_floor, q_sum / n_sub

    @classmethod
    def calculate_carnot_cop(cls, outdoor_temp_c: float, flow_temp_c: float = 35.0) -> float:
        """Legacy Carnot-scaled COP (models.physics). The planner uses calculate_cop (measured)."""
        from models.physics import calculate_carnot_cop as _calc_cop
        return _calc_cop(outdoor_temp_c, flow_temp_c=flow_temp_c, carnot_efficiency=cls.CARNOT_EFFICIENCY)

    @classmethod
    def calculate_thermal_cost(
        cls,
        price_eur: float,
        cop: float,
        solar_kw: float = 0.0,
        unallocated_kw: float = 0.0,
        export_price_eur: Optional[float] = None,
        tariff_provider: Optional[Any] = None,
    ) -> float:
        """
        Calculates effective cost per thermal kWh (€/kWh_th = Price_eff / COP).
        1. Subtracts the dynamic household unallocated load (sluip-/overig verbruik) first:
           surplus_kw = max(0.0, solar_kw - unallocated_kw)
        2. Values the fraction of modulated heat pump demand (MOD_FLOOR_REF_10C_W) covered by
           net solar surplus at the dynamic EPEX export price via calculate_slot_financials.
        """
        from layer3_scheduling.dhw_financials import calculate_slot_financials
        p_ref_kw = max(0.50, cls.MOD_FLOOR_REF_10C_W / 1000.0)
        if export_price_eur is not None:
            surplus_kw = max(0.0, float(solar_kw) - max(0.0, float(unallocated_kw)))
            solar_share = min(1.0, surplus_kw / p_ref_kw)
            effective_price = solar_share * float(export_price_eur) + (1.0 - solar_share) * price_eur
        else:
            _, _, _, effective_price = calculate_slot_financials(
                solar_kw=max(0.0, float(solar_kw)),
                unalloc_kw=max(0.0, float(unallocated_kw)),
                el_demand_kw=p_ref_kw,
                price_all_in=price_eur,
                step_hours=0.25,
                tariff_provider=tariff_provider,
            )

        return round(effective_price / max(1.0, cop), 4)

    # ------------------------------------------------------------------ planning
    @classmethod
    def _rollout(
        cls,
        t_room0: float,
        t_floor0: float,
        allowed: List[bool],
        setpoints: List[float],
        gains: List[float],
        outdoor: List[float],
        ua: List[float],
        step_hours: float,
        soft: Optional[List[bool]] = None,
        dhw_slots: Optional[Set[int]] = None,
        thermal_costs: Optional[List[float]] = None,
        max_bridge_ratio: Optional[float] = None,
        heat_limits: Optional[Tuple[float, float]] = None,
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        Simulates the horizon; returns room and floor temperature at the START of every slot and mean Q_th.
        Enforces the Madoka -0.5 K autonomous start hysteresis: once the heat pump is off (above setpoint,
        after a pre-heat, or after a lockout), it only turns on autonomously when T_room drops to
        setpoint - MIN_COMFORT_DELTA_C (-0.5 K), or when Open HEMS actively commands a pre-heat (+1.0 K).
        Ongoing runs are allowed to modulate through advised_off, and across a post-preheat bridge block when
        the thermal cost is cheaper or within max_bridge_ratio (default 1.25 = +25% marginal cost).
        """
        rooms, floors, heats = [], [], []
        t_r, t_f = t_room0, t_floor0
        base_sp = min(setpoints) if setpoints else cls.TARGET_ROOM_TEMP_C
        start_thresh = round(base_sp - cls.MIN_COMFORT_DELTA_C, 2)
        is_running = (t_r <= base_sp + 0.15)
        active_preheat_sp = base_sp + cls.PREHEAT_OFFSET_C
        bridge_ratio = cls.MAX_BRIDGE_COST_PREMIUM_RATIO if max_bridge_ratio is None else max_bridge_ratio
        mean_tc = (sum(thermal_costs) / max(1, len(thermal_costs))) if thermal_costs else 0.0
        seen_hard_lockout = False
        for i in range(len(outdoor)):
            rooms.append(t_r)
            floors.append(t_f)
            sp = setpoints[i]
            is_pre = sp > base_sp + 0.1
            was_pre = (i > 0 and setpoints[i - 1] > base_sp + 0.1)
            if not allowed[i]:
                # 3-way valve pause for DHW preserves the Madoka room thermostat latch; hard lockout resets it
                if not (dhw_slots and i in dhw_slots):
                    is_running = False
                    seen_hard_lockout = True
            elif is_pre:
                safety_ceiling = min(
                    cls.MAX_PREHEAT_SAFETY_TEMP_C,
                    round(base_sp + cls.MAX_PREHEAT_DELTA_ABOVE_BASE_C, 1)
                )
                if not was_pre:
                    # Match Layer 4 RoomThermostatBufferController: elevate at least +1.0 K above current room temp,
                    # capped at baseline + 3.0 K (e.g. 23.5 C at 20.5 C base, 17.0 C at 14.0 C vacation).
                    active_preheat_sp = min(safety_ceiling, round(max(sp, t_r + cls.PREHEAT_OFFSET_C), 1))
                sp = active_preheat_sp
                is_running = (
                    (t_r < sp)
                    and (t_f < cls.MAX_PREHEAT_FLOOR_TEMP_C)
                    and (t_r + cls.PREHEAT_OFFSET_C <= safety_ceiling + 0.25)
                )
            else:
                if was_pre and t_r >= base_sp:
                    can_bridge_financially = (
                        thermal_costs is not None
                        and i < len(thermal_costs)
                        and thermal_costs[i] <= mean_tc * bridge_ratio
                        and t_f < cls.MAX_PREHEAT_FLOOR_TEMP_C - 0.5
                    )
                    if not can_bridge_financially:
                        is_running = False
                if not is_running:
                    # During advised_off (soft peak shoulder), avoid cold-starting a new run unless comfort is genuinely threatened
                    in_soft = bool(soft and i < len(soft) and soft[i])
                    eff_thresh = (start_thresh - 0.15) if in_soft else start_thresh
                    lookahead_h = (2.5 * step_hours) if (seen_hard_lockout and not in_soft) else step_hours
                    t_r_unh, _ = cls._advance_thermal_state(t_r, t_f, 0.0, gains[i], outdoor[i], ua[i], lookahead_h)
                    if t_r <= eff_thresh + 0.03 or t_r_unh <= eff_thresh + 0.03:
                        is_running = True
            t_r, t_f, q = cls._simulate_slot(
                t_r, t_f, (is_running and allowed[i]), sp, gains[i], outdoor[i], ua[i], step_hours, heat_limits
            )
            heats.append(q)
        return rooms, floors, heats

    @staticmethod
    def _hard_lockout_blocks(hard: List[bool]) -> List[Tuple[int, int]]:
        blocks, i = [], 0
        while i < len(hard):
            if hard[i]:
                j = i
                while j + 1 < len(hard) and hard[j + 1]:
                    j += 1
                blocks.append((i, j))
                i = j + 1
            else:
                i += 1
        return blocks

    @classmethod
    def plan_space_heating(
        cls,
        outdoor_temps_c: List[float],
        prices_eur: List[float],
        solar_kw: List[float],
        active_dhw_slots: List[int],
        dynamic_peaks: List[Dict[str, Any]],
        current_room_temp_c: Optional[float] = None,
        current_floor_temp_c: Optional[float] = None,
        target_room_temp_c: Optional[float] = None,
        wind_speeds_ms: Optional[List[float]] = None,
        is_heating_enabled: bool = True,
        step_hours: float = 0.25,
        slot_lockout_map: Optional[Dict[int, Dict[str, Any]]] = None,
        slot_datetimes: Optional[List[datetime]] = None,
        solar_radiation_w_m2: Optional[List[float]] = None,
        thermostat_setpoint_c: Optional[float] = None,
        is_buffering: bool = False,
        unallocated_kw: Optional[List[float]] = None,
        tariff_provider: Optional[Any] = None,
    ) -> SpaceHeatingPlanSummary:
        """
        Plans space heating over the horizon with the Daikin in the loop.

        slot_lockout_map: per-slot peak entries from detect_dynamic_price_peaks (is_hard_lockout is
          True only inside the ≤150 min crest). When omitted it is rebuilt from the peak objects.
        solar_radiation_w_m2: forecast global horizontal irradiance per slot; when omitted it is
          approximated from solar_kw.
        """
        n_slots = len(outdoor_temps_c)
        act_p = cls.get_active_parameters()
        mean_outdoor = sum(outdoor_temps_c) / n_slots if n_slots > 0 else 15.0

        target_room = round(target_room_temp_c, 1) if target_room_temp_c is not None else cls.TARGET_ROOM_TEMP_C
        min_comfort_room = round(target_room - cls.MIN_COMFORT_DELTA_C, 2)
        max_preheat_room = round(target_room + cls.MAX_PREHEAT_OVERSHOOT_C, 2)
        is_heating_season = (mean_outdoor < cls.SUMMER_LOCKOUT_OUTDOOR_C) and is_heating_enabled

        # 1. Per-slot peak lockouts (hard only inside the crest window)
        if slot_lockout_map is not None:
            lockout_slot_map = {k: v for k, v in slot_lockout_map.items() if 0 <= k < n_slots}
        else:
            lockout_slot_map = {}
            for peak in dynamic_peaks:
                s_idx = peak.get("start_idx", 0)
                e_idx = peak.get("end_idx", 0)
                hs_raw = peak.get("hard_start_idx")
                he_raw = peak.get("hard_end_idx")
                if hs_raw is None or he_raw is None:
                    hs_raw, he_raw = s_idx, e_idx  # legacy peak object: the whole cluster is hard
                hs, he = int(hs_raw), int(he_raw)
                for idx in range(s_idx, min(n_slots, e_idx + 1)):
                    entry = dict(peak)
                    entry["is_hard_lockout"] = bool(peak.get("is_hard_lockout")) and hs >= 0 and hs <= idx <= he
                    lockout_slot_map[idx] = entry
        hard = [bool(lockout_slot_map.get(i, {}).get("is_hard_lockout")) for i in range(n_slots)]
        soft = [(i in lockout_slot_map) and not hard[i] for i in range(n_slots)]
        dhw = set(active_dhw_slots)

        # 2. Exogenous inputs per slot
        ua_slots = []
        gains = []
        for i in range(n_slots):
            v_wind = wind_speeds_ms[i] if (wind_speeds_ms and i < len(wind_speeds_ms)) else 0.0
            ua_slots.append(act_p["ua_kw_per_k"] + act_p["c_wind_kw_per_k_ms"] * max(0.0, v_wind - 2.0))
            if solar_radiation_w_m2 is not None and i < len(solar_radiation_w_m2):
                ghi_kw_m2 = max(0.0, solar_radiation_w_m2[i]) / 1000.0
            else:
                ghi_kw_m2 = max(0.0, solar_kw[i]) / cls.PV_KW_PER_KW_M2_GHI
            gains.append(cls.INTERNAL_GAINS_KW + cls.SOLAR_APERTURE_M2 * ghi_kw_m2)
        cops = [cls.calculate_cop(t) for t in outdoor_temps_c]
        thermal_costs = [
            cls.calculate_thermal_cost(
                prices_eur[i],
                cops[i],
                solar_kw[i],
                unallocated_kw=(unallocated_kw[i] if (unallocated_kw and i < len(unallocated_kw)) else 0.0),
                tariff_provider=tariff_provider,
            )
            for i in range(n_slots)
        ]

        t_room0 = current_room_temp_c if current_room_temp_c is not None else target_room
        t_floor0 = current_floor_temp_c if current_floor_temp_c is not None else t_room0 + (1.5 if is_heating_season else -0.2)
        allowed = [is_heating_season and not hard[i] and i not in dhw for i in range(n_slots)]
        preheat = [False] * n_slots

        def setpoints_for(pre: List[bool]) -> List[float]:
            return [target_room + (cls.PREHEAT_OFFSET_C if pre[i] else 0.0) for i in range(n_slots)]

        mean_th_cost = sum(thermal_costs) / max(1, n_slots)
        max_bridge_ratio = act_p.get("max_bridge_cost_premium_ratio", cls.MAX_BRIDGE_COST_PREMIUM_RATIO)
        heat_limits = (
            float(act_p.get("emitter_kw_per_k", cls.DAIKIN_EMITTER_KW_PER_K)),
            float(act_p.get("max_heat_kw", cls.DAIKIN_MAX_HEAT_KW)),
        )

        def evaluate(pre: List[bool], block: Tuple[int, int]) -> Tuple[float, Tuple[List[float], List[float], List[float]]]:
            sim = cls._rollout(
                t_room0, t_floor0, allowed, setpoints_for(pre), gains, outdoor_temps_c, ua_slots, step_hours,
                soft=soft, dhw_slots=dhw, thermal_costs=thermal_costs, max_bridge_ratio=max_bridge_ratio,
                heat_limits=heat_limits,
            )
            rooms, floors, heats = sim
            if n_slots > 0:
                t_r_end, t_f_end = cls._advance_thermal_state(
                    rooms[-1], floors[-1], heats[-1], gains[-1], outdoor_temps_c[-1], ua_slots[-1], step_hours
                )
                e_end = cls.C_ROOM_KWH_PER_K * t_r_end + cls.C_FLOOR_KWH_PER_K * t_f_end
            else:
                e_end = 0.0
            cost = sum(thermal_costs[i] * heats[i] * step_hours for i in range(n_slots)) - mean_th_cost * e_end
            b0, b1 = block
            recovery_end = min(n_slots, b1 + int(round(6.0 / step_hours)))
            has_deficit = False
            for i in range(b0, recovery_end):
                deficit = min_comfort_room - rooms[i]
                if deficit > 0:
                    has_deficit = True
                    cost += cls.COMFORT_PENALTY_EUR_PER_KH * deficit * step_hours
            if has_deficit:
                cost += 0.50
            overheat_lookback = int(round(6.0 / step_hours))
            safety_room_cap = min(
                cls.MAX_PREHEAT_SAFETY_TEMP_C,
                round(target_room + cls.MAX_PREHEAT_DELTA_ABOVE_BASE_C, 2)
            )
            preheat_overheated = any(
                (rooms[i] > safety_room_cap + 0.05)
                or (rooms[i] > max_preheat_room + 0.05 and floors[i] >= cls.MAX_PREHEAT_FLOOR_TEMP_C - 1.5)
                for i in range(n_slots)
                if any(pre[max(0, i - overheat_lookback):i + 1])
            )
            if max(floors) > cls.MAX_FLOOR_TEMP_C or preheat_overheated:
                cost += 1e3
            return cost, sim

        # 3. Pre-heat decision per peak/evening block: cheapest of "none" and 1-4 h of setpoint offset
        #    (sliding up to 4 h ahead of the block or ahead of its soft shoulder to capture midday solar/COP).
        if is_heating_season and n_slots > 0:
            target_blocks = list(cls._hard_lockout_blocks(hard))
            for s0_blk, s1_blk in cls._hard_lockout_blocks(soft):
                if not any(not (s1_blk < hb0 - 1 or s0_blk > hb1 + 1) for hb0, hb1 in target_blocks):
                    target_blocks.append((s0_blk, s1_blk))
            if (not target_blocks
                    and slot_datetimes is None
                    and max(thermal_costs) - min(thermal_costs) >= 0.008):
                eve_start = int(16 / step_hours)
                eve_end = min(n_slots - 1, int(20 / step_hours))
                if eve_start < n_slots:
                    target_blocks.append((eve_start, eve_end))
            target_blocks.sort()

            for b0, b1 in target_blocks:
                s0 = b0
                while s0 > 0 and soft[s0 - 1]:
                    s0 -= 1
                best_pre = list(preheat)
                best_cost, (base_rooms, _, base_heats) = evaluate(preheat, (b0, b1))
                base_cost = best_cost
                # Skip pre-heating for this block if no heating occurs in the block + 8h recovery window and comfort already holds
                local_check_end = min(n_slots, b1 + int(round(8.0 / step_hours)))
                check_slice = base_rooms[b0:local_check_end]
                if sum(base_heats[s0:local_check_end]) <= 1e-6 and (not check_slice or min(check_slice) >= min_comfort_room):
                    continue
                # Pre-heat should end at or before s0 (avoiding the advised_off / soft shoulder),
                # so 'geadviseerd uit' does not collide with 'geadviseerd aan' unless strictly necessary for comfort.
                comfort_violated = (not check_slice or min(check_slice) < min_comfort_room)
                end_candidates = sorted({
                    e for e in (
                        [s0]
                        + [s0 - int(round(g / step_hours)) for g in cls.PREHEAT_LEAD_GAP_HOURS]
                        + ([b0] if (comfort_violated or s0 == b0) else [])
                    ) if 0 < e <= b0
                })
                for end_slot in end_candidates:
                    for hours in cls.PREHEAT_CANDIDATE_HOURS[1:]:
                        dur_slots = int(round(hours / step_hours))
                        cand = list(preheat)
                        collected = 0
                        idx = end_slot - 1
                        max_lookback = dur_slots + len(dhw)
                        while idx >= 0 and collected < dur_slots and (end_slot - idx) <= max_lookback:
                            if idx in dhw:
                                idx -= 1
                                continue
                            if not allowed[idx] or (soft[idx] and not (end_slot == b0 and s0 == 0)):
                                break
                            cand[idx] = True
                            collected += 1
                            idx -= 1
                        if cand == preheat:
                            continue
                        c, _ = evaluate(cand, (b0, b1))
                        if c < best_cost:
                            best_pre, best_cost = cand, c
                        # Financial bridge candidate: if cand ends before s0 and the intermediate block (end_slot..s0)
                        # has an average thermal cost <= max_bridge_ratio (e.g. 1.25x) of mean_th_cost, also evaluate
                        # holding the run continuously across that block to prevent pre-peak cooling.
                        if end_slot < s0 and (s0 - end_slot) <= int(round(3.0 / step_hours)):
                            bridge_slots = [k for k in range(end_slot, s0) if allowed[k] and not soft[k]]
                            if bridge_slots:
                                bridge_avg_cost = sum(thermal_costs[k] for k in bridge_slots) / len(bridge_slots)
                                if bridge_avg_cost <= mean_th_cost * max_bridge_ratio:
                                    cand_bridged = list(cand)
                                    for k in bridge_slots:
                                        cand_bridged[k] = True
                                    cb, _ = evaluate(cand_bridged, (b0, b1))
                                    if cb < best_cost:
                                        best_pre, best_cost = cand_bridged, cb
                if base_cost - best_cost >= cls.PREHEAT_MIN_SAVING_EUR:
                    preheat = best_pre

        rooms, floors, heats = cls._rollout(
            t_room0, t_floor0, allowed, setpoints_for(preheat), gains,
            outdoor_temps_c, ua_slots, step_hours,
            soft=soft, dhw_slots=dhw, thermal_costs=thermal_costs, max_bridge_ratio=max_bridge_ratio,
            heat_limits=heat_limits,
        )

        # 4. Slot results
        slot_results: List[SpaceHeatingSlotResult] = []
        total_kwh_el = 0.0
        total_kwh_th = 0.0
        preheat_slots_count = 0
        lockout_slots_count = 0
        run_slot_idx = 0
        thermo_off_kw = act_p.get("thermo_off_cutoff_w", cls.THERMO_OFF_CUTOFF_W) / 1000.0
        thermo_off_margin_c = act_p.get("thermo_off_room_margin_c", cls.THERMO_OFF_ROOM_MARGIN_C)
        for i in range(n_slots):
            q_th_raw = heats[i]
            cop = cops[i]
            p_raw = q_th_raw / cop if cop > 0 and q_th_raw > 0 else 0.0

            # Thermo-off cutoff: negligible drive below cutoff when room is comfortably at or above setpoint
            if p_raw < thermo_off_kw and rooms[i] >= target_room - thermo_off_margin_c and not preheat[i]:
                run_slot_idx = 0
                heating_el = 0.0
                q_th = 0.0
            elif p_raw > 0.0:
                run_slot_idx += 1
                heating_el = cls.calculate_run_power_kw(
                    outdoor_temps_c[i], slot_in_run=run_slot_idx, q_drive_th_kw=q_th_raw, params=act_p
                )
                q_th = heating_el * cop
            else:
                run_slot_idx = 0
                heating_el = 0.0
                q_th = 0.0

            if not is_heating_season:
                mode_code = "normal"
            elif i in dhw:
                mode_code = "forced_on"  # DHW has precedence; CV paused
            elif hard[i]:
                mode_code = "forced_off"
                lockout_slots_count += 1
            elif preheat[i]:
                mode_code = "advised_on"
                preheat_slots_count += 1
            elif soft[i]:
                mode_code = "advised_off"  # SG2 normal for the Daikin; shown as soft advice
                lockout_slots_count += 1
            else:
                mode_code = "normal"
            q_loss = ua_slots[i] * max(0.0, rooms[i] - outdoor_temps_c[i])
            total_kwh_el += heating_el * step_hours
            total_kwh_th += q_th * step_hours
            slot_results.append(
                SpaceHeatingSlotResult(
                    slot_idx=i,
                    heating_kw_el=round(heating_el, 2),
                    heating_kw_th=round(q_th, 2),
                    cop=cops[i],
                    room_temp_c=round(rooms[i], 2),
                    floor_temp_c=round(floors[i], 2),
                    heat_loss_kw=round(max(0.0, q_loss - gains[i]), 2),
                    mode_code=mode_code,
                    is_preheat_active=preheat[i] and is_heating_season,
                    is_lockout_active=is_heating_season and (hard[i] or soft[i]),
                    cost_th_eur_per_kwh=thermal_costs[i],
                    outdoor_temp_c=round(outdoor_temps_c[i], 2)
                )
            )

        # 5. Counterfactual without heating from the first heated slot onwards,
        #    plus a second counterfactual branching off at the start of the second heating run (if any).
        first_heat_idx = next((i for i, s in enumerate(slot_results) if s.heating_kw_el > 0.05), None)
        unheated_second_run_temps: List[Optional[float]] = [None] * n_slots
        if first_heat_idx is None:
            unheated_room_temps = [s.room_temp_c for s in slot_results]
        else:
            no_heat = [False] * n_slots
            u_rooms, _, _ = cls._rollout(rooms[first_heat_idx], floors[first_heat_idx], no_heat,
                                         setpoints_for([False] * n_slots), gains[first_heat_idx:] + [0.0] * first_heat_idx,
                                         outdoor_temps_c[first_heat_idx:] + [0.0] * first_heat_idx,
                                         ua_slots[first_heat_idx:] + [0.0] * first_heat_idx, step_hours)
            unheated_room_temps = ([s.room_temp_c for s in slot_results[:first_heat_idx]]
                                   + [round(t, 2) for t in u_rooms[:n_slots - first_heat_idx]])

            first_gap_idx = next(
                (i for i in range(first_heat_idx + 1, n_slots) if slot_results[i].heating_kw_el <= 0.05),
                None
            )
            if first_gap_idx is not None:
                second_heat_idx = next(
                    (i for i in range(first_gap_idx + 1, n_slots) if slot_results[i].heating_kw_el > 0.05),
                    None
                )
                if second_heat_idx is not None:
                    u2_rooms, _, _ = cls._rollout(
                        rooms[second_heat_idx], floors[second_heat_idx], no_heat,
                        setpoints_for([False] * n_slots),
                        gains[second_heat_idx:] + [0.0] * second_heat_idx,
                        outdoor_temps_c[second_heat_idx:] + [0.0] * second_heat_idx,
                        ua_slots[second_heat_idx:] + [0.0] * second_heat_idx,
                        step_hours
                    )
                    anchor_idx = max(0, second_heat_idx - 1)
                    unheated_second_run_temps = (
                        [None] * anchor_idx
                        + [slot_results[i].room_temp_c for i in range(anchor_idx, second_heat_idx)]
                        + [round(t, 2) for t in u2_rooms[:n_slots - second_heat_idx]]
                    )

        # Prediction uncertainty band (P05/P95)
        room_p05, room_p95, unh_p05, unh_p95 = [], [], [], []
        for i, s in enumerate(slot_results):
            spread = 0.40 * (i / max(1, n_slots - 1)) ** 0.65
            room_p05.append(round(s.room_temp_c - spread, 2))
            room_p95.append(round(s.room_temp_c + spread, 2))
            unh_p05.append(round(unheated_room_temps[i] - spread, 2))
            unh_p95.append(round(unheated_room_temps[i] + spread, 2))

        all_r_temps = [s.room_temp_c for s in slot_results]
        if not is_heating_enabled:
            season_label = "Verwarming Uitgeschakeld (Thermostaat Uit)"
        elif not is_heating_season:
            season_label = "Zomersluiting (CV Vergrendeld)"
        else:
            season_label = "Stookseizoen Actief (Slimme Vloerbuffer)"
        return SpaceHeatingPlanSummary(
            is_heating_season=is_heating_season,
            season_status_label=season_label,
            total_heating_kwh_el=round(total_kwh_el, 2),
            total_heating_kwh_th=round(total_kwh_th, 2),
            average_cop=round(total_kwh_th / total_kwh_el, 2) if total_kwh_el > 0 else (round(sum(cops) / len(cops), 2) if cops else 3.5),
            preheat_hours=round(preheat_slots_count * step_hours, 1),
            lockout_hours=round(lockout_slots_count * step_hours, 1),
            min_projected_room_temp_c=min(all_r_temps) if all_r_temps else target_room,
            max_projected_room_temp_c=max(all_r_temps) if all_r_temps else target_room,
            slots=slot_results,
            target_room_temp_c=target_room,
            min_comfort_room_c=min_comfort_room,
            max_preheat_room_c=max_preheat_room,
            max_floor_temp_c=cls.MAX_FLOOR_TEMP_C,
            thermostat_setpoint_c=round(thermostat_setpoint_c, 1) if thermostat_setpoint_c is not None else target_room,
            baseline_comfort_temp_c=target_room,
            is_buffering=is_buffering,
            unheated_room_temps_c=unheated_room_temps,
            unheated_second_run_temps_c=unheated_second_run_temps,
            room_temps_p05_c=room_p05,
            room_temps_p95_c=room_p95,
            unheated_temps_p05_c=unh_p05,
            unheated_temps_p95_c=unh_p95
        )
