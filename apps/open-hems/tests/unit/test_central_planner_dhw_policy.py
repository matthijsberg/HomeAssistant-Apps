"""
CentralPlanner integration of the Daikin-first DHW policy (ADR-006, WP2 of PLAN-dhw-daikin-first).
"""

from datetime import datetime, timezone

from models.canonical import StandardizedState
from layer3_scheduling.central_planner import CentralPlanner
from layer3_scheduling.plan_store import PlanStore
from tests.unit.test_replay_harness import _load_and_plan_fixture

UI_KEYS = ("status", "badge_html", "box_title", "explanation", "trajectory", "unheated_trajectory",
           "comfort_boundary_c", "morning_dip_c", "morning_dip_time", "dynamic_peaks", "planner")
FORCED = (StandardizedState.FORCED_ON, StandardizedState.MAX_ON)


def _plan(fixture: str, engine: str, store=None, tank_c=None):
    data, frame, _ = _load_and_plan_fixture(fixture)
    t0 = data["dhw_tank_temp_c"] if tank_c is None else tank_c
    return CentralPlanner.plan(frame, current_dhw_temp=t0, store=store or PlanStore(), dhw_engine=engine)


def _hard_indices(plan):
    return {i for i, s in enumerate(plan.slots) if s.mode_code == StandardizedState.FORCED_OFF}


def test_daikin_first_engine_produces_ui_compatible_summary():
    plan = _plan("golden_winter_sunny_peak.json", "daikin_first")
    details = plan.dhw_summary.decision_details
    assert details["planner"] == "daikin_first"
    assert plan.metadata["dhw_engine"] == "daikin_first"
    for key in UI_KEYS:
        assert key in details, key
    n = len(plan.slots)
    assert len(details["trajectory"]["temperatures_c"]) == n + 1
    assert len(details["unheated_trajectory"]["temperatures_c"]) == n + 1


def test_dp_engine_remains_available_as_fallback():
    plan = _plan("golden_winter_sunny_peak.json", "dp")
    assert plan.dhw_summary.decision_details["planner"] == "optimizer"
    assert plan.metadata["dhw_engine"] == "dp"


def test_unknown_engine_falls_back_to_daikin_first():
    plan = _plan("golden_shoulder_season.json", "something_else")
    assert plan.metadata["dhw_engine"] == "daikin_first"


def test_forced_slots_only_carry_50_or_60_and_never_sit_in_a_lockout():
    for fixture in ("day_2026_09_12_recorded.json", "golden_winter_sunny_peak.json", "golden_winter_dunkelflaute.json",
                    "golden_summer_solar_heavy.json", "golden_shoulder_season.json"):
        plan = _plan(fixture, "daikin_first")
        hard = _hard_indices(plan)
        for i, s in enumerate(plan.slots):
            if s.mode_code in FORCED:
                assert s.target_temp_c in (50.0, 60.0), (fixture, i, s.target_temp_c)
                assert i not in hard
                assert (s.mode_code == StandardizedState.MAX_ON) == (s.target_temp_c == 60.0)
            if i in hard:
                assert s.dhw_kw == 0.0


def test_daikin_own_run_is_normal_mode_with_dhw_power_and_paused_floor_heating():
    # Vriesmist: the tank is at 40.5 °C; Open HEMS does not intervene, the Daikin heats by itself
    plan = _plan("golden_winter_defrost_humid.json", "daikin_first")
    own = [s for s in plan.slots if s.dhw_kw > 0 and s.mode_code == StandardizedState.NORMAL]
    assert own, "the Daikin's own run must be visible in the plan"
    assert all(s.heating_kw == 0.0 for s in own)
    assert plan.dhw_summary.planned_mode == "normal"


def test_preheat_before_evening_peak_in_dunkelflaute():
    plan = _plan("golden_winter_dunkelflaute.json", "daikin_first")
    hard = sorted(_hard_indices(plan))
    forced = [i for i, s in enumerate(plan.slots) if s.mode_code == StandardizedState.FORCED_ON]
    assert forced, "a pre-heat must be planned"
    peak_start = next(i for i in hard if i > forced[0])     # the evening peak the pre-heat is for
    assert max(forced) < peak_start
    assert peak_start - forced[0] <= 24                      # started within 6 h before the peak
    assert plan.dhw_summary.target_temp_c == 50.0


def test_in_flight_run_is_read_as_starting_state():
    store = PlanStore()
    store.register_in_flight_run(target_temp_c=60.0, mode="max_on", started_at=datetime.now(timezone.utc),
                                 max_duration_min=120, source="test")
    plan = _plan("golden_shoulder_season.json", "daikin_first", store=store, tank_c=52.0)
    first = plan.slots[0]
    if first.mode_code != StandardizedState.FORCED_OFF:
        assert first.mode_code == StandardizedState.MAX_ON
        assert first.target_temp_c == 60.0
