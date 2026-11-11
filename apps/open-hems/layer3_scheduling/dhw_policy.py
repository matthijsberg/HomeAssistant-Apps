"""
Open HEMS — Daikin-first DHW Policy (ADR-006)
=============================================
Layer 3 Scheduling: pure, rule-based domestic hot water (DHW) policy.

The Daikin regulates the tank by itself (SG2: starts at setpoint - 10 K, stops at the setpoint).
Open HEMS only intervenes when it has to, with exactly two targets (50 °C and 60 °C):

  1. Peak lockout        hard lockout quarter                               -> forced_off (SG1)
  2. Finish running run  a run started by Open HEMS is below its target      -> keep heating
  3. Pre-heat (comfort)  forecast < 40 °C + margin inside a hard lockout     -> 50 °C at the cheapest start
                                                                               within the window before the peak
  4. Free electricity    effective price <= threshold                       -> 60 °C
  5. Boost               heat to 60 °C now clearly cheaper than at X        -> 60 °C
  6. Advance             heat to 50 °C now >= advance_margin cheaper than X  -> 50 °C
  7. Otherwise           the Daikin decides                                  -> normal (SG2)

Heat price = effective electricity price / COP(tank temperature, outdoor temperature of that quarter),
with the tank at 45 °C for a run to 50 °C and 55 °C for a run to 60 °C. X is the first quarter in which
the Daikin would start by itself according to the autonomous forecast. Rules 5 and 6 only fire when the
current quarter is among the cheapest quarters before X.

The published plan is the rollout of the same rules over the horizon with the P50 tap profile, so plan
and execution cannot drift apart. Evidence and numbers: docs/adr/ADR-006-daikin-first-dhw-policy.md and
scripts/backtest_dhw_policies.py. No I/O, no Home Assistant entities, no actuation.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from models.physics import dhw_cop, dhw_electric_power_kw, dhw_step
from layer3_scheduling.dhw_financials import calculate_slot_financials
from layer3_scheduling.dhw_specs import DhwTankSpec
from layer3_scheduling.tariff_provider import TariffProvider

AMS_TZ = ZoneInfo("Europe/Amsterdam")
DT_H = 0.25
T_AMB_C = 18.0
NORMAL_RUN_COP_TANK_C = 45.0     # mean tank temperature of a run to 50 °C
BOOST_RUN_COP_TANK_C = 55.0      # mean tank temperature of a run to 60 °C

MODE_NORMAL = "normal"
MODE_FORCED_ON = "forced_on"     # SG4 with a software stop at 50 °C
MODE_MAX_ON = "max_on"           # SG4 up to the Daikin maximum (60 °C)
MODE_FORCED_OFF = "forced_off"   # SG1 peak lockout

# Run kinds
PREHEAT, ADVANCE, BOOST, BOOST_FREE, IN_FLIGHT = "preheat", "advance", "boost", "boost_free", "in_flight"


def _clamp(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v):
        return default
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class DhwPolicyParams:
    """All tunables of the Daikin-first policy (ADR-006 §7). Zero magic numbers in the rules."""
    preheat_margin_c: float = 1.0               # forecast below 40 + margin inside a hard lockout triggers a pre-heat
    preheat_window_hours: float = 4.0           # the pre-heat start is chosen within this window before the peak
    boost_max_start_temp_c: float = 57.0        # no boost on a (nearly) full tank
    boost_standby_factor: float = 0.05          # extra standby loss of a 60 °C tank, as a fraction of the heat price
    boost_margin_eur_per_kwh_th: float = 0.005  # minimum advantage per kWh heat (prevents flutter)
    advance_margin: Optional[float] = 0.10      # advance to 50 °C when heat is this fraction cheaper (None: off)
    advance_max_start_temp_c: float = 47.0      # only advance when at least ~3 K can be added
    free_price_eur_per_kwh: Optional[float] = 0.0  # effective price at/below which heating to 60 °C is free (None: off)
    sg4_release_hysteresis_c: float = 0.2       # a run is finished at target - hysteresis

    @property
    def preheat_window_slots(self) -> int:
        return max(1, int(round(self.preheat_window_hours * 4)))

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None) -> "DhwPolicyParams":
        """Reads cfg['dhw_policy'] with the bounds of SETTINGS_SPEC; invalid values fall back to the defaults."""
        values = effective_settings(cfg)
        return cls(**{k: values[k] for k in POLICY_PARAM_KEYS})


# ---------------------------------------------------------------------------------------------
# Settings: one table for config reading, API validation (/api/settings) and the Layer 4 supervisor
# ---------------------------------------------------------------------------------------------

# key: (default, lower bound, upper bound, nullable)
SETTINGS_SPEC: Dict[str, Tuple[Optional[float], float, float, bool]] = {
    "preheat_margin_c": (1.0, 0.0, 5.0, False),
    "preheat_window_hours": (4.0, 0.5, 12.0, False),
    "boost_max_start_temp_c": (57.0, 45.0, 59.0, False),
    "boost_standby_factor": (0.05, 0.0, 0.5, False),
    "boost_margin_eur_per_kwh_th": (0.005, 0.0, 0.10, False),
    "advance_margin": (0.10, 0.0, 1.0, True),
    "advance_max_start_temp_c": (47.0, 40.0, 49.0, False),
    "free_price_eur_per_kwh": (0.0, -1.0, 0.10, True),
    "sg4_release_hysteresis_c": (0.2, 0.0, 1.0, False),
    "sg4_no_effect_timeout_min": (10.0, 3.0, 60.0, False),   # Layer 4 supervisor
    "sg4_no_effect_cooldown_min": (60.0, 0.0, 240.0, False),  # Layer 4 supervisor
}
POLICY_PARAM_KEYS = (
    "preheat_margin_c", "preheat_window_hours", "boost_max_start_temp_c", "boost_standby_factor",
    "boost_margin_eur_per_kwh_th", "advance_margin", "advance_max_start_temp_c", "free_price_eur_per_kwh",
    "sg4_release_hysteresis_c",
)
DHW_ENGINES = ("daikin_first", "dp")


def effective_settings(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All dhw_policy settings with defaults applied and out-of-range values clamped (lenient: config reading)."""
    c = (cfg or {}).get("dhw_policy", {}) or {}
    out: Dict[str, Any] = {}
    for key, (default, lo, hi, nullable) in SETTINGS_SPEC.items():
        if key in c and c[key] is None and nullable:
            out[key] = None
        else:
            out[key] = _clamp(c.get(key), float(default) if default is not None else 0.0, lo, hi)
    engine = str(c.get("engine", "daikin_first"))
    out["engine"] = engine if engine in DHW_ENGINES else "daikin_first"
    return out


def validate_settings_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """Strict validation of a dhw_policy update from the API. Raises ValueError with a Dutch message."""
    if not isinstance(update, dict):
        raise ValueError("dhw_policy moet een object zijn")
    clean: Dict[str, Any] = {}
    for key, value in update.items():
        if key == "engine":
            if value not in DHW_ENGINES:
                raise ValueError(f"engine moet een van {', '.join(DHW_ENGINES)} zijn")
            clean[key] = value
            continue
        if key not in SETTINGS_SPEC:
            raise ValueError(f"Onbekende instelling dhw_policy.{key}")
        _, lo, hi, nullable = SETTINGS_SPEC[key]
        if value is None:
            if not nullable:
                raise ValueError(f"dhw_policy.{key} mag niet leeg zijn")
            clean[key] = None
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"dhw_policy.{key} moet een getal zijn")
        if math.isnan(v) or not (lo <= v <= hi):
            raise ValueError(f"dhw_policy.{key} moet tussen {lo:g} en {hi:g} liggen")
        clean[key] = round(v, 4)
    return clean


@dataclass
class PolicyInputs:
    """Per-horizon inputs, precomputed once per plan run (or once per backtest period)."""
    dts: List[datetime]
    labels: List[str]
    outdoor_temp_c: List[float]
    tap_p50_kwh: List[float]
    p_eff: List[float]           # effective EUR/kWh_el of a nominal DHW run (solar surplus at export value)
    hard: Set[int]
    spec: DhwTankSpec
    model_parameters: Dict[str, Any]
    ua_w_per_k: float
    tariff_provider: TariffProvider
    price_all_in: List[float] = field(default_factory=list)
    solar_kw: List[float] = field(default_factory=list)
    unallocated_kw: List[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.dts)

    @property
    def c_tank(self) -> float:
        return self.spec.thermal_capacity_kwh_per_k

    @classmethod
    def from_slots(
        cls,
        slots: List[Any],
        hard_slots: Set[int],
        spec: DhwTankSpec,
        dhw_model: Any,
        tariff_provider: TariffProvider,
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> "PolicyInputs":
        mp = model_parameters or {}
        dts, labels, touts, taps, peffs, prices, solars, unallocs = [], [], [], [], [], [], [], []
        for k, s in enumerate(slots):
            dt = getattr(s, "dt")
            local = dt.astimezone(AMS_TZ) if dt.tzinfo else dt
            t_out = float(getattr(s, "outdoor_temp_c", getattr(s, "outdoor_temp", 10.0)))
            price = float(getattr(s, "price_all_in", 0.25))
            solar = float(getattr(s, "solar_kw", 0.0))
            unalloc = float(getattr(s, "unallocated_kw", 0.30))
            kw = dhw_electric_power_kw(50.0, t_out, params=mp)
            dts.append(dt)
            labels.append(str(getattr(s, "label", local.strftime("%H:%M"))))
            touts.append(t_out)
            taps.append(float(dhw_model.get_learned_tap_kwh_th(local.weekday(), local.hour * 4 + local.minute // 15)))
            peffs.append(calculate_slot_financials(solar, unalloc, kw, price, DT_H, tariff_provider)[3])
            prices.append(price)
            solars.append(solar)
            unallocs.append(unalloc)
        return cls(dts=dts, labels=labels, outdoor_temp_c=touts, tap_p50_kwh=taps, p_eff=peffs, hard=set(hard_slots),
                   spec=spec, model_parameters=mp, ua_w_per_k=float(dhw_model.get_tank_ua()), tariff_provider=tariff_provider,
                   price_all_in=prices, solar_kw=solars, unallocated_kw=unallocs)


def tank_step(inp: PolicyInputs, t_c: float, heat_on: bool, stop_c: float, j: int, tap_kwh: float) -> Tuple[float, float, bool]:
    """One quarter of the canonical tank balance (models.physics.dhw_step) plus the electric energy used.
    Returns (next temperature, kWh_el, stop temperature reached within this quarter)."""
    t_out = inp.outdoor_temp_c[j]
    p_el = dhw_electric_power_kw(t_c, t_out, params=inp.model_parameters)
    raw = p_el * dhw_cop(t_c, t_out, params=inp.model_parameters) * DT_H
    q = min(raw, max(0.0, (stop_c - t_c) * inp.c_tank)) if (heat_on and t_c < stop_c) else 0.0
    kwh_el = (q / raw) * p_el * DT_H if raw > 0 else 0.0
    t_next = dhw_step(t_c, 1.0 if q > 0 else 0.0, tap_kwh, t_out, DT_H,
                      spec={"thermal_capacity_kwh_per_k": inp.c_tank, "ua_w_per_k": inp.ua_w_per_k, "heat_pump_power_kw": p_el},
                      params=inp.model_parameters, t_max_c=stop_c if q > 0 else max(stop_c, t_c), t_amb_c=T_AMB_C)
    return t_next, kwh_el, heat_on and q < raw - 1e-9


class DaikinTank:
    """The Daikin as seen by the policy: thermostat demand latch under SG2, SG1 blocks, SG4 forces heating."""

    def __init__(self, inp: PolicyInputs, t0_c: float, latch: bool = False, tap_factor: float = 1.0):
        self.inp = inp
        self.t_c = float(t0_c)
        self.latch = bool(latch)
        self.tap_factor = tap_factor

    def step(self, j: int, mode: str, stop_c: Optional[float]) -> Tuple[float, bool]:
        """Advances one quarter; returns (kWh_el, heating)."""
        spec = self.inp.spec
        if self.t_c <= spec.target_setpoint_c - spec.auto_start_delta_c + 1e-6:
            self.latch = True
        if mode == MODE_FORCED_OFF:
            heat_on, stop = False, spec.target_setpoint_c
        elif mode in (MODE_FORCED_ON, MODE_MAX_ON):
            heat_on, stop = True, min(spec.boost_setpoint_c, stop_c if stop_c is not None else spec.boost_setpoint_c)
        else:
            heat_on, stop = self.latch, spec.target_setpoint_c
        t_next, kwh_el, reached = tank_step(self.inp, self.t_c, heat_on, stop, j, self.inp.tap_p50_kwh[j] * self.tap_factor)
        if heat_on and ((reached and stop >= spec.target_setpoint_c) or t_next >= spec.target_setpoint_c):
            self.latch = False
        self.t_c = t_next
        return kwh_el, kwh_el > 1e-6


def forecast_autonomous(inp: PolicyInputs, k: int, t_c: float, latch: bool, horizon: int) -> Tuple[List[float], List[bool]]:
    """'Daikin autonomous' from quarter k: P50 tap profile, SG1 in hard lockouts. Returns (temperatures, heating)."""
    spec = inp.spec
    start_c = spec.target_setpoint_c - spec.auto_start_delta_c
    temps, heat = [t_c], []
    on = latch
    for j in range(k, min(k + horizon, inp.n)):
        if t_c <= start_c + 1e-6:
            on = True
        h = on and j not in inp.hard
        t_c, _, reached = tank_step(inp, t_c, h, spec.target_setpoint_c, j, inp.tap_p50_kwh[j])
        if h and reached:
            on = False
        heat.append(h)
        temps.append(t_c)
    return temps, heat


def slots_to_heat(inp: PolicyInputs, t_from: float, t_to: float, j: int) -> int:
    t_out = inp.outdoor_temp_c[j]
    rate = dhw_electric_power_kw(t_from, t_out, params=inp.model_parameters) * dhw_cop(t_from, t_out, params=inp.model_parameters) * DT_H
    return max(1, math.ceil(max(0.0, t_to - t_from) * inp.c_tank / max(rate, 0.1)))


@dataclass
class DhwDecision:
    mode: str                     # normal | forced_on | max_on | forced_off
    target_temp_c: Optional[float]
    rule: str                     # peak_lockout | continue | preheat | free | boost | advance | daikin
    reason: str


class DhwPolicy:
    """Stateful rule evaluator (the only state is the run Open HEMS started). One instance per rollout."""

    def __init__(self, inp: PolicyInputs, params: Optional[DhwPolicyParams] = None, horizon: Optional[int] = None):
        self.inp = inp
        self.p = params or DhwPolicyParams()
        self.horizon = horizon or inp.n
        self.commit: Optional[Tuple[str, float, float]] = None   # (kind, target °C, reference heat price)
        self.events: Dict[str, int] = {PREHEAT: 0, ADVANCE: 0, BOOST: 0, BOOST_FREE: 0}

    # -- heat prices ---------------------------------------------------------------------------
    def heat_price(self, j: int, t_to: float) -> float:
        """EUR per kWh heat of a run to t_to in quarter j."""
        t_tank = BOOST_RUN_COP_TANK_C if t_to > self.inp.spec.target_setpoint_c else NORMAL_RUN_COP_TANK_C
        return self.inp.p_eff[j] / dhw_cop(t_tank, self.inp.outdoor_temp_c[j], params=self.inp.model_parameters)

    def _is_free(self, j: int) -> bool:
        return self.p.free_price_eur_per_kwh is not None and self.inp.p_eff[j] <= self.p.free_price_eur_per_kwh

    def _beats(self, c_now: float, ref: float) -> bool:
        return c_now * (1.0 + self.p.boost_standby_factor) + self.p.boost_margin_eur_per_kwh_th < ref

    def _cheapest(self, k: int, until: int, n: int, t_to: float) -> bool:
        ranked = sorted(range(k, until), key=lambda j: self.heat_price(j, t_to))
        return k in set(ranked[:n])

    def _start(self, kind: str, target_c: float, ref: float, rule: str, reason: str) -> DhwDecision:
        self.commit = (kind, target_c, ref)
        if kind in self.events:
            self.events[kind] += 1
        return DhwDecision(MODE_MAX_ON if target_c > self.inp.spec.target_setpoint_c else MODE_FORCED_ON, target_c, rule, reason)

    def start_in_flight(self, target_c: float) -> None:
        """Seeds the rollout with the run Layer 4 is executing (read-only view of the in-flight commitment)."""
        target = self.inp.spec.boost_setpoint_c if target_c > self.inp.spec.target_setpoint_c else self.inp.spec.target_setpoint_c
        self.commit = (IN_FLIGHT, target, math.inf)

    def _post_50_boost_ref(self, k: int, t_c: float, end: int) -> Optional[float]:
        """Reference heat price of the next required Daikin/preheat run AFTER reaching 50 °C from (k, t_c),
        only if the current slot is also among the cheapest slots before that run (no cheaper midday/solar window)."""
        inp, p, spec = self.inp, self.p, self.inp.spec
        t50, t60 = spec.target_setpoint_c, spec.boost_setpoint_c
        k50 = min(end, k + (slots_to_heat(inp, t_c, t50, k) if t_c < t50 else 0))
        if k50 >= end:
            return None
        temps50, heat50 = forecast_autonomous(inp, k50, max(t_c, t50), False, end - k50)
        x50 = next((j for j in range(k50, end) if heat50[j - k50]), None)
        comfort_c = max(spec.comfort_min_temp_c, t50 - spec.auto_start_delta_c + p.preheat_margin_c)
        dip50 = next((j for j in range(k50, end) if j in inp.hard and temps50[j - k50] < comfort_c), None)

        ref_candidates: List[Tuple[int, float]] = []
        if x50 is not None and x50 > k:
            t_x = min(t50 - spec.auto_start_delta_c, temps50[x50 - k50])
            n = slots_to_heat(inp, t_x, t50, x50)
            run = range(x50, min(x50 + n, end))
            if run:
                ref_candidates.append((x50, sum(self.heat_price(j, t50) for j in run) / len(run)))

        if dip50 is not None:
            peak_start50 = dip50
            while peak_start50 - 1 >= k50 and (peak_start50 - 1) in inp.hard:
                peak_start50 -= 1
            if peak_start50 > k:
                min_adv_c = min(p.advance_max_start_temp_c, t50 - 3.0)
                best_pre: Optional[float] = None
                for s in range(max(k50, peak_start50 - p.preheat_window_slots), peak_start50):
                    if temps50[s - k50] > min_adv_c:
                        continue
                    n = slots_to_heat(inp, temps50[s - k50], t50, s)
                    if s + n > peak_start50 or any(j in inp.hard for j in range(s, s + n)):
                        continue
                    c = sum(self.heat_price(j, t50) for j in range(s, s + n)) / n
                    if best_pre is None or c < best_pre:
                        best_pre = c
                if best_pre is not None:
                    ref_candidates.append((peak_start50, best_pre))

        if not ref_candidates:
            return None
        # Choose the earliest required intervention after k50 (or highest cost if same boundary)
        ref_candidates.sort(key=lambda item: (item[0], -item[1]))
        until_idx, ref_val = ref_candidates[0]
        n_boost = slots_to_heat(inp, max(t_c, t50), t60, k)
        if not self._cheapest(k, until_idx, n_boost, t60):
            return None
        # Stopping at t50 forces a second separate DHW start later (piping/coil heat-up overhead ~8%)
        return ref_val * 1.08

    # -- the rules -----------------------------------------------------------------------------
    def decide(self, k: int, t_c: float, latch: bool) -> DhwDecision:
        inp, p, spec = self.inp, self.p, self.inp.spec
        t50, t60 = spec.target_setpoint_c, spec.boost_setpoint_c
        lbl = inp.labels
        end = min(k + self.horizon, inp.n)

        # 1. Peak lockout
        if k in inp.hard:
            self.commit = None
            return DhwDecision(MODE_FORCED_OFF, None, "peak_lockout", "Spitsblok: Daikin geblokkeerd (Smart Grid-stand 1)")

        # 2. Finish the run Open HEMS started (upgrade 50 -> 60 °C seamlessly on the same SG4 relay if boost pays)
        if self.commit:
            kind, target_c, ref = self.commit
            if target_c <= t50 and t_c < p.boost_max_start_temp_c:
                ref50 = self._post_50_boost_ref(k, t_c, end)
                if self._is_free(k) or (ref50 is not None and self._beats(self.heat_price(k, t60), ref50)):
                    target_c = t60
                    ref = ref50 if ref50 is not None else ref
                    self.commit = (kind, target_c, ref)
            can_bridge_slot = (
                k + 1 < end
                and (k + 1) not in inp.hard
                and self.heat_price(k, t60) <= ref
                and self._beats(self.heat_price(k + 1, t60), ref)
            )
            still_wanted = (
                kind in (PREHEAT, ADVANCE, IN_FLIGHT)
                or self._beats(self.heat_price(k, t60), ref)
                or can_bridge_slot
                or self._is_free(k)
            )
            if t_c < target_c - p.sg4_release_hysteresis_c and still_wanted:
                mode = MODE_MAX_ON if target_c > t50 else MODE_FORCED_ON
                return DhwDecision(mode, target_c, "continue", f"Lopende run naar {target_c:.0f} °C afmaken")
            self.commit = None

        temps, heat = forecast_autonomous(inp, k, t_c, latch, self.horizon)
        ref_cost: Optional[float] = None
        ref_label = ""
        horizon_end = end

        # 3. Pre-heat before a peak in which the tank would drop below 40 °C + margin
        comfort_c = max(spec.comfort_min_temp_c, t50 - spec.auto_start_delta_c + p.preheat_margin_c)
        dip = next((j for j in range(k, end) if j in inp.hard and temps[j - k] < comfort_c), None)
        if dip is not None:
            peak_start = dip
            while peak_start - 1 >= k and (peak_start - 1) in inp.hard:
                peak_start -= 1
            
            peak_end = dip
            while peak_end < end and peak_end in inp.hard:
                peak_end += 1
                
            horizon_end = peak_start
            
            # Dynamically calculate required temperature to bridge the peak
            min_temp_in_peak = min(temps[peak_start - k : peak_end - k])
            drop = temps[peak_start - k] - min_temp_in_peak
            req_t = comfort_c + drop + 0.5
            req_t = max(t50, min(t60, req_t))
            
            best: Optional[Tuple[float, int]] = None
            for s in range(max(k, peak_start - p.preheat_window_slots), peak_start):
                n = slots_to_heat(inp, temps[s - k], req_t, s)
                if s + n > peak_start:
                    continue
                c = sum(self.heat_price(j, req_t) for j in range(s, s + n)) / n
                if best is None or c < best[0]:
                    best = (c, s)
            if best is None:
                best = (self.heat_price(k, req_t), k)
            ref_cost, ref_label = best[0], f"de voorverwarmrun vóór de spits van {lbl[peak_start]}"
            
            if best[1] == k and t_c < req_t - p.sg4_release_hysteresis_c:
                ref50 = self._post_50_boost_ref(k, t_c, end)
                boost_pays = self._is_free(k) or (ref50 is not None and self._beats(self.heat_price(k, t60), ref50))
                target = t60 if boost_pays else req_t
                return self._start(PREHEAT, target, ref50 if (boost_pays and ref50 is not None) else ref_cost, "preheat",
                                   f"Voorverwarmen naar {target:.0f} °C: zonder ingreep zakt het vat in de spits van "
                                   f"{lbl[peak_start]} onder {comfort_c:.0f} °C; nu is warmte het goedkoopst "
                                   f"(€{best[0]:.3f}/kWh)")
        else:
            x = next((j for j in range(k, end) if heat[j - k]), None)
            if x is not None:
                t_x = min(t50 - spec.auto_start_delta_c, temps[x - k])
                n = slots_to_heat(inp, t_x, t50, x)
                run = range(x, min(x + n, end))
                ref_cost = sum(self.heat_price(j, t50) for j in run) / len(run)
                ref_label, horizon_end = f"de Daikin-run om {lbl[x]}", x

        # 4–6. Heat early when heat is cheap
        if t_c >= p.boost_max_start_temp_c:
            return DhwDecision(MODE_NORMAL, None, "daikin", "Vat (bijna) vol: de Daikin regelt zelf")
        if self._is_free(k):
            return self._start(BOOST_FREE, t60, ref_cost if ref_cost is not None else -math.inf, "free",
                               f"Doorstoken naar 60 °C: stroom is gratis (effectief €{inp.p_eff[k]:.3f}/kWh)")
        if ref_cost is None or horizon_end <= k:
            return DhwDecision(MODE_NORMAL, None, "daikin", "Geen run van de Daikin binnen de horizon: niets te doen")
        c_boost = self.heat_price(k, t60)
        ref50_early = self._post_50_boost_ref(k, t_c, end)
        eff_boost_ref = max(ref_cost, ref50_early) if ref50_early is not None else ref_cost
        if self._cheapest(k, horizon_end, slots_to_heat(inp, t_c, t60, k), t60) and self._beats(c_boost, eff_boost_ref):
            return self._start(BOOST, t60, eff_boost_ref, "boost",
                               f"Doorstoken naar 60 °C: warmte €{c_boost:.3f}/kWh tegen €{eff_boost_ref:.3f} voor {ref_label}")
        min_adv_start_c = min(p.advance_max_start_temp_c, t50 - 3.0)
        if p.advance_margin is not None and t_c <= min_adv_start_c:
            c_adv = self.heat_price(k, t50)
            if self._cheapest(k, horizon_end, slots_to_heat(inp, t_c, t50, k), t50) and c_adv * (1.0 + p.advance_margin) < ref_cost:
                return self._start(ADVANCE, t50, ref_cost, "advance",
                                   f"Vervroegen naar {t50:.0f} °C: warmte €{c_adv:.3f}/kWh tegen €{ref_cost:.3f} voor {ref_label}")
        return DhwDecision(MODE_NORMAL, None, "daikin", f"Geen ingreep: warmte is nu niet duidelijk goedkoper dan voor {ref_label}")


# ---------------------------------------------------------------------------------------------
# Rollout over the horizon: the published DHW plan
# ---------------------------------------------------------------------------------------------

@dataclass
class DhwPolicyRun:
    start_idx: int
    end_idx: int                  # exclusive
    kind: str                     # preheat | advance | boost | boost_free | in_flight
    target_temp_c: float
    t_start_c: float
    t_end_c: float
    kwh_el: float
    cost_eur: float
    reason: str


@dataclass
class DhwPolicyResult:
    slot_modes: List[str]
    slot_targets: List[Optional[float]]
    slot_reasons: List[str]
    slot_dhw_kw: List[float]                  # expected DHW electric power (Open HEMS runs and Daikin's own runs)
    forced_slots: List[int]                   # SG4 quarters
    autonomous_slots: List[int]               # quarters in which the Daikin heats by itself (SG2)
    runs: List[DhwPolicyRun]
    trajectory: Dict[str, List[float]]        # temperatures_c, temperatures_p05_c, temperatures_p95_c, demand_kwh_th
    autonomous_trajectory: List[float]        # tank temperature without any intervention
    first_autonomous_start_idx: Optional[int]
    explanation: str
    total_kwh_el: float = 0.0
    total_cost_eur: float = 0.0
    autonomous_cost_eur: float = 0.0          # cost if Open HEMS only applied the peak lockouts
    saving_eur: float = 0.0                   # autonomous - plan, corrected for the heat left in the tank


def plan_dhw(
    slots: List[Any],
    t0_c: float,
    hard_slots: Set[int],
    dhw_model: Any,
    tariff_provider: Optional[TariffProvider] = None,
    spec: Optional[DhwTankSpec] = None,
    model_parameters: Optional[Dict[str, Any]] = None,
    params: Optional[DhwPolicyParams] = None,
    compressor_heating: bool = False,
    in_flight_target_c: Optional[float] = None,
    p05_factor: float = 0.25,
    p95_factor: float = 1.5,
) -> DhwPolicyResult:
    """
    Pure function: rolls the Daikin-first rules out over the horizon with the P50 tap profile.

    compressor_heating: telemetry shows the Daikin heating DHW by itself right now (its thermostat latch).
    in_flight_target_c: target of the run Layer 4 is executing (read-only), or None.
    """
    spec = spec or DhwTankSpec()
    tp = tariff_provider or TariffProvider()
    inp = PolicyInputs.from_slots(slots, set(hard_slots), spec, dhw_model, tp, model_parameters)
    n = inp.n
    policy = DhwPolicy(inp, params)
    if in_flight_target_c is not None and t0_c < in_flight_target_c - policy.p.sg4_release_hysteresis_c:
        policy.start_in_flight(in_flight_target_c)

    tank = DaikinTank(inp, t0_c, latch=compressor_heating)
    band = {f: DaikinTank(inp, t0_c, latch=compressor_heating, tap_factor=f) for f in (p05_factor, p95_factor)}
    modes: List[str] = []
    targets: List[Optional[float]] = []
    reasons: List[str] = []
    dhw_kw: List[float] = []
    temps, t05, t95 = [round(t0_c, 2)], [round(t0_c, 2)], [round(t0_c, 2)]
    autonomous: List[int] = []
    runs: List[DhwPolicyRun] = []
    open_run: Optional[Dict[str, Any]] = None
    total_kwh = total_cost = 0.0

    for k in range(n):
        d = policy.decide(k, tank.t_c, tank.latch)
        t_before = tank.t_c
        kwh, heating = tank.step(k, d.mode, d.target_temp_c)
        for f, b in band.items():
            b.step(k, d.mode, d.target_temp_c)
        cost = calculate_slot_financials(inp.solar_kw[k], inp.unallocated_kw[k], kwh / DT_H, inp.price_all_in[k], DT_H, tp)[0] if kwh > 0 else 0.0
        total_kwh += kwh
        total_cost += cost
        modes.append(d.mode)
        targets.append(d.target_temp_c)
        reasons.append(d.reason)
        dhw_kw.append(round(kwh / DT_H, 3))
        temps.append(round(tank.t_c, 2))
        t05.append(round(band[p05_factor].t_c, 2))
        t95.append(round(band[p95_factor].t_c, 2))
        if heating and d.mode == MODE_NORMAL:
            autonomous.append(k)

        forced = d.mode in (MODE_FORCED_ON, MODE_MAX_ON)
        if forced and open_run is None:
            kind = policy.commit[0] if policy.commit else IN_FLIGHT
            open_run = {"start": k, "kind": kind, "target": d.target_temp_c, "t_start": t_before, "kwh": 0.0, "cost": 0.0,
                        "reason": d.reason}
        if open_run is not None and forced:
            open_run["kwh"] += kwh
            open_run["cost"] += cost
            open_run["target"] = d.target_temp_c
        if open_run is not None and (not forced or k == n - 1):
            end = k + 1 if forced else k
            runs.append(DhwPolicyRun(open_run["start"], end, open_run["kind"], float(open_run["target"]),
                                     round(open_run["t_start"], 1), round(temps[end], 1), round(open_run["kwh"], 2),
                                     round(open_run["cost"], 3), open_run["reason"]))
            open_run = None

    # Counterfactual "Daikin autonomous" (SG1 in peaks only), same tank model and cost function
    auto_tank = DaikinTank(inp, t0_c, latch=compressor_heating)
    auto_cost = 0.0
    for k in range(n):
        kwh, _ = auto_tank.step(k, MODE_FORCED_OFF if k in inp.hard else MODE_NORMAL, None)
        if kwh > 0:
            auto_cost += calculate_slot_financials(inp.solar_kw[k], inp.unallocated_kw[k], kwh / DT_H, inp.price_all_in[k], DT_H, tp)[0]
    heat_price_per_k = 0.0
    if n:
        mean_heat_price = sum(inp.p_eff[k] / dhw_cop(NORMAL_RUN_COP_TANK_C, inp.outdoor_temp_c[k], params=inp.model_parameters)
                              for k in range(n)) / n
        heat_price_per_k = inp.c_tank * mean_heat_price
    saving = auto_cost - total_cost + (tank.t_c - auto_tank.t_c) * heat_price_per_k

    auto_temps, auto_heat = forecast_autonomous(inp, 0, t0_c, compressor_heating, n)
    first_auto = next((j for j, h in enumerate(auto_heat) if h), None)
    def when(k: int) -> str:
        """Clock time of quarter k, prefixed with the day when it is not the first day of the horizon."""
        day0 = (inp.dts[0].astimezone(AMS_TZ) if inp.dts[0].tzinfo else inp.dts[0]).date()
        dk = inp.dts[k].astimezone(AMS_TZ) if inp.dts[k].tzinfo else inp.dts[k]
        offset = (dk.date() - day0).days
        prefix = {0: "", 1: "morgen "}.get(offset, f"over {offset} dagen ")
        return prefix + dk.strftime("%H:%M")

    if runs:
        explanation = " ".join(f"{when(r.start_idx)}: {r.reason}." for r in runs[:3])
    elif first_auto is not None:
        explanation = f"Geen ingreep nodig: de Daikin warmt zelf op rond {when(first_auto)}."
    else:
        explanation = "Geen ingreep nodig: het vat blijft binnen de horizon boven de comfortgrens."

    return DhwPolicyResult(
        slot_modes=modes, slot_targets=targets, slot_reasons=reasons, slot_dhw_kw=dhw_kw,
        forced_slots=[k for k, m in enumerate(modes) if m in (MODE_FORCED_ON, MODE_MAX_ON)],
        autonomous_slots=autonomous, runs=runs,
        trajectory={"temperatures_c": temps, "temperatures_p05_c": t05, "temperatures_p95_c": t95,
                    "demand_kwh_th": [round(q, 4) for q in inp.tap_p50_kwh]},
        autonomous_trajectory=[round(t, 2) for t in auto_temps], first_autonomous_start_idx=first_auto,
        explanation=explanation, total_kwh_el=round(total_kwh, 2), total_cost_eur=round(total_cost, 3),
        autonomous_cost_eur=round(auto_cost, 3), saving_eur=round(saving, 3),
    )
