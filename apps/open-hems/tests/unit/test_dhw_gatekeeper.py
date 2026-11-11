from datetime import datetime, timezone
from layer4_control.preflight.models import SubsystemLiveState, LockoutHorizon
from layer4_control.preflight.dhw_gatekeeper import DhwGatekeeper


def test_emergency_comfort_overrules_everything():
    gk = DhwGatekeeper(emergency_floor_c=38.0)
    state = SubsystemLiveState(dhw_temp_c=36.5, outdoor_temp_c=5.0)
    horizon = LockoutHorizon(
        evaluated_at=datetime.now(timezone.utc),
        is_currently_locked=True  # Zelfs tijdens actieve spits!
    )
    decision = gk.evaluate(state, horizon, planned_mode="forced_off")
    assert decision.action == "EMERGENCY"
    assert decision.target_mode == "forced_on"
    assert "38.0" in decision.reason


def test_defer_when_lockout_too_close_and_temp_safe():
    gk = DhwGatekeeper(emergency_floor_c=38.0, comfort_buffer_c=40.0)
    # Vat is 44°C, run duurt ca. 30 min, spits begint al over 15 min.
    now = datetime(2026, 11, 2, 16, 45, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    state = SubsystemLiveState(dhw_temp_c=44.0, outdoor_temp_c=8.0)
    horizon = LockoutHorizon(now, spits_start, spits_end)

    decision = gk.evaluate(state, horizon, planned_mode="forced_on")
    assert decision.action == "DEFER"
    assert "uitgesteld" in decision.reason.lower()


def test_preemptive_start_when_lockout_would_cause_cold_tank():
    gk = DhwGatekeeper(emergency_floor_c=38.0, comfort_buffer_c=40.0)
    # Vat is 40.2°C, spits over 15 min duurt 2.5u. Verlies is 0.6°C -> vat zou 39.6°C worden (< 40°C).
    now = datetime(2026, 11, 2, 16, 45, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    state = SubsystemLiveState(dhw_temp_c=40.2, outdoor_temp_c=8.0)
    horizon = LockoutHorizon(now, spits_start, spits_end)

    decision = gk.evaluate(state, horizon, planned_mode="forced_on")
    assert decision.action == "START_PREEMPTIVE"
    assert decision.target_mode in ("forced_on", "max_on")
