"""
Regression tests for docs/reviews/2026-10-09-control-logic-review.md
====================================================================
Each test pins one review finding so it cannot silently come back.
All tests are in-process and offline (no Home Assistant, no network, no /config writes).
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from layer1_data_collection.sanitizer import TelemetrySanitizer
from layer2_calibration.dhw_thermal_model import DhwThermalModel
from layer3_scheduling.central_planner import CentralPlanner
from layer3_scheduling.dhw_baseline import simulate_autonomous
from layer3_scheduling.dhw_optimizer import DhwOptimizerParams, solve
from layer3_scheduling.dhw_specs import DhwTankSpec
from layer3_scheduling.peak_detection import detect_dynamic_price_peaks, hard_lockout_slot_indices
from layer3_scheduling.plan_store import PlanStore
from layer4_control.dhw_run_supervisor import DhwRunSupervisor
from layer4_control.dispatch_guard import resolve_current_slot
from models.canonical import StandardizedState

AMS = ZoneInfo("Europe/Amsterdam")
TAP_MODEL = DhwThermalModel(profile_path="/nonexistent")  # deterministic built-in tap profile


def _winter_slots(start, n=96):
    slots = []
    for i in range(n):
        dt = start + timedelta(minutes=15 * i)
        h = dt.hour + dt.minute / 60
        price = 0.24 + (0.22 if 17 <= h < 20 else 0) + (0.06 if 7 <= h < 9 else 0) - (0.05 if 1 <= h < 5 else 0)
        slots.append(SimpleNamespace(slot_idx=i, dt=dt, label=dt.strftime("%H:%M"), price_all_in=price,
                                     solar_kw=0.0, unallocated_kw=0.4, outdoor_temp_c=3.0))
    return slots


def _peaks(slots):
    items = [{"idx": s.slot_idx, "dt": s.dt, "label": s.label, "price": s.price_all_in,
              "solar": 0.0, "unalloc": 0.4} for s in slots]
    return detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150)


# --------------------------------------------------------------------------- B1
@pytest.mark.parametrize("start_h,t0", [(17, 41.5), (18, 42.0), (16, 42.0)])
def test_dp_never_plans_inside_hard_lockout_with_planner_peak_format(start_h, t0):
    slots = _winter_slots(datetime(2026, 1, 14, start_h, 0, tzinfo=AMS))
    peaks, slot_map = _peaks(slots)
    hard = {k for k, v in slot_map.items() if v.get("is_hard_lockout")}
    assert hard, "scenario must contain a hard lockout"
    assert hard_lockout_slot_indices(peaks, n_slots=len(slots)) == hard
    res = solve(slots=slots, t0_c=t0, dhw_model=TAP_MODEL, params=DhwOptimizerParams(), dynamic_peaks=peaks)
    assert not (set(res.planned_slots) & hard)


def test_in_flight_commitment_never_forces_through_hard_lockout():
    slots = _winter_slots(datetime(2026, 1, 14, 17, 0, tzinfo=AMS))
    peaks, slot_map = _peaks(slots)
    hard = {k for k, v in slot_map.items() if v.get("is_hard_lockout")}
    res = solve(slots=slots, t0_c=44.0, run_state0=("ON_MANDATORY", 1), dhw_model=TAP_MODEL,
                params=DhwOptimizerParams(), dynamic_peaks=peaks, in_flight_slots=4, in_flight_target_c=50.0)
    assert not (set(res.planned_slots) & hard)


# --------------------------------------------------------------------------- B3
def test_baseline_guard_rejects_cheaper_but_comfort_violating_baseline():
    spec, params = DhwTankSpec(), DhwOptimizerParams()
    slots = _winter_slots(datetime(2026, 1, 14, 8, 0, tzinfo=AMS), n=192)
    opt = solve(slots=slots, t0_c=48.0, dhw_model=TAP_MODEL, spec=spec, params=params)
    base = simulate_autonomous(slots=slots, t0_c=48.0, dhw_model=TAP_MODEL, spec=spec, params=params)
    assert base.j_objective_eur < opt.j_objective_eur - 0.005, "scenario: baseline is cheaper"
    assert base.min_temp_c < spec.comfort_min_temp_c, "scenario: baseline breaches comfort"
    assert CentralPlanner._baseline_is_preferable(base, opt, spec, params) is False


def test_baseline_guard_accepts_feasible_cheaper_baseline():
    spec, params = DhwTankSpec(), DhwOptimizerParams()
    base = SimpleNamespace(min_temp_c=45.0, j_objective_eur=0.50)
    opt = SimpleNamespace(j_objective_eur=0.60)
    assert CentralPlanner._baseline_is_preferable(base, opt, spec, params) is True
    assert CentralPlanner._baseline_is_preferable(base, opt, spec, params, in_flight_slots=2) is False


# --------------------------------------------------------------------------- B2 / B5
def _plan_frame(now, dhw_temp, prices):
    raw_prices = [{"dt": (now + timedelta(minutes=15 * i)).isoformat(), "price": p} for i, p in enumerate(prices)]
    return TelemetrySanitizer.sanitize(
        now=now, raw_prices=raw_prices, raw_solar=[], raw_weather=[], raw_unallocated_matrix=[0.30] * 672,
        current_dhw_temp=dhw_temp, last_hardware_reading_time=now, horizon_slots=len(prices), step_mins=15)


def test_planner_slots_carry_run_target_and_consistent_state():
    now = datetime(2026, 1, 14, 16, 0, tzinfo=AMS)
    prices = [s.price_all_in for s in _winter_slots(now)]
    frame = _plan_frame(now, 41.0, prices)
    plan = CentralPlanner.plan(frame, current_dhw_temp=41.0, store=PlanStore(persistence_path=None),
                               battery_context={"installed": False, "simulate": False})
    dhw_slots = [s for s in plan.slots if s.dhw_kw > 0 and s.mode_code in (StandardizedState.FORCED_ON, StandardizedState.MAX_ON)]
    assert dhw_slots, "a 41°C tank in winter must get a run"
    for s in dhw_slots:
        assert s.target_temp_c is not None
        expected = StandardizedState.MAX_ON if s.target_temp_c >= 52.0 else StandardizedState.FORCED_ON
        assert s.mode_code == expected
    assert not any(s.mode_code == StandardizedState.FORCED_OFF and s.dhw_kw > 0 for s in plan.slots)


def test_planner_does_not_plan_dhw_on_unknown_tank_temperature():
    now = datetime(2026, 1, 14, 16, 0, tzinfo=AMS)
    prices = [s.price_all_in for s in _winter_slots(now)]
    frame = _plan_frame(now, None, prices)
    plan = CentralPlanner.plan(frame, current_dhw_temp=None, store=PlanStore(persistence_path=None),
                               battery_context={"installed": False, "simulate": False})
    assert plan.dhw_summary.decision_details["status"] == "SENSOR_UNAVAILABLE"
    assert all(s.dhw_kw == 0.0 for s in plan.slots)


def test_planner_never_writes_in_flight_commitment():
    store = PlanStore(persistence_path=None)
    now = datetime(2026, 1, 14, 16, 0, tzinfo=AMS)
    prices = [s.price_all_in for s in _winter_slots(now)]
    CentralPlanner.plan(_plan_frame(now, 41.0, prices), current_dhw_temp=41.0, store=store,
                        battery_context={"installed": False, "simulate": False})
    assert store.get_in_flight_run() is None


# --------------------------------------------------------------------------- B6 / A4 (sanitizer)
def test_missing_hardware_reading_is_not_fresh():
    now = datetime(2026, 1, 14, 16, 0, tzinfo=AMS)
    frame = TelemetrySanitizer.sanitize(now=now, raw_prices=[], raw_solar=[], raw_weather=[],
                                        raw_unallocated_matrix=[], current_dhw_temp=None,
                                        last_hardware_reading_time=None, horizon_slots=4)
    assert frame.is_fresh is False


def test_sanitizer_grid_is_exact_across_dst_fallback():
    now = datetime(2026, 10, 25, 1, 45, tzinfo=AMS)
    raw_prices = []
    t = now.astimezone(timezone.utc)
    for i in range(16):  # distinct price per absolute quarter, incl. both 02:xx hours
        raw_prices.append({"dt": (t + timedelta(minutes=15 * i)).isoformat(), "price": 0.10 + 0.01 * i})
    frame = TelemetrySanitizer.sanitize(now=now, raw_prices=raw_prices, raw_solar=[], raw_weather=[],
                                        raw_unallocated_matrix=[], current_dhw_temp=50.0,
                                        last_hardware_reading_time=now, horizon_slots=16)
    utc = [s.dt.astimezone(timezone.utc) for s in frame.slots]
    assert all((b - a) == timedelta(minutes=15) for a, b in zip(utc, utc[1:]))
    assert [s.price_all_in for s in frame.slots] == [round(0.10 + 0.01 * i, 4) for i in range(16)]


# --------------------------------------------------------------------------- A4 / A5 (dispatch guard)
def _plan_stub(generated_at, start, n=8, step=15):
    # Step in UTC like the sanitizer does (wall-clock timedelta on a local datetime is the DST bug)
    start_utc = start.astimezone(timezone.utc)
    tz = start.tzinfo
    slots = [SimpleNamespace(dt_iso=(start_utc + timedelta(minutes=step * i)).astimezone(tz).isoformat(),
                             mode_code="normal", time_label=str(i)) for i in range(n)]
    return SimpleNamespace(generated_at=generated_at.isoformat(), resolution_mins=step, slots=slots)


def test_dispatch_guard_selects_slot_by_absolute_time_across_dst():
    gen = datetime(2026, 10, 25, 0, 50, tzinfo=timezone.utc).astimezone(AMS)       # 02:50 CEST
    start = datetime(2026, 10, 25, 0, 45, tzinfo=timezone.utc).astimezone(AMS)     # 02:45 CEST
    plan = _plan_stub(gen, start)
    now = datetime(2026, 10, 25, 1, 5, tzinfo=timezone.utc)                         # 02:05 CET
    slot, reason = resolve_current_slot(plan, now)
    assert reason is None
    assert slot is plan.slots[1]  # 01:00–01:15 UTC


def test_dispatch_guard_rejects_stale_plan():
    gen = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    plan = _plan_stub(gen, gen)
    slot, reason = resolve_current_slot(plan, gen + timedelta(minutes=30))
    assert slot is None and "oud" in reason


# --------------------------------------------------------------------------- A2 (run supervisor)
def test_supervisor_arms_with_slot_target_and_releases_at_target_even_if_plan_still_forced():
    store = PlanStore(persistence_path=None)
    sup = DhwRunSupervisor(store)
    t = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    # DP engine semantics (slot carries the DP target); DHW heating is measured throughout
    kw = {"engine": "dp", "dhw_heating_observed": True}
    d = sup.decide("forced_on", 55.8, 46.0, now=t, planned_run_minutes=60, **kw)
    assert (d.mode, d.target_temp_c, d.in_flight_action) == ("forced_on", 55.8, "armed")
    # Replan shows normal mid-run: commitment continues
    d = sup.decide("normal", None, 50.0, now=t + timedelta(minutes=15), **kw)
    assert (d.mode, d.in_flight_action) == ("forced_on", "continued")
    # Target reached while the plan still shows forced slots: Goldfish -> Elephant baseline
    d = sup.decide("forced_on", 55.8, 55.7, now=t + timedelta(minutes=45), **kw)
    assert (d.mode, d.in_flight_action) == ("normal", "cleared")
    assert store.get_in_flight_run() is None
    # ... and it does not re-arm for the same run
    d = sup.decide("forced_on", 55.8, 55.7, now=t + timedelta(minutes=46), **kw)
    assert d.mode == "normal" and d.in_flight_action == "none"


def test_supervisor_never_forces_dhw_with_unknown_tank_temperature():
    store = PlanStore(persistence_path=None)
    sup = DhwRunSupervisor(store)
    t = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    sup.decide("forced_on", 55.0, 45.0, now=t)
    d = sup.decide("forced_on", 55.0, None, now=t + timedelta(minutes=1))
    assert d.mode == "normal" and d.in_flight_action == "cleared"


def test_supervisor_peak_lockout_ends_commitment():
    store = PlanStore(persistence_path=None)
    sup = DhwRunSupervisor(store)
    t = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    sup.decide("max_on", 58.0, 45.0, now=t)
    d = sup.decide("forced_off", None, 47.0, now=t + timedelta(minutes=15))
    assert d.mode == "forced_off" and d.in_flight_action == "cleared"


def test_in_flight_commitment_expires():
    store = PlanStore(persistence_path=None)
    t = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    store.register_in_flight_run(60.0, "max_on", started_at=t, max_duration_min=90)
    assert store.get_in_flight_run(now=t + timedelta(minutes=89)) is not None
    assert store.get_in_flight_run(now=t + timedelta(minutes=91)) is None


# --------------------------------------------------------------------------- A3 (plan immutability)
def test_published_plan_is_isolated_from_caller_mutation():
    now = datetime(2026, 1, 14, 16, 0, tzinfo=AMS)
    prices = [s.price_all_in for s in _winter_slots(now)]
    store = PlanStore(persistence_path=None)
    plan = CentralPlanner.plan(_plan_frame(now, 45.0, prices), current_dhw_temp=45.0, store=store,
                               battery_context={"installed": False, "simulate": False})
    plan.slots[0].mode_code = StandardizedState.MAX_ON
    plan.slots[0].dhw_kw = 99.0
    assert store.get_plan().slots[0].dhw_kw != 99.0


# --------------------------------------------------------------------------- A1 (planning lock)
def test_ensure_active_plan_runs_at_most_one_planner_concurrently(monkeypatch):
    import api.context as ctx

    store = PlanStore(persistence_path=None)
    store.publish_plan(SimpleNamespace(slots=[], is_fresh=True, dhw_summary=None, dynamic_peaks=[]))
    monkeypatch.setattr(ctx, "get_plan_store", lambda: store)
    monkeypatch.setattr(ctx, "_LAST_PLAN_MONOTONIC", None)

    active, peak = [0], [0]
    lock = threading.Lock()

    def slow_plan(st, horizon_hours):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with lock:
            active[0] -= 1
        return st.get_plan()

    monkeypatch.setattr(ctx, "_compute_and_publish_plan", slow_plan)
    threads = [threading.Thread(target=ctx.ensure_active_canonical_plan) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert peak[0] == 1


# --------------------------------------------------------------------------- A7 (parameter lost updates)
def test_params_store_merge_preserves_other_writers(tmp_path):
    from layer2_calibration.params_store import merge_owned_keys, update_params, read_params
    path = tmp_path / "params.json"
    path.write_text(json.dumps({"building": {"ua_base_w_per_k": 300.0}, "dhw_power": {"p_nom_50": 2.7}}))
    stale_snapshot = read_params(path)                                   # forecaster loads at startup
    update_params(lambda d: d["dhw_power"].update({"p_nom_50": 3.1}), path)  # calibration script writes
    stale_snapshot["building"]["ua_base_w_per_k"] = 312.5                # forecaster retrains
    merge_owned_keys(stale_snapshot, ["building.ua_base_w_per_k"], path)
    final = read_params(path)
    assert final["building"]["ua_base_w_per_k"] == 312.5
    assert final["dhw_power"]["p_nom_50"] == 3.1, "other writer's update must survive"


# --------------------------------------------------------------------------- E1
def test_ols_refuses_collinear_design_instead_of_returning_defaults():
    from layer2_calibration.calibrator import ModelCalibrationEngine
    cal = ModelCalibrationEngine(config_path="/nonexistent", params_path="/nonexistent")
    X = [[dt, dt * 0.1, pv] for dt, pv in zip(range(5, 25), range(20))]
    Y = [7.0 * r[0] for r in X]
    assert cal.solve_ols_3x3(X, Y) is None


# --------------------------------------------------------------------------- A8 (MQTT framing)
def test_mqtt_parser_handles_long_payloads_qos_and_split_chunks():
    from daemon import HemsMqttSubscriberThread as M

    def publish(topic, payload, qos=0):
        t = topic.encode()
        body = bytes([len(t) >> 8, len(t) & 0xFF]) + t + (b"\x00\x07" if qos else b"") + payload
        return bytes([0x30 | (qos << 1)]) + M.encode_remaining_length(len(body)) + body

    long_payload = b"{" + b"x" * 300 + b"}"
    stream = publish("P1P2/R/state", long_payload) + b"\x90\x03\x00\x01\x00" + publish("mbmd/inepro1-102/Power", b"1234.5", qos=1)
    out, rest = M.parse_packets(bytearray(stream[:50]))
    assert out == [] and len(rest) == 50          # incomplete packet stays buffered
    out, rest = M.parse_packets(bytearray(stream))
    assert [t for t, _ in out] == ["P1P2/R/state", "mbmd/inepro1-102/Power"]
    assert out[0][1] == long_payload and out[1][1] == b"1234.5"
    assert rest == bytearray()


# --------------------------------------------------------------------------- Strict Relay-Only Mandate (never touch CV master switch)
def test_actuator_never_reenables_cv_master_switched_off_by_user(monkeypatch):
    import integrations.homeassistant.client as client
    from layer4_control.dispatch_state import PersistentState

    calls = []
    monkeypatch.setattr(client, "call_ha_service", lambda d, s, data: calls.append((d, s, data["entity_id"])) or True)
    state = PersistentState(None)
    states = {"switch.hc_mode_altherma_on": {"state": "off"},
              "input_select.warmtepomp_smart_grid_modus": {"state": "Automatisch"}}
    act = client.make_daikin_ha_actuator(states_map=states, dispatch_state=state)
    act.execute_mode("normal")
    assert ("switch", "turn_on", "switch.hc_mode_altherma_on") not in calls

    # Strict Relay-Only Mandate: Open HEMS must NEVER touch switch.hc_mode_altherma_on in ANY mode
    states = {"switch.hc_mode_altherma_on": {"state": "on"},
              "input_select.warmtepomp_smart_grid_modus": {"state": "Automatisch"}}
    client.make_daikin_ha_actuator(states_map=states, dispatch_state=state).execute_mode("forced_on")
    assert ("switch", "turn_off", "switch.hc_mode_altherma_on") not in calls
    assert ("input_select", "select_option", "input_select.warmtepomp_smart_grid_modus") in calls

    states = {"switch.hc_mode_altherma_on": {"state": "on"},
              "input_select.warmtepomp_smart_grid_modus": {"state": "Geforceerd aan"}}
    client.make_daikin_ha_actuator(states_map=states, dispatch_state=state).execute_mode("forced_off")
    assert ("switch", "turn_off", "switch.hc_mode_altherma_on") not in calls

    states = {"switch.hc_mode_altherma_on": {"state": "on"},
              "input_select.warmtepomp_smart_grid_modus": {"state": "Geforceerd uit"}}
    client.make_daikin_ha_actuator(states_map=states, dispatch_state=state).execute_mode("normal")
    assert ("switch", "turn_on", "switch.hc_mode_altherma_on") not in calls
    assert ("switch", "turn_off", "switch.hc_mode_altherma_on") not in calls


def test_in_flight_hard_lockout_does_not_self_cancel_after_one_minute():
    """Verify an active hard lockout at slot 0 is not cancelled by last_hard_end_slot=-1 on subsequent ticks."""
    slots = _winter_slots(datetime(2026, 10, 16, 18, 15, tzinfo=AMS), n=96)
    items = [{"idx": s.slot_idx, "dt": s.dt, "label": s.label, "price": s.price_all_in,
              "solar": 0.0, "unalloc": 0.4} for s in slots]

    # Tick 0 (start of lockout): past_continuous_lockout_mins = 0
    _, map_t0 = detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150,
                                           past_continuous_lockout_mins=0, mins_since_last_lockout=999)
    assert map_t0[0]["is_hard_lockout"] is True

    # Tick 0.5 (<60s into lockout, even if caller passes 0,0 or 1,0): must never self-cancel
    _, map_t05 = detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150,
                                            past_continuous_lockout_mins=0, mins_since_last_lockout=0)
    assert map_t05[0]["is_hard_lockout"] is True

    # Tick 1 (1 minute into lockout): past_continuous_lockout_mins = 1, mins_since_last_lockout = 0
    _, map_t1 = detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150,
                                           past_continuous_lockout_mins=1, mins_since_last_lockout=0)
    assert map_t1[0]["is_hard_lockout"] is True

    # Tick 60 (60 minutes into lockout): still hard-locked at slot 0
    _, map_t60 = detect_dynamic_price_peaks(items, step_mins=15, max_lockout_mins=150,
                                            past_continuous_lockout_mins=60, mins_since_last_lockout=0)
    assert map_t60[0]["is_hard_lockout"] is True

