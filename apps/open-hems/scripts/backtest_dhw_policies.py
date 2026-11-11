#!/usr/bin/env python3
"""
Open HEMS — DHW Policy Backtest (closed loop)
=============================================
Evidence base for docs/adr/ADR-006-daikin-first-dhw-policy.md.

Compares domestic hot water (DHW) control policies on recorded site data with the production
physics and cost functions:
  - models.physics: lumped tank balance (dhw_step), dhw_cop, dhw_electric_power_kw
  - layer2_calibration.dhw_thermal_model: learned 7x96 tap profile (P50) and calibrated tank UA
  - layer3_scheduling.peak_detection.detect_dynamic_price_peaks: hard SG1 lockouts, per local day
  - layer3_scheduling.dhw_financials.calculate_slot_financials: solar self-consumption at export value

Plant model (identical for every policy):
  SG2  Daikin thermostat: starts at <= setpoint - auto_start_delta (40 °C), stops at the setpoint (50 °C)
  SG1  compressor blocked; the thermostat demand is remembered until the block ends
  SG4  forced heating until the software stop (50 °C, 60 °C or a DP target), never above 60 °C

Policies:
  auto                Daikin autonomous; Open HEMS only applies SG1 in hard peak lockouts
  literal             the proposal as written: the boost compares EUR per kWh electricity and calls a quarter
                      'cheap' when it is in the cheapest 20 % of the horizon; pre-heat always stops at 50 °C
  daikin_first        ADR-006: heat price (EUR per kWh heat = price / COP); free electricity (effective price
                      <= 0) heats to 60 °C; a boost to 60 °C or an advanced run to 50 °C in the n cheapest
                      quarters before X when heat is clearly cheaper than at X
  daikin_first_noadvance  daikin_first without advancing the Daikin's own run to 50 °C
  daikin_first_nocop  daikin_first, but comparing EUR per kWh electricity (isolates the COP effect)
  dp                  current exact DP (dhw_optimizer.solve), re-solved every quarter with the observed
                      compressor state including min-run/dwell; SG4 until the DP run target
  dp_coupled          the DP coupled the way production does it: ON_MANDATORY while a committed SG4 run is
                      below its target, otherwise ON_FREE/OFF_FREE. Exaggerates target creep compared to
                      production, because commitments are re-evaluated per quarter instead of per minute.

Every planner sees a perfect 24 h forecast of prices, solar and outdoor temperature and plans on the
learned P50 tap profile. The plant draws P50 (scenario 'p50') or 1.5 x P50 (scenario 'heavy').

Usage:
  PYTHONPATH=. python3 scripts/backtest_dhw_policies.py extract --start 2026-01-01 --days 31 \\
      --out /config/open_hems_backtest/2026-01.json
  PYTHONPATH=. python3 scripts/backtest_dhw_policies.py run --data /config/open_hems_backtest/2026-01.json
  (48 h horizon: extract with --horizon-days 2, run with --horizon-hours 48)

Prices come from the public EnergyZero API (quarter-hour data, available from 2025-10-01): all-in incl. VAT
plus the supplier markup, exactly as api.energy_feed.get_epex_tariffs_cached feeds the planner. Solar
self-consumption is valued by the production TariffProvider. Telemetry comes from InfluxDB 'openhems'.
The extracted file contains recorded site telemetry: keep it outside the repository.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.http_client import safe_urlopen
from api.secrets_store import CONFIG_FILE, PARAMS_FILE, load_json, load_secrets
from layer2_calibration.dhw_thermal_model import DhwThermalModel
from layer3_scheduling.dhw_financials import calculate_slot_financials
from layer3_scheduling.dhw_optimizer import DhwOptimizerParams, solve
from layer3_scheduling.dhw_policy import (DhwPolicy, DhwPolicyParams, PolicyInputs, MODE_FORCED_OFF, MODE_FORCED_ON,
                                          MODE_MAX_ON)
from layer3_scheduling.dhw_specs import DhwTankSpec
from layer3_scheduling.peak_detection import detect_dynamic_price_peaks
from layer3_scheduling.tariff_provider import TariffProvider
from models.physics import dhw_cop, dhw_electric_power_kw, dhw_step

AMS = ZoneInfo("Europe/Amsterdam")
STEP_S = 900
DT_H = 0.25
DEFAULT_HORIZON_HOURS = 24   # planning horizon of every planner
T_AMB_C = 18.0               # technical room temperature, as in DhwOptimizerParams
HEAVY_TAP_FACTOR = 1.5       # 'heavy' scenario: the plant draws 1.5 x the learned P50 profile
COMFORT_REPORT_C = 39.5      # hours below this are reported; the thermostat itself starts at 40 °C
SG4_RELEASE_HYSTERESIS_C = 0.2
EZ_URL = ("https://public.api.energyzero.nl/public/v1/prices?energyType=ENERGY_TYPE_ELECTRICITY"
          "&date={d}&interval=INTERVAL_QUARTER")
POLICIES = ["auto", "literal", "daikin_first", "daikin_first_noadvance", "daikin_first_nocop", "dp", "dp_coupled"]
SCENARIOS = ["p50", "heavy"]


# ---------------------------------------------------------------------------------------------
# 1. Extraction (EnergyZero prices + InfluxDB telemetry)
# ---------------------------------------------------------------------------------------------

def _influx_connection() -> Tuple[str, str, str, str]:
    cfg = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
    conn = next((c for c in cfg.get("influxdb_connections", []) if c.get("id") == "local_ha_influxdb"), {})
    url = conn.get("url") or cfg.get("influxdb", {}).get("url", "http://a0d7b954-influxdb:8086")
    db = conn.get("read_database") or conn.get("database") or "openhems"
    user = conn.get("username") or "openhems"
    sec = load_secrets()
    pwd = sec.get("influxdb", {}).get("openhems_db") or sec.get("influxdb", {}).get("local_ha_influxdb") or sec.get("influx_password", "")
    return str(url).rstrip("/"), str(db), str(user), str(pwd)


def _influx_mean_15m(conn: Tuple[str, str, str, str], measurement: str, fld: str, condition: str,
                     t0_iso: str, t1_iso: str) -> Dict[int, float]:
    url, db, user, pwd = conn
    where = f"time >= '{t0_iso}' AND time < '{t1_iso}'" + (f" AND {condition}" if condition else "")
    query = f'SELECT mean("{fld}") FROM "{measurement}" WHERE {where} GROUP BY time(15m) fill(none)'
    full = f"{url}/query?" + urllib.parse.urlencode({"u": user, "p": pwd, "db": db, "q": query, "epoch": "s"})
    with safe_urlopen(full, timeout=180) as r:
        res = json.loads(r.read().decode("utf-8"))
    series = res.get("results", [{}])[0].get("series", [])
    if not series:
        return {}
    return {int(v[0]): float(v[1]) for v in series[0]["values"] if v[1] is not None}


def _merged(primary: Dict[int, float], fallback: Dict[int, float]) -> Dict[int, float]:
    out = dict(fallback)
    out.update(primary)
    return out


def _energyzero_prices(first_day: date, last_day: date) -> Tuple[Dict[int, float], Dict[int, float]]:
    """Quarter-hour EPEX spot ('base', EUR/kWh excl. VAT) and 'all_in_with_vat' (spot and energy tax incl. VAT,
    without supplier markup). One request returns the day before, the day and the day after."""
    spot: Dict[int, float] = {}
    all_in: Dict[int, float] = {}
    d = first_day + timedelta(days=1)
    while d - timedelta(days=1) <= last_day:
        with safe_urlopen(EZ_URL.format(d=d.strftime("%d-%m-%Y")), timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
        for key, target in (("base", spot), ("all_in_with_vat", all_in)):
            for it in payload.get(key, []):
                ts = int(datetime.fromisoformat(str(it["start"]).replace("Z", "+00:00")).timestamp())
                target[ts] = float(it["price"]["value"])
        d += timedelta(days=3)
        time.sleep(1.0)
    return spot, all_in


def extract(start: date, days: int, out_path: Path, horizon_days: int = 1) -> None:
    """Writes `days` simulation days plus `horizon_days` look-ahead days of 15-minute inputs to `out_path`."""
    t0 = datetime(start.year, start.month, start.day, tzinfo=AMS)
    last_day = start + timedelta(days=days + horizon_days - 1)
    t1 = datetime(last_day.year, last_day.month, last_day.day, tzinfo=AMS) + timedelta(days=1)
    t0_iso = t0.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t1_iso = t1.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = _influx_connection()
    tele = "energy_telemetry"
    spot, all_in_with_vat = _energyzero_prices(start, last_day)
    series = {
        "spot": spot,
        "all_in_with_vat": all_in_with_vat,
        "solar_w": _merged(_influx_mean_15m(conn, tele, "solar_w", "\"source\"='canonical_accumulator'", t0_iso, t1_iso),
                           _influx_mean_15m(conn, tele, "solar_w", "\"source\"='ha_history_import'", t0_iso, t1_iso)),
        "unalloc_w": _merged(_influx_mean_15m(conn, tele, "unallocated_w", "\"source\"='canonical_accumulator'", t0_iso, t1_iso),
                             _influx_mean_15m(conn, tele, "unallocated_w", "\"source\"='ha_history_import'", t0_iso, t1_iso)),
        "t_out": _merged(_influx_mean_15m(conn, tele, "temperature_c", "\"device_id\"='outdoor_weather'", t0_iso, t1_iso),
                         _influx_mean_15m(conn, "weather_forecast", "outdoor_temp_c", "", t0_iso, t1_iso)),
        "t_tank": _influx_mean_15m(conn, tele, "temperature_c", "\"device_id\"='dhw_tank'", t0_iso, t1_iso),
    }
    n_slots = int((t1 - t0).total_seconds()) // STEP_S
    doc = {
        "meta": {
            "start_local": start.isoformat(), "simulation_days": days, "horizon_days": horizon_days, "n_slots": n_slots,
            "t0_epoch": int(t0.timestamp()), "extracted_at": datetime.now(timezone.utc).isoformat(),
            "sources": {"prices": "EnergyZero public API (base, all_in_with_vat; quarter)", "telemetry": "InfluxDB openhems"},
        },
        "series": {k: {str(ts): v for ts, v in sorted(s.items())} for k, s in series.items()},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc), encoding="utf-8")
    t0_ep = int(t0.timestamp())
    for k, s in series.items():
        covered = sum(1 for i in range(n_slots) if t0_ep + i * STEP_S in s)
        print(f"{k:>10}: {covered}/{n_slots} quarters")
    print(f"Written {out_path}")


# ---------------------------------------------------------------------------------------------
# 2. Simulation context and plant
# ---------------------------------------------------------------------------------------------

@dataclass
class Slot:
    dt: datetime                 # local time (tap-profile lookup and labels)
    label: str
    price_all_in: float
    solar_kw: float
    unallocated_kw: float
    outdoor_temp_c: float
    tap_p50: float               # learned P50 tap demand of this quarter (kWh_th)


@dataclass
class Context:
    slots: List[Slot]
    hard: Set[int]
    spec: DhwTankSpec
    opt_params: DhwOptimizerParams
    tp: TariffProvider
    model: DhwThermalModel
    mp: Dict[str, Any]
    ua_w_per_k: float
    c_tank: float
    t0_c: float
    tap_factor: float
    horizon: int                 # planning horizon in quarters
    n_decisions: int             # simulated quarters (the look-ahead days are only forecast input)
    p_eff: List[float] = field(default_factory=list)   # effective EUR/kWh_el for a nominal DHW run
    cop45: List[float] = field(default_factory=list)   # COP of a normal 40->50 °C run


def load_context(data_path: Path, scenario: str, horizon_hours: float = DEFAULT_HORIZON_HOURS) -> Context:
    doc = json.loads(data_path.read_text(encoding="utf-8"))
    meta, series = doc["meta"], doc["series"]
    cfg = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
    mp = load_json(PARAMS_FILE) if PARAMS_FILE.exists() else {}
    tp = TariffProvider.from_dict(cfg)
    model = DhwThermalModel()

    # Same price the planner gets from api.energy_feed.get_epex_tariffs_cached: EnergyZero all-in incl. VAT
    # plus the supplier import markup (config fallback; the live value comes from Home Assistant).
    markup = float(cfg.get("dynamic_tariffs", {}).get("fallback_markup_import", 0.0121))
    last = {"all_in_with_vat": 0.25, "solar_w": 0.0, "unalloc_w": 300.0, "t_out": 10.0}
    slots: List[Slot] = []
    t0_c: Optional[float] = None
    for i in range(int(meta["n_slots"])):
        ts = int(meta["t0_epoch"]) + i * STEP_S
        for key in last:
            v = series.get(key, {}).get(str(ts))
            if v is not None:
                last[key] = float(v)
        if t0_c is None:
            v_tank = series.get("t_tank", {}).get(str(ts))
            t0_c = float(v_tank) if v_tank is not None else None
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(AMS)
        q_idx = dt.hour * 4 + dt.minute // 15
        slots.append(Slot(
            dt=dt, label=dt.strftime("%a %d %H:%M"),
            price_all_in=round(last["all_in_with_vat"] + markup, 5),
            solar_kw=max(0.0, last["solar_w"]) / 1000.0,
            unallocated_kw=max(0.0, last["unalloc_w"]) / 1000.0,
            outdoor_temp_c=last["t_out"],
            tap_p50=model.get_learned_tap_kwh_th(dt.weekday(), q_idx),
        ))

    # Hard SG1 lockouts: production detector, once per local calendar day (shared by every policy)
    hard: Set[int] = set()
    by_day: Dict[date, List[int]] = {}
    for i, s in enumerate(slots):
        by_day.setdefault(s.dt.date(), []).append(i)
    for idxs in by_day.values():
        items = [{"idx": n, "dt": slots[i].dt, "label": slots[i].label, "price": slots[i].price_all_in,
                  "solar": slots[i].solar_kw, "unalloc": slots[i].unallocated_kw} for n, i in enumerate(idxs)]
        _, lmap = detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150)
        hard.update(idxs[n] for n, v in lmap.items() if v.get("is_hard_lockout"))

    sim_end = date.fromisoformat(meta["start_local"]) + timedelta(days=int(meta["simulation_days"]))
    n_decisions = sum(1 for s in slots if s.dt.date() < sim_end)
    horizon = int(round(horizon_hours * 4))
    if n_decisions + horizon > len(slots):
        raise ValueError(f"{data_path} has too little look-ahead for a {horizon_hours:g} h horizon; "
                         f"extract with --horizon-days {math.ceil(horizon_hours / 24)}")

    spec = DhwTankSpec.from_config(cfg)
    ctx = Context(
        slots=slots, hard=hard, spec=spec, opt_params=DhwOptimizerParams.from_config(cfg), tp=tp, model=model, mp=mp,
        ua_w_per_k=model.get_tank_ua(), c_tank=spec.thermal_capacity_kwh_per_k, t0_c=t0_c if t0_c is not None else 47.0,
        tap_factor=HEAVY_TAP_FACTOR if scenario == "heavy" else 1.0, horizon=horizon, n_decisions=n_decisions,
    )
    for s in slots:
        kw = dhw_electric_power_kw(50.0, s.outdoor_temp_c, params=mp)
        ctx.p_eff.append(calculate_slot_financials(s.solar_kw, s.unallocated_kw, kw, s.price_all_in, DT_H, tp)[3])
        ctx.cop45.append(dhw_cop(45.0, s.outdoor_temp_c, params=mp))
    _check_against_canonical_step(ctx)
    return ctx


def heat_step(ctx: Context, t_c: float, heat_on: bool, stop_c: float, j: int, tap_kwh: float) -> Tuple[float, float, bool]:
    """Lumped tank step with the equations of models.physics.dhw_step, plus the electric energy used.
    Returns (next temperature, kWh_el, stop temperature reached within this quarter)."""
    s = ctx.slots[j]
    p_el = dhw_electric_power_kw(t_c, s.outdoor_temp_c, params=ctx.mp)
    raw = p_el * dhw_cop(t_c, s.outdoor_temp_c, params=ctx.mp) * DT_H
    q = min(raw, max(0.0, (stop_c - t_c) * ctx.c_tank)) if (heat_on and t_c < stop_c) else 0.0
    kwh_el = (q / raw) * p_el * DT_H if raw > 0 else 0.0
    standby = ctx.ua_w_per_k * max(0.0, t_c - T_AMB_C) * DT_H / 1000.0
    reached = heat_on and q < raw - 1e-9
    return max(15.0, t_c + (q - standby - tap_kwh) / ctx.c_tank), kwh_el, reached


def _check_against_canonical_step(ctx: Context) -> None:
    s = ctx.slots[0]
    mine, _, _ = heat_step(ctx, 45.0, True, 60.0, 0, 0.1)
    ref = dhw_step(45.0, 1.0, 0.1, s.outdoor_temp_c, DT_H,
                   spec={"thermal_capacity_kwh_per_k": ctx.c_tank, "ua_w_per_k": ctx.ua_w_per_k,
                         "heat_pump_power_kw": dhw_electric_power_kw(45.0, s.outdoor_temp_c, params=ctx.mp)},
                   params=ctx.mp, t_max_c=60.0, t_amb_c=T_AMB_C)
    if abs(mine - ref) > 1e-6:
        raise RuntimeError(f"Backtest tank step diverges from models.physics.dhw_step ({mine} vs {ref})")


class Plant:
    """The Daikin: thermostat demand latch (start <= 40 °C, stop at 50 °C) under SG2; SG1 blocks; SG4 forces."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.t_c = ctx.t0_c
        self.latch = False

    def step(self, j: int, mode: str, stop_c: Optional[float]) -> Tuple[float, float]:
        spec = self.ctx.spec
        if self.t_c <= spec.target_setpoint_c - spec.auto_start_delta_c + 1e-6:
            self.latch = True
        if mode == "SG1":
            heat_on, stop = False, spec.target_setpoint_c
        elif mode == "SG4":
            heat_on, stop = True, min(spec.boost_setpoint_c, stop_c if stop_c is not None else spec.boost_setpoint_c)
        else:
            heat_on, stop = self.latch, spec.target_setpoint_c
        t_next, kwh_el, reached = heat_step(self.ctx, self.t_c, heat_on, stop, j, self.ctx.slots[j].tap_p50 * self.ctx.tap_factor)
        if heat_on and ((reached and stop >= spec.target_setpoint_c) or t_next >= spec.target_setpoint_c):
            self.latch = False      # the Daikin's own demand is satisfied once the tank passed 50 °C
        self.t_c = t_next
        s = self.ctx.slots[j]
        cost = calculate_slot_financials(s.solar_kw, s.unallocated_kw, kwh_el / DT_H, s.price_all_in, DT_H, self.ctx.tp)[0] if kwh_el > 0 else 0.0
        return kwh_el, cost


def forecast_autonomous(ctx: Context, k: int, t_c: float, latch: bool) -> Tuple[List[float], List[bool]]:
    """Planner's view of 'Daikin autonomous' from quarter k: P50 tap profile, SG1 in hard lockouts."""
    temps, heat = [t_c], []
    on = latch
    for j in range(k, min(k + ctx.horizon, len(ctx.slots))):
        if t_c <= 40.0 + 1e-6:
            on = True
        h = on and j not in ctx.hard
        t_c, _, reached = heat_step(ctx, t_c, h, 50.0, j, ctx.slots[j].tap_p50)
        if h and reached:
            on = False
        heat.append(h)
        temps.append(t_c)
    return temps, heat


def slots_to_heat(ctx: Context, t_from: float, t_to: float, j: int) -> int:
    s = ctx.slots[j]
    rate = dhw_electric_power_kw(t_from, s.outdoor_temp_c, params=ctx.mp) * dhw_cop(t_from, s.outdoor_temp_c, params=ctx.mp) * DT_H
    return max(1, math.ceil(max(0.0, t_to - t_from) * ctx.c_tank / max(rate, 0.1)))


# ---------------------------------------------------------------------------------------------
# 3. Policies
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleParams:
    cop_aware: bool = True                 # compare EUR per kWh heat (price / COP) instead of EUR per kWh electricity
    window_fill: bool = True               # boost in the n cheapest quarters before X (False: 'cheapest 20 %' test)
    free_price_eur: Optional[float] = 0.0  # effective price at/below which heating to 60 °C is always worth it
    advance_margin: Optional[float] = 0.10  # advance the Daikin's own run to 50 °C when heat is this much cheaper now
    advance_max_start_c: float = 47.0      # only advance when at least ~3 K can be added (no short runs)
    preheat_margin_c: float = 1.0          # forecast below 40 + margin inside a hard lockout triggers a pre-heat
    preheat_window_slots: int = 16         # pre-heat start is chosen within 4 h before the peak
    boost_standby_factor: float = 0.05     # extra standby loss of a 60 °C tank, as a fraction of the boost cost
    boost_margin_eur: float = 0.005        # minimum advantage per kWh to start a boost (prevents flutter)
    boost_max_start_c: float = 57.0        # no boost on a (nearly) full tank
    cheap_fraction: float = 0.20           # 'literal' variant: cheapest fraction of the horizon counts as cheap


# Prototype rules, kept only for variants the production policy deliberately does not support
RULE_VARIANTS = {
    "literal": RuleParams(cop_aware=False, window_fill=False, free_price_eur=None, advance_margin=None),
    "daikin_first_nocop": RuleParams(cop_aware=False),
}


class RulesPolicy:
    """Daikin-first: SG2 by default, SG1 in peaks, pre-heat before a forecast peak dip, heat early when heat is cheap."""

    def __init__(self, ctx: Context, params: RuleParams):
        self.ctx = ctx
        self.p = params
        self.commit: Optional[Tuple[str, float, float]] = None   # (kind, target °C, reference cost)
        self.events = {"preheat": 0, "advance": 0, "boost": 0, "boost_free": 0}

    def _cost(self, j: int, t_from: float, t_to: float) -> float:
        """Heat price of a run to t_to in quarter j: EUR per kWh_th with the COP at 45 °C (run to 50 °C) or
        55 °C (boost to 60 °C) and that quarter's outdoor temperature; EUR per kWh_el when not COP-aware."""
        if not self.p.cop_aware:
            return self.ctx.p_eff[j]
        return self.ctx.p_eff[j] / dhw_cop(55.0 if t_to > 50.0 else 45.0, self.ctx.slots[j].outdoor_temp_c, params=self.ctx.mp)

    def _is_free(self, j: int) -> bool:
        return self.p.free_price_eur is not None and self.ctx.p_eff[j] <= self.p.free_price_eur

    def _beats(self, c_now: float, ref: float) -> bool:
        return c_now * (1.0 + self.p.boost_standby_factor) + self.p.boost_margin_eur < ref

    def _start(self, kind: str, target_c: float, ref: float) -> Tuple[str, Optional[float]]:
        self.commit = (kind, target_c, ref)
        self.events[kind] += 1
        return "SG4", target_c

    def _cheapest(self, k: int, until: int, n: int, t_from: float, t_to: float) -> bool:
        """True when quarter k is among the n cheapest quarters (heat price) in [k, until)."""
        ranked = sorted(range(k, until), key=lambda j: self._cost(j, t_from, t_to))
        return k in set(ranked[:n])

    def decide(self, k: int, plant: Plant) -> Tuple[str, Optional[float]]:
        ctx, p = self.ctx, self.p
        t_c = plant.t_c
        if k in ctx.hard:
            self.commit = None
            return "SG1", None
        if self.commit:
            kind, target_c, ref = self.commit
            still_wanted = kind in ("preheat", "advance") or self._beats(self._cost(k, t_c, 60.0), ref) or self._is_free(k)
            if t_c < target_c - SG4_RELEASE_HYSTERESIS_C and still_wanted:
                return "SG4", target_c
            self.commit = None

        temps, heat = forecast_autonomous(ctx, k, t_c, plant.latch)
        end = min(k + ctx.horizon, len(ctx.slots))
        ref_cost: Optional[float] = None
        horizon_end = end

        # Rule 2 (ADR-006) — pre-heat: the forecast dips below 40 °C + margin inside a hard lockout
        dip = next((j for j in range(k, end) if j in ctx.hard and temps[j - k] < 40.0 + p.preheat_margin_c), None)
        if dip is not None:
            peak_start = dip
            while peak_start - 1 >= k and (peak_start - 1) in ctx.hard:
                peak_start -= 1
            horizon_end = peak_start
            best: Optional[Tuple[float, int]] = None
            for s in range(max(k, peak_start - p.preheat_window_slots), peak_start):
                n = slots_to_heat(ctx, temps[s - k], 50.0, s)
                if s + n > peak_start:
                    continue
                c = sum(self._cost(j, temps[s - k], 50.0) for j in range(s, s + n)) / n
                if best is None or c < best[0]:
                    best = (c, s)
            if best is None:                       # not enough time left: start now
                best = (self._cost(k, t_c, 50.0), k)
            ref_cost = best[0]
            if best[1] == k and t_c < 50.0 - SG4_RELEASE_HYSTERESIS_C:
                return self._start("preheat", 60.0 if self._is_free(k) else 50.0, ref_cost)
        else:
            x = next((j for j in range(k, end) if heat[j - k]), None)
            if x is not None:
                t_x = min(40.0, temps[x - k])
                n = slots_to_heat(ctx, t_x, 50.0, x)
                run = range(x, min(x + n, end))
                ref_cost = sum(self._cost(j, t_x, 50.0) for j in run) / len(run)
                horizon_end = x

        # Rule 3 (ADR-006) — heat early when heat is cheap: free electricity, a boost to 60 °C,
        # or advancing the Daikin's own run to 50 °C
        if t_c >= p.boost_max_start_c:
            return "SG2", None
        if self._is_free(k):
            # Continue while still free, or while it still beats the run it replaces
            return self._start("boost_free", 60.0, ref_cost if ref_cost is not None else -math.inf)
        if ref_cost is None or horizon_end <= k:
            return "SG2", None
        c_boost = self._cost(k, t_c, 60.0)
        if p.window_fill:
            cheap_enough = self._cheapest(k, horizon_end, slots_to_heat(ctx, t_c, 60.0, k), t_c, 60.0)
        else:
            window = sorted(ctx.p_eff[k:end])
            cheap_enough = c_boost <= window[max(0, int(p.cheap_fraction * len(window)) - 1)]
        if cheap_enough and self._beats(c_boost, ref_cost):
            return self._start("boost", 60.0, ref_cost)
        if p.advance_margin is not None and t_c <= p.advance_max_start_c:
            c_adv = self._cost(k, t_c, 50.0)
            if (self._cheapest(k, horizon_end, slots_to_heat(ctx, t_c, 50.0, k), t_c, 50.0)
                    and c_adv * (1.0 + p.advance_margin) < ref_cost):
                return self._start("advance", 50.0, ref_cost)
        return "SG2", None


PRODUCTION_VARIANTS = {
    "daikin_first": DhwPolicyParams(),
    "daikin_first_noadvance": DhwPolicyParams(advance_margin=None),
}


class ProductionPolicy:
    """The production rules (layer3_scheduling.dhw_policy) as closed-loop controller."""

    def __init__(self, ctx: Context, params: DhwPolicyParams):
        s = ctx.slots
        inp = PolicyInputs(
            dts=[x.dt for x in s], labels=[x.label for x in s], outdoor_temp_c=[x.outdoor_temp_c for x in s],
            tap_p50_kwh=[x.tap_p50 for x in s], p_eff=list(ctx.p_eff), hard=set(ctx.hard), spec=ctx.spec,
            model_parameters=ctx.mp, ua_w_per_k=ctx.ua_w_per_k, tariff_provider=ctx.tp,
            price_all_in=[x.price_all_in for x in s], solar_kw=[x.solar_kw for x in s], unallocated_kw=[x.unallocated_kw for x in s])
        self.policy = DhwPolicy(inp, params, horizon=ctx.horizon)

    @property
    def events(self) -> Dict[str, int]:
        return self.policy.events

    def decide(self, k: int, plant: "Plant") -> Tuple[str, Optional[float]]:
        d = self.policy.decide(k, plant.t_c, plant.latch)
        if d.mode == MODE_FORCED_OFF:
            return "SG1", None
        if d.mode in (MODE_FORCED_ON, MODE_MAX_ON):
            return "SG4", d.target_temp_c
        return "SG2", None


class DpPolicy:
    """Current exact DP (dhw_optimizer.solve) as receding-horizon controller."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.solve_ms: List[float] = []

    def decide(self, k: int, plant: Plant, run_state: Any) -> Tuple[str, Optional[float]]:
        ctx = self.ctx
        if k in ctx.hard:
            return "SG1", None
        end = min(k + ctx.horizon, len(ctx.slots))
        peaks = [{"slot_idx": j - k, "is_hard_lockout": True} for j in range(k, end) if j in ctx.hard]
        t_start = time.perf_counter()
        res = solve(slots=ctx.slots[k:end], t0_c=plant.t_c, run_state0=run_state, dhw_model=ctx.model, tariff_provider=ctx.tp,
                    spec=ctx.spec, params=ctx.opt_params, dynamic_peaks=peaks, model_parameters=ctx.mp)
        self.solve_ms.append((time.perf_counter() - t_start) * 1000.0)
        if 0 in res.planned_slots and res.runs:
            return "SG4", float(res.runs[0].t_end_c)
        return "SG2", None


# ---------------------------------------------------------------------------------------------
# 4. Closed-loop simulation
# ---------------------------------------------------------------------------------------------

def simulate(data_path: str, policy: str, scenario: str, horizon_hours: float = DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    ctx = load_context(Path(data_path), scenario, horizon_hours)
    plant = Plant(ctx)
    rules: Any = None
    if policy in RULE_VARIANTS:
        rules = RulesPolicy(ctx, RULE_VARIANTS[policy])
    elif policy in PRODUCTION_VARIANTS:
        rules = ProductionPolicy(ctx, PRODUCTION_VARIANTS[policy])
    dp = DpPolicy(ctx) if policy in ("dp", "dp_coupled") else None

    n_decisions = ctx.n_decisions
    kwh_total = cost_total = 0.0
    starts = sg4_quarters = below = 0
    t_min, t_max = plant.t_c, plant.t_c
    prev_on, on_count, off_count = False, 0, 0
    prev_mode, prev_stop = "SG2", None
    daily: Dict[str, float] = {}
    for k in range(n_decisions):
        if policy == "auto":
            mode, stop = ("SG1", None) if k in ctx.hard else ("SG2", None)
        elif rules is not None:
            mode, stop = rules.decide(k, plant)
        elif dp is not None and policy == "dp":
            mode, stop = dp.decide(k, plant, ("ON", on_count) if prev_on else ("OFF", off_count))
        elif dp is not None:
            committed = prev_mode == "SG4" and prev_stop is not None and plant.t_c < prev_stop - SG4_RELEASE_HYSTERESIS_C
            run_state = ("ON_MANDATORY", 1) if committed else (("ON_FREE", 0) if prev_on else ("OFF_FREE", 0))
            mode, stop = dp.decide(k, plant, run_state)
        else:
            raise ValueError(f"Unknown policy '{policy}'")
        prev_mode, prev_stop = mode, stop

        kwh_el, cost = plant.step(k, mode, stop)
        on = kwh_el > 1e-6
        starts += int(on and not prev_on)
        on_count = on_count + 1 if on else 0
        off_count = 0 if on else off_count + 1
        prev_on = on
        sg4_quarters += int(mode == "SG4")
        kwh_total += kwh_el
        cost_total += cost
        t_min, t_max = min(t_min, plant.t_c), max(t_max, plant.t_c)
        below += int(plant.t_c < COMFORT_REPORT_C)
        day = ctx.slots[k].dt.date().isoformat()
        daily[day] = daily.get(day, 0.0) + cost

    # Heat left in the tank differs per policy: value the end-state difference at the period's average
    # cost of normal-run heat, so a policy cannot look cheaper by ending with an emptier tank.
    p_ref = sum(ctx.p_eff[:n_decisions]) / n_decisions
    cop_ref = sum(ctx.cop45[:n_decisions]) / n_decisions
    stored_heat_eur = (plant.t_c - ctx.t0_c) * ctx.c_tank * p_ref / cop_ref

    result: Dict[str, Any] = {
        "policy": policy, "scenario": scenario, "days": len(daily), "horizon_hours": horizon_hours,
        "period": f"{ctx.slots[0].dt.date()} .. {ctx.slots[n_decisions - 1].dt.date()}",
        "hard_lockout_hours": round(sum(1 for h in ctx.hard if h < n_decisions) / 4, 1),
        "cost_eur": round(cost_total, 2), "cost_adj_eur": round(cost_total - stored_heat_eur, 2), "kwh_el": round(kwh_total, 1),
        "eur_per_kwh_el": round(cost_total / kwh_total, 4) if kwh_total else None,
        "starts": starts, "sg4_quarters": sg4_quarters,
        "hours_below_comfort": below / 4, "t_min_c": round(t_min, 2), "t_max_c": round(t_max, 2),
        "t_start_c": round(ctx.t0_c, 2), "t_end_c": round(plant.t_c, 2),
        "daily_cost_eur": {d: round(v, 3) for d, v in daily.items()},
    }
    if rules is not None:
        result["events"] = rules.events
    if dp is not None and dp.solve_ms:
        result["solve_ms_median"] = round(sorted(dp.solve_ms)[len(dp.solve_ms) // 2], 1)
    return result


def run(data_path: Path, policies: List[str], scenarios: List[str], jobs: int, json_out: Optional[Path],
        horizon_hours: float = DEFAULT_HORIZON_HOURS) -> None:
    load_context(data_path, scenarios[0], horizon_hours)    # fail fast on missing look-ahead, before forking workers
    combos = [(p, s) for s in scenarios for p in policies]
    with ProcessPoolExecutor(max_workers=max(1, min(jobs, len(combos)))) as pool:
        futures = {combo: pool.submit(simulate, str(data_path), combo[0], combo[1], horizon_hours) for combo in combos}
        results = {combo: f.result() for combo, f in futures.items()}

    first = next(iter(results.values()))
    print(f"Periode {first['period']} ({first['days']} dagen), horizon {horizon_hours:g} u, harde spitsblokken "
          f"{first['hard_lockout_hours']} u, starttemperatuur vat {first['t_start_c']} °C")
    for s in scenarios:
        print(f"\nScenario '{s}' (tapverbruik {'1,5 x ' if s == 'heavy' else ''}P50)\n")
        print(f"| Beleid | Kosten € | Na eindvoorraad € | Stroom kWh | €/kWh | Starts | Uren < {COMFORT_REPORT_C} °C | Min °C | Eind °C |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for p in policies:
            r = results[(p, s)]
            print(f"| {p} | {r['cost_eur']:.2f} | {r['cost_adj_eur']:.2f} | {r['kwh_el']:.1f} | {r['eur_per_kwh_el'] or 0:.3f} | "
                  f"{r['starts']} | {r['hours_below_comfort']:.2f} | {r['t_min_c']:.1f} | {r['t_end_c']:.1f} |")
    if json_out:
        json_out.write_text(json.dumps([results[c] for c in combos], indent=1), encoding="utf-8")
        print(f"\nWritten {json_out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Closed-loop DHW policy backtest (ADR-006 evidence)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="fetch prices + telemetry for a period")
    ex.add_argument("--start", required=True, help="first local day, YYYY-MM-DD")
    ex.add_argument("--days", type=int, required=True, help="number of simulated days")
    ex.add_argument("--horizon-days", type=int, default=1, help="look-ahead days added after the period (2 for a 48 h horizon)")
    ex.add_argument("--out", required=True, type=Path)
    rn = sub.add_parser("run", help="simulate policies on an extracted period")
    rn.add_argument("--data", required=True, type=Path)
    rn.add_argument("--policies", default=",".join(POLICIES))
    rn.add_argument("--scenarios", default=",".join(SCENARIOS))
    rn.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 1))
    rn.add_argument("--horizon-hours", type=float, default=DEFAULT_HORIZON_HOURS)
    rn.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    if args.cmd == "extract":
        extract(date.fromisoformat(args.start), args.days, args.out, args.horizon_days)
    else:
        policies = [p.strip() for p in args.policies.split(",") if p.strip()]
        scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        unknown = [p for p in policies if p not in POLICIES] + [s for s in scenarios if s not in SCENARIOS]
        if unknown:
            ap.error(f"unknown policy/scenario: {', '.join(unknown)}")
        try:
            run(args.data, policies, scenarios, args.jobs, args.json_out, args.horizon_hours)
        except ValueError as e:
            ap.error(str(e))


if __name__ == "__main__":
    main()
