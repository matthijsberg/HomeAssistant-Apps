"""
Layer 4 DHW run supervisor under ADR-006 (WP3 of docs/plans/PLAN-dhw-daikin-first.md):
targets 50/60 °C only, no re-arm to plan targets, 50 → 60 °C upgrade, SG4-without-effect release.
"""

from datetime import datetime, timedelta, timezone

from layer3_scheduling.plan_store import PlanStore
from layer4_control.dhw_run_supervisor import DhwRunSupervisor

T0 = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
HEAT = {"dhw_heating_observed": True}


def _sup():
    store = PlanStore(persistence_path=None)
    return store, DhwRunSupervisor(store)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_mode_decides_the_target_not_the_slot():
    _, sup = _sup()
    d = sup.decide("forced_on", 55.8, 45.0, now=T0, **HEAT)
    assert (d.mode, d.target_temp_c, d.in_flight_action) == ("forced_on", 50.0, "armed")
    _, sup = _sup()
    d = sup.decide("max_on", 52.3, 45.0, now=T0, **HEAT)
    assert (d.mode, d.target_temp_c, d.in_flight_action) == ("max_on", 60.0, "armed")


def test_no_rearm_to_a_higher_plan_target_after_reaching_the_target():
    # The 2026-10-10 creep: armed at 59.3 °C, re-armed at 59.9 °C. Under Daikin-first the target is 60 °C
    # and a reached target is released, whatever the slot says.
    store, sup = _sup()
    sup.decide("max_on", 59.3, 50.0, now=T0, **HEAT)
    d = sup.decide("max_on", 59.9, 59.85, now=at(40), **HEAT)
    assert (d.mode, d.in_flight_action) == ("normal", "cleared")
    assert store.get_in_flight_run() is None
    d = sup.decide("max_on", 59.9, 59.85, now=at(41), **HEAT)
    assert d.mode == "normal" and d.in_flight_action == "none"


def test_50c_run_is_released_at_50_even_if_slot_says_more():
    store, sup = _sup()
    sup.decide("forced_on", 52.0, 45.0, now=T0, **HEAT)
    d = sup.decide("forced_on", 52.0, 49.85, now=at(20), **HEAT)
    assert (d.mode, d.in_flight_action) == ("normal", "cleared")


def test_running_50c_run_is_upgraded_to_60c_when_plan_says_max_on():
    store, sup = _sup()
    sup.decide("forced_on", 50.0, 45.0, now=T0, **HEAT)
    started = store.get_in_flight_run(now=at(1))["started_at"]
    d = sup.decide("max_on", 60.0, 48.0, now=at(10), **HEAT)
    assert (d.mode, d.target_temp_c, d.in_flight_action) == ("max_on", 60.0, "upgraded")
    run = store.get_in_flight_run(now=at(11))
    assert run["target_temp_c"] == 60.0
    assert run["started_at"] == started          # effect timing keeps running from the original start
    d = sup.decide("max_on", 60.0, 52.0, now=at(20), **HEAT)
    assert (d.mode, d.in_flight_action) == ("max_on", "continued")


def test_sg4_without_dhw_heating_is_released_and_cools_down():
    store, sup = _sup()
    d = sup.decide("max_on", 60.0, 45.0, now=T0, dhw_heating_observed=False)
    assert d.in_flight_action == "armed"
    d = sup.decide("max_on", 60.0, 44.9, now=at(9), dhw_heating_observed=False)
    assert d.in_flight_action == "continued"
    d = sup.decide("max_on", 60.0, 44.8, now=at(10), dhw_heating_observed=False)
    assert (d.mode, d.in_flight_action) == ("normal", "released_no_effect")
    assert "centrale verwarming hersteld" in (d.reason or "")
    assert store.get_in_flight_run() is None
    # The plan still asks for SG4: no new run during the cooldown
    d = sup.decide("max_on", 60.0, 44.5, now=at(30), dhw_heating_observed=False)
    assert (d.mode, d.in_flight_action) == ("normal", "cooldown")
    # After the cooldown a new run may be armed
    d = sup.decide("max_on", 60.0, 43.0, now=at(71), dhw_heating_observed=False)
    assert d.in_flight_action == "armed"


def test_heating_seen_once_keeps_the_run_alive():
    _, sup = _sup()
    sup.decide("forced_on", 50.0, 42.0, now=T0, dhw_heating_observed=False)
    sup.decide("forced_on", 50.0, 42.5, now=at(5), dhw_heating_observed=True)
    d = sup.decide("forced_on", 50.0, 47.0, now=at(25), dhw_heating_observed=False)
    assert (d.mode, d.in_flight_action) == ("forced_on", "continued")


def test_mid_run_stall_or_valve_diversion_releases_sg4_after_timeout():
    """
    Regression test for 2026-10-27 06:20-07:30: if DHW heating starts normally, then mid-run the compressor
    stops at ~57.8 °C or the 3-way valve switches to space heating (dhw_heating_observed=False) for >= 10 minutes,
    DhwRunSupervisor must release SG4 instead of holding 'Geforceerd aan' indefinitely.
    """
    store, sup = _sup()
    sup.decide("max_on", 60.0, 44.0, now=T0, dhw_heating_observed=True)
    # At t=30m, tank reaches 57.8 °C and Daikin switches 3-way valve off DHW (dhw_heating_observed=False)
    d1 = sup.decide("max_on", 60.0, 57.8, now=at(30), dhw_heating_observed=False)
    assert (d1.mode, d1.in_flight_action) == ("max_on", "continued")
    # 9 minutes after stopping: still within 10-min grace window
    d2 = sup.decide("max_on", 60.0, 57.5, now=at(39), dhw_heating_observed=False)
    assert (d2.mode, d2.in_flight_action) == ("max_on", "continued")
    # 10 minutes without DHW heating: release SG4 back to normal
    d3 = sup.decide("max_on", 60.0, 57.4, now=at(40), dhw_heating_observed=False)
    assert (d3.mode, d3.in_flight_action) == ("normal", "released_no_effect")
    assert store.get_in_flight_run() is None


def test_unmeasured_heating_counts_as_no_effect():
    # No power/valve telemetry: SG4 with the CV master off is never held blind beyond the timeout
    _, sup = _sup()
    sup.decide("max_on", 60.0, 45.0, now=T0, dhw_heating_observed=None)
    d = sup.decide("max_on", 60.0, 45.0, now=at(10), dhw_heating_observed=None)
    assert d.in_flight_action == "released_no_effect"


def test_peak_lockout_and_unknown_tank_still_win():
    store, sup = _sup()
    sup.decide("max_on", 60.0, 45.0, now=T0, **HEAT)
    d = sup.decide("forced_off", None, 47.0, now=at(5), **HEAT)
    assert (d.mode, d.in_flight_action) == ("forced_off", "cleared")
    sup.decide("forced_on", 50.0, 45.0, now=at(30), **HEAT)
    d = sup.decide("forced_on", 50.0, None, now=at(31), **HEAT)
    assert (d.mode, d.in_flight_action) == ("normal", "cleared")


def test_dp_engine_keeps_legacy_rearm_until_wp5():
    _, sup = _sup()
    sup.decide("forced_on", 52.0, 45.0, now=T0, engine="dp", **HEAT)
    d = sup.decide("max_on", 58.0, 51.9, now=at(30), engine="dp", **HEAT)
    assert (d.mode, d.target_temp_c, d.in_flight_action) == ("max_on", 58.0, "rearmed")


def test_from_config_reads_and_bounds_safety_net_settings():
    store = PlanStore(persistence_path=None)
    sup = DhwRunSupervisor.from_config(store, {"dhw_policy": {"sg4_no_effect_timeout_min": 1, "sg4_no_effect_cooldown_min": "x"}})
    assert sup.no_effect_timeout_min == 3.0
    assert sup.no_effect_cooldown_min == 60.0
    assert DhwRunSupervisor.from_config(store, None).no_effect_timeout_min == 10.0
