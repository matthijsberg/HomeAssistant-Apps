"""
Unit tests for layer3_scheduling/dhw_policy.py (ADR-006 Daikin-first DHW policy).

Scenario conventions: outdoor 10 °C (COP 2.35 for a run to 50 °C, 1.65 for a run to 60 °C), no solar unless
stated, calibrated-style COP/power parameters, constant tap demand unless stated.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from zoneinfo import ZoneInfo

import pytest

from layer3_scheduling.dhw_policy import (
    DhwPolicyParams,
    MODE_FORCED_OFF,
    MODE_FORCED_ON,
    MODE_MAX_ON,
    MODE_NORMAL,
    plan_dhw,
)
from layer3_scheduling.dhw_specs import DhwTankSpec

AMS = ZoneInfo("Europe/Amsterdam")
MP = {
    "dhw_cop": {"cop_50": 2.0, "k_t": 0.07, "k_out": 0.05, "cop_min": 1.4, "cop_max": 3.2},
    "dhw_power": {"p_nom_50": 2.72, "k_t_tank": 0.074, "k_out": 0.057, "p_min_kw": 1.6, "p_max_kw": 3.5},
}


@dataclass
class Slot:
    dt: datetime
    label: str
    price_all_in: float
    solar_kw: float = 0.0
    unallocated_kw: float = 0.3
    outdoor_temp_c: float = 10.0


class TapModel:
    """Test double for DhwThermalModel: tap demand per quarter of the day."""

    def __init__(self, default_kwh: float = 0.05, per_quarter: Optional[Dict[int, float]] = None):
        self.default_kwh = default_kwh
        self.per_quarter = per_quarter or {}

    def get_learned_tap_kwh_th(self, dow: int, quarter_idx: int) -> float:
        return self.per_quarter.get(quarter_idx, self.default_kwh)

    def get_tank_ua(self) -> float:
        return 2.38


def make_slots(prices, start_hour: int = 8, n: int = 96, solar=None):
    t0 = datetime(2026, 1, 14, start_hour, 0, tzinfo=AMS)
    out = []
    for k in range(n):
        dt = t0 + timedelta(minutes=15 * k)
        out.append(Slot(dt=dt, label=dt.strftime("%H:%M"), price_all_in=prices(k),
                        solar_kw=solar(k) if solar else 0.0))
    return out


def run_plan(slots, t0_c, hard: Optional[Set[int]] = None, tap: Optional[TapModel] = None, **kw):
    return plan_dhw(slots=slots, t0_c=t0_c, hard_slots=hard or set(), dhw_model=tap or TapModel(),
                    spec=DhwTankSpec(), model_parameters=MP, **kw)


def assert_only_two_targets(res):
    assert {t for t in res.slot_targets if t is not None} <= {48.0, 50.0, 55.0, 60.0}


# ---------------------------------------------------------------------------------------------

def test_hard_lockout_is_forced_off_even_with_in_flight_run():
    slots = make_slots(lambda k: 0.25)
    res = run_plan(slots, 52.0, hard={0, 1}, in_flight_target_c=60.0)
    assert res.slot_modes[0] == MODE_FORCED_OFF
    assert res.slot_modes[1] == MODE_FORCED_OFF
    assert_only_two_targets(res)


def _peak_tap() -> TapModel:
    # Little tapping until 17:00, heavy showers during the evening peak (17:00–19:30)
    return TapModel(default_kwh=0.02, per_quarter={q: 0.30 for q in range(17 * 4, 19 * 4 + 2)})


def test_preheat_starts_at_cheapest_quarter_in_window_and_finishes_before_peak():
    # Start 12:00; peak lockout 17:00–19:30 (slots 20..29); 14:00–15:00 (slots 8..11) is cheapest
    slots = make_slots(lambda k: 0.20 if 8 <= k < 12 else 0.25, start_hour=12)
    peak = set(range(20, 30))
    res = run_plan(slots, 44.0, hard=peak, tap=_peak_tap())
    forced = res.forced_slots
    assert forced, "a pre-heat must be planned"
    first_run = res.runs[0]
    assert first_run.kind == "preheat"
    assert first_run.start_idx == 8
    assert first_run.end_idx <= 20
    assert first_run.target_temp_c == 55.0
    assert res.slot_modes[8] == MODE_FORCED_ON
    assert all(res.slot_modes[k] == MODE_FORCED_OFF for k in peak)
    assert_only_two_targets(res)


def test_preheat_goes_to_60_when_electricity_is_free_at_the_chosen_start():
    slots = make_slots(lambda k: -0.02 if 8 <= k < 12 else 0.25, start_hour=12)
    res = run_plan(slots, 44.0, hard=set(range(20, 30)), tap=_peak_tap())
    assert res.slot_modes[8] == MODE_MAX_ON
    assert res.slot_targets[8] == 60.0


def test_free_electricity_boosts_to_60_immediately():
    slots = make_slots(lambda k: -0.02 if k < 4 else 0.30)
    res = run_plan(slots, 50.0)
    assert res.slot_modes[0] == MODE_MAX_ON
    assert res.slot_targets[0] == 60.0
    assert res.runs[0].kind == "boost_free"


def test_free_solar_surplus_counts_as_free():
    # 5 kW solar on 0.3 kW base load with a low all-in price: exporting is worth less than nothing
    slots = make_slots(lambda k: 0.10 if k < 8 else 0.30, solar=lambda k: 5.0 if k < 8 else 0.0)
    res = run_plan(slots, 50.0)
    assert res.slot_modes[0] == MODE_MAX_ON


@pytest.mark.parametrize("price_now, t0_c, expected_mode", [
    (0.18, 45.0, MODE_MAX_ON),     # 40 % cheaper: worth heating to 60 °C despite the lower COP
    (0.24, 45.0, MODE_FORCED_ON),  # 20 % cheaper: advance to 50 °C, a boost would cost more than at X
    (0.285, 45.0, MODE_NORMAL),    # 5 % cheaper: below the 10 % advance margin
    (0.24, 48.0, MODE_NORMAL),     # tank above 47 °C: no short advance runs
])
def test_heat_price_decides_between_boost_advance_and_nothing(price_now, t0_c, expected_mode):
    # Cheap window 08:00–10:00 (8 quarters); the Daikin would start by itself later at 0.30
    slots = make_slots(lambda k: price_now if k < 8 else 0.30)
    res = run_plan(slots, t0_c)
    assert res.slot_modes[0] == expected_mode
    if expected_mode == MODE_FORCED_ON:
        assert res.slot_targets[0] == 50.0
        assert res.runs[0].kind == "advance"
    assert_only_two_targets(res)


def test_boost_uses_the_cheapest_quarters_not_the_first_cheap_one():
    # 08:00–09:00 cheap, 09:00–11:00 cheaper, the rest expensive
    slots = make_slots(lambda k: 0.20 if k < 4 else (0.10 if k < 12 else 0.40))
    res = run_plan(slots, 45.0)
    assert res.slot_modes[:4] == [MODE_NORMAL] * 4
    assert res.slot_modes[4] == MODE_MAX_ON


def test_boost_stops_when_the_cheap_window_closes():
    slots = make_slots(lambda k: 0.10 if k < 2 else 0.40)
    res = run_plan(slots, 45.0)
    assert res.slot_modes[0] == MODE_MAX_ON
    assert res.slot_modes[2] == MODE_NORMAL
    assert max(res.trajectory["temperatures_c"][:4]) < 59.0


def test_no_intervention_when_the_daikin_does_not_need_to_heat_within_the_horizon():
    slots = make_slots(lambda k: 0.15 if k % 8 == 0 else 0.30, n=32)
    res = run_plan(slots, 55.0, tap=TapModel(default_kwh=0.01))
    assert res.forced_slots == []
    assert res.first_autonomous_start_idx is None


def test_no_boost_on_a_nearly_full_tank_even_when_free():
    slots = make_slots(lambda k: -0.02 if k < 4 else 0.30)
    res = run_plan(slots, 57.5)
    assert res.slot_modes[0] == MODE_NORMAL


def test_in_flight_run_is_finished_to_its_target():
    slots = make_slots(lambda k: 0.40)
    res = run_plan(slots, 52.0, in_flight_target_c=60.0)
    assert res.slot_modes[0] == MODE_MAX_ON
    assert res.slot_targets[0] == 60.0


def test_daikin_runs_by_itself_when_heat_is_not_cheaper():
    # Flat prices: Open HEMS does nothing, the Daikin's own run shows up as autonomous slots
    slots = make_slots(lambda k: 0.25)
    res = run_plan(slots, 42.0)
    assert res.forced_slots == []
    assert res.autonomous_slots, "the Daikin's own run must be visible in the plan"
    assert res.slot_dhw_kw[res.autonomous_slots[0]] > 0.0
    assert min(res.trajectory["temperatures_c"]) > 39.0


def test_params_from_config_bounds_and_switches():
    p = DhwPolicyParams.from_config({"dhw_policy": {"advance_margin": None, "preheat_window_hours": 99, "boost_max_start_temp_c": "x"}})
    assert p.advance_margin is None
    assert p.preheat_window_hours == 12.0
    assert p.boost_max_start_temp_c == 57.0
    assert p.preheat_window_slots == 48
    assert DhwPolicyParams.from_config(None) == DhwPolicyParams()


def test_trajectory_and_band_cover_the_horizon():
    slots = make_slots(lambda k: 0.25)
    res = run_plan(slots, 46.0)
    n = len(slots)
    for key in ("temperatures_c", "temperatures_p05_c", "temperatures_p95_c"):
        assert len(res.trajectory[key]) == n + 1
    assert len(res.autonomous_trajectory) == n + 1
    # Before any reheat, heavy tapping (P95) leaves the tank colder than light tapping (P05). Once the P95 tank
    # reaches 40 °C the Daikin's own thermostat reheats it, so the band may cross later; check the first 5 hours.
    p95, p05 = res.trajectory["temperatures_p95_c"], res.trajectory["temperatures_p05_c"]
    assert min(p95[:21]) > 40.0
    assert all(p95[k] <= p05[k] + 1e-6 for k in range(21))


def test_in_flight_50c_run_upgrades_seamlessly_to_60c_without_stopping_relay_when_solar_boost_pays():
    """
    When a 50 °C run is in flight (or starting before a peak) and midday solar makes continuing on the
    SG4 relay to 60 °C cheaper than the next autonomous Daikin run, DhwPolicy returns MODE_MAX_ON (60 °C)
    immediately so DhwRunSupervisor holds 'Geforceerd aan' continuously without dropping at 50 °C.
    """
    slots = make_slots(lambda k: 0.24 if k < 8 else 0.35, solar=lambda k: 3.5 if k < 8 else 0.0, start_hour=12)
    res = run_plan(slots, 49.2, hard=set(range(24, 34)), tap=_peak_tap(), in_flight_target_c=50.0)
    assert res.slot_modes[0] == MODE_MAX_ON
    assert res.slot_targets[0] == 60.0


def test_early_morning_50c_run_does_not_upgrade_to_60c_when_midday_solar_is_cheaper():
    """
    Regression test for 2026-10-27 05:15: an early-morning run to 50 °C bridges the morning peak (08:00-10:00),
    after which midday slots (11:00-14:00) have cheaper electricity + solar. The 05:15 run must remain at 50 °C
    (MODE_FORCED_ON) and must NOT upgrade itself to 60 °C (MODE_MAX_ON) when in_flight_target_c=50.0.
    """
    def price_fn(k):
        # start_hour=5: k=0..7 (05:00-07:00) €0.19, k=12..19 (08:00-10:00) €0.35 morning peak,
        # k=24..35 (11:00-14:00) €0.15 midday valley + solar, k=48..60 (17:00-20:00) €0.39 evening peak
        if 12 <= k < 20:
            return 0.35
        if 24 <= k < 36:
            return 0.15
        if 48 <= k < 60:
            return 0.39
        return 0.19

    slots = make_slots(price_fn, solar=lambda k: 2.5 if 24 <= k < 36 else 0.0, start_hour=5)
    res = run_plan(slots, 43.4, hard=set(range(12, 20)) | set(range(48, 60)), tap=_peak_tap(), in_flight_target_c=50.0)
    assert res.slot_modes[0] == MODE_FORCED_ON
    assert res.slot_targets[0] == 50.0


