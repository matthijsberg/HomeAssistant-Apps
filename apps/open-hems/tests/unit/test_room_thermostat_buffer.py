"""
Tests for Room Thermostat Floor Buffer Controller
=================================================
Verifies:
1. +1.0°C elevation above current room temperature.
2. Rate-limiting: max 2 changes/hour (1 up, 1 down).
3. Rate-limiting: max 6 changes/24h (3 complete cycles).
4. Minimum run duration: 45 minutes hold time before de-actuation.
5. Watchdog reset: lingering elevated setpoint restored to baseline.
"""

import pytest
from datetime import datetime, timedelta, timezone
from layer4_control.room_thermostat_buffer import RoomThermostatBufferController


def test_elevation_and_baseline_capture():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    # Current room temp 21.2°C, baseline 20.5°C -> target should be 22.2°C (+1.0°C)
    target = ctrl.request_preheat(current_room_temp_c=21.2, current_setpoint_c=20.5, now=t0)
    assert target == 22.2
    assert ctrl.is_buffering is True
    assert ctrl.baseline_temp_c == 20.5


def test_minimum_run_duration_45m():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.0)
    t0 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    target = ctrl.request_preheat(current_room_temp_c=19.5, current_setpoint_c=20.0, now=t0)
    assert target == 21.0

    # Try release after 20 minutes -> should be blocked (< 45 mins)
    t_early = t0 + timedelta(minutes=20)
    res_early = ctrl.request_release(now=t_early)
    assert res_early is None
    assert ctrl.is_buffering is True

    # Try release after 50 minutes -> allowed, returns baseline 20.0°C
    t_ok = t0 + timedelta(minutes=50)
    res_ok = ctrl.request_release(now=t_ok)
    assert res_ok == 20.0
    assert ctrl.is_buffering is False


def test_rate_limit_max_2_per_hour():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.0)
    t0 = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)

    # Change 1 (UP)
    assert ctrl.request_preheat(current_room_temp_c=20.0, current_setpoint_c=20.0, now=t0) == 21.0
    # Change 2 (DOWN at t0 + 50m)
    t1 = t0 + timedelta(minutes=50)
    assert ctrl.request_release(now=t1) == 20.0

    # Attempt Change 3 (UP again at t0 + 55m, which is within the 1-hour rolling window from t0)
    t2 = t0 + timedelta(minutes=55)
    assert ctrl.request_preheat(current_room_temp_c=20.0, current_setpoint_c=20.0, now=t2) is None

    # At t0 + 65m, the first change (t0) is older than 1 hour -> allowed again
    t3 = t0 + timedelta(minutes=65)
    assert ctrl.request_preheat(current_room_temp_c=20.0, current_setpoint_c=20.0, now=t3) == 21.0


def test_rate_limit_max_6_per_24h():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.0)
    base_t = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)

    # 3 full cycles spaced across 6 hours:
    # Cycle 1: up at 0h, down at 1h (2 changes)
    assert ctrl.request_preheat(20.0, 20.0, now=base_t + timedelta(hours=0)) == 21.0
    assert ctrl.request_release(now=base_t + timedelta(hours=1)) == 20.0

    # Cycle 2: up at 2h, down at 3h (4 changes)
    assert ctrl.request_preheat(20.0, 20.0, now=base_t + timedelta(hours=2)) == 21.0
    assert ctrl.request_release(now=base_t + timedelta(hours=3)) == 20.0

    # Cycle 3: up at 4h, down at 5h (6 changes)
    assert ctrl.request_preheat(20.0, 20.0, now=base_t + timedelta(hours=4)) == 21.0
    assert ctrl.request_release(now=base_t + timedelta(hours=5)) == 20.0

    # Attempt Cycle 4: up at 6h -> should be blocked (6 changes in 24h)
    assert ctrl.request_preheat(20.0, 20.0, now=base_t + timedelta(hours=6)) is None


def test_watchdog_restores_our_lingering_elevation():
    """Our own pre-heat value still present while idle (e.g. restore write failed) is restored."""
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
    elevated = ctrl.request_preheat(current_room_temp_c=20.4, current_setpoint_c=20.5, now=t0)
    assert elevated == 21.5
    t1 = t0 + timedelta(minutes=50)
    assert ctrl.request_release(now=t1) == 20.5        # restore issued ...
    t2 = t1 + timedelta(minutes=5)
    # ... but HA still reports our elevated value -> watchdog restores baseline
    assert ctrl.watchdog_check(current_setpoint_c=21.5, now=t2) == 20.5


def test_watchdog_never_overrides_user_setpoint():
    """A setpoint chosen by the user is adopted as baseline, never reverted (review finding C1)."""
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
    assert ctrl.is_buffering is False
    assert ctrl.watchdog_check(current_setpoint_c=21.5, now=t0) is None
    assert ctrl.baseline_temp_c == 21.5
    # A later pre-heat elevates relative to the user's baseline
    assert ctrl.request_preheat(current_room_temp_c=21.0, current_setpoint_c=21.5, now=t0) == 22.5


def test_user_takeover_during_preheat_is_respected():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.0)
    t0 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    assert ctrl.request_preheat(current_room_temp_c=19.5, current_setpoint_c=20.0, now=t0) == 21.0
    # User sets 19.0 while we are buffering -> stop buffering, adopt 19.0, write nothing
    t1 = t0 + timedelta(minutes=30)
    assert ctrl.watchdog_check(current_setpoint_c=19.0, now=t1) is None
    assert ctrl.is_buffering is False
    assert ctrl.baseline_temp_c == 19.0
    assert ctrl.request_release(now=t1 + timedelta(hours=1)) is None


def test_release_never_blocked_by_change_budget():
    """Budget exhaustion must never strand an elevated setpoint (review finding C2)."""
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    now = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    for _ in range(2):
        ctrl.request_preheat(20.0, 20.5, now=now)
        now += timedelta(hours=1)
        ctrl.request_release(now=now)
        now += timedelta(hours=1)
    assert ctrl.request_preheat(20.0, 20.5, now=now) == 21.5   # 5th change
    now += timedelta(hours=1)
    ctrl.request_release(now=now)                               # 6th change
    now += timedelta(hours=1)
    assert ctrl.request_preheat(20.0, 20.5, now=now) is None    # elevation budget exhausted
    # but a release after an elevation is always possible
    ctrl2 = RoomThermostatBufferController(default_baseline_c=20.5)
    t = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    ctrl2.change_history = [t - timedelta(minutes=m) for m in (10, 20, 30, 40, 50)]
    assert ctrl2.request_preheat(20.0, 20.5, now=t) is None     # hourly limit
    ctrl2.change_history = [t - timedelta(hours=h) for h in (2, 4, 6, 8, 10)]
    assert ctrl2.request_preheat(20.0, 20.5, now=t) == 21.5     # 6th change in 24h
    assert ctrl2.request_release(now=t + timedelta(minutes=50)) == 20.5


def test_state_survives_restart_without_ratchet(tmp_path):
    from layer4_control.dispatch_state import PersistentState
    state = PersistentState(tmp_path / "state.json")
    t0 = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5, state=state)
    assert ctrl.request_preheat(20.4, 20.5, now=t0) == 21.5
    # Restart: new controller instance with the same persisted state
    ctrl2 = RoomThermostatBufferController(default_baseline_c=20.5, state=PersistentState(tmp_path / "state.json"))
    assert ctrl2.is_buffering is True
    assert ctrl2.baseline_temp_c == 20.5
    assert ctrl2.request_release(now=t0 + timedelta(minutes=50)) == 20.5


def test_vacation_mode_14c_preheat_and_ceiling():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    # Thermostat at 14.0°C (vacation), room at 14.2°C -> preheats to 15.2°C, restores to 14.0°C
    assert ctrl.request_preheat(current_room_temp_c=14.2, current_setpoint_c=14.0, now=t0) == 15.2
    assert ctrl.baseline_temp_c == 14.0
    assert ctrl.request_release(now=t0 + timedelta(minutes=50)) == 14.0
    # Room at 16.0°C with 14.0°C setpoint -> preheats to 17.0°C (baseline + 3.0°C ceiling)
    t1 = t0 + timedelta(hours=3)
    assert ctrl.request_preheat(current_room_temp_c=16.0, current_setpoint_c=14.0, now=t1) == 17.0
    assert ctrl.request_release(now=t1 + timedelta(minutes=50)) == 14.0
    # Room still warm (18.0°C) when vacation starts -> no preheat above 17.0°C ceiling
    t2 = t1 + timedelta(hours=3)
    assert ctrl.request_preheat(current_room_temp_c=18.0, current_setpoint_c=14.0, now=t2) is None


def test_winter_solar_spike_ceiling_and_write_budget_guard():
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 1, 22, 12, 0, tzinfo=timezone.utc)
    # Write budget < 3 blocks preheat so baseline restoration is never jeopardized
    assert ctrl.request_preheat(22.0, 20.5, now=t0, write_budget=2.0) is None
    assert ctrl.is_buffering is False
    # Floor already saturated (>= 26.5°C) blocks preheat
    assert ctrl.request_preheat(22.0, 20.5, now=t0, write_budget=50.0, current_floor_temp_c=26.8) is None
    # Sunny winter midday: room air at 22.2°C, cold floor (20.5°C), healthy write budget (50) -> elevates to 23.2°C (<= 23.5°C)
    assert ctrl.request_preheat(22.2, 20.5, now=t0, write_budget=50.0, current_floor_temp_c=20.5) == 23.2
    assert ctrl.request_release(now=t0 + timedelta(minutes=50)) == 20.5


def test_resolve_effective_baseline_idle_and_buffering_and_override():
    """Verifies that Open HEMS resolves true baseline during buffering and adopts user overrides."""
    ctrl = RoomThermostatBufferController(default_baseline_c=20.0)
    t0 = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)

    # 1. Idle state: thermostat at 20.0°C -> baseline is 20.0°C, is_buffering is False
    base_sp, is_buf = ctrl.resolve_effective_baseline(20.0, now=t0)
    assert base_sp == 20.0
    assert is_buf is False

    # 2. User manually adjusts thermostat to 19.5°C while idle -> adopted as baseline
    base_sp, is_buf = ctrl.resolve_effective_baseline(19.5, now=t0 + timedelta(minutes=10))
    assert base_sp == 19.5
    assert is_buf is False
    assert ctrl.baseline_temp_c == 19.5

    # 3. Open HEMS initiates buffer preheat: room is 19.5°C, elevates to 20.5°C
    t1 = t0 + timedelta(hours=1)
    elevated = ctrl.request_preheat(current_room_temp_c=19.5, current_setpoint_c=19.5, now=t1)
    assert elevated == 20.5
    assert ctrl.is_buffering is True

    # 4. While buffering, thermostat reports 20.5°C: baseline remains 19.5°C, is_buffering is True
    base_sp, is_buf = ctrl.resolve_effective_baseline(20.5, now=t1 + timedelta(minutes=15))
    assert base_sp == 19.5
    assert is_buf is True

    # 5. User manually overrides thermostat during buffer: turns dial to 21.0°C
    base_sp, is_buf = ctrl.resolve_effective_baseline(21.0, now=t1 + timedelta(minutes=25))
    assert base_sp == 21.0
    assert is_buf is False
    assert ctrl.is_buffering is False
    assert ctrl.baseline_temp_c == 21.0


def test_daikin_05c_step_snapping_and_settling_never_adopt_buffer_as_baseline():
    """
    Verifies that when request_preheat computes a 0.1 C target (e.g. 22.7 C or 22.8 C) and the Daikin P1P2
    thermostat snaps it to 0.5 C (22.5 C or 23.0 C), or while a write is settling / lingering after release,
    resolve_effective_baseline NEVER adopts the buffer setpoint as baseline_temp_c.
    """
    ctrl = RoomThermostatBufferController(default_baseline_c=20.5)
    t0 = datetime(2026, 10, 17, 11, 16, tzinfo=timezone.utc)

    # 1. Room at 21.7°C -> request_preheat returns 22.7°C; Daikin P1P2 snaps to 22.5°C
    elevated = ctrl.request_preheat(current_room_temp_c=21.7, current_setpoint_c=20.5, now=t0)
    assert elevated == 22.7

    # 2. 10 seconds later (inside 180s settling window), HA still reports old 20.5°C -> must NOT cancel buffering!
    base_sp, is_buf = ctrl.resolve_effective_baseline(20.5, now=t0 + timedelta(seconds=10))
    assert base_sp == 20.5
    assert is_buf is True

    # 3. 10 minutes later, HA reports snapped 22.5°C -> recognized as ours, baseline stays 20.5°C
    base_sp, is_buf = ctrl.resolve_effective_baseline(22.5, now=t0 + timedelta(minutes=10))
    assert base_sp == 20.5
    assert is_buf is True

    # 4. After 50 minutes, release is issued -> even if HA still reports 22.5°C before P1P2 settles, baseline stays 20.5°C
    t_rel = t0 + timedelta(minutes=50)
    assert ctrl.request_release(now=t_rel) == 20.5
    base_sp, is_buf = ctrl.resolve_effective_baseline(22.5, now=t_rel + timedelta(seconds=5))
    assert base_sp == 20.5
    assert is_buf is False
    base_sp, is_buf = ctrl.resolve_effective_baseline(22.5, now=t_rel + timedelta(minutes=5))
    assert base_sp == 20.5
    assert is_buf is False




