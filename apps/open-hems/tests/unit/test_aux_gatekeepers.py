from datetime import datetime, timezone
from layer4_control.preflight.models import SubsystemLiveState, LockoutHorizon
from layer4_control.preflight.heating_gatekeeper import HeatingGatekeeper
from layer4_control.preflight.battery_gatekeeper import BatteryGatekeeper


def test_heating_hydraulic_isolation_when_dhw_active():
    hg = HeatingGatekeeper()
    state = SubsystemLiveState(dhw_temp_c=45.0, outdoor_temp_c=7.0)
    decision = hg.evaluate(state, is_dhw_running=True)
    assert decision.action == "ISOLATE"
    assert decision.target_mode == "off"
    assert "hydraulische uitsluiting" in decision.reason.lower()


def test_heating_defer_when_lockout_too_close():
    hg = HeatingGatekeeper(min_cv_run_mins=30.0)
    now = datetime(2026, 11, 2, 7, 10, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)

    state = SubsystemLiveState(
        dhw_temp_c=48.0,
        outdoor_temp_c=4.0,
        room_temp_c=19.2,
        room_setpoint_c=19.5
    )
    horizon = LockoutHorizon(now, spits_start, spits_end)
    decision = hg.evaluate(state, horizon=horizon, is_dhw_running=False, is_heating_active=False)
    assert decision.action == "DEFER"
    assert "uitgesteld" in decision.reason.lower()


def test_heating_preheats_before_lockout():
    hg = HeatingGatekeeper(preheat_lead_mins=60.0)
    now = datetime(2026, 11, 2, 16, 15, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    state = SubsystemLiveState(dhw_temp_c=48.0, outdoor_temp_c=6.0, room_setpoint_c=20.5)
    horizon = LockoutHorizon(now, spits_start, spits_end)
    decision = hg.evaluate(state, horizon=horizon, is_dhw_running=False, is_heating_active=True)
    assert decision.action == "PREHEAT"
    assert decision.target_temp_c == 21.5  # +1.0°C boost voor betondekvloer


def test_heating_respects_advised_off_and_does_not_preheat():
    hg = HeatingGatekeeper(preheat_lead_mins=60.0, min_preheat_lead_mins=40.0)
    now = datetime(2026, 11, 2, 16, 15, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    # In geadviseerd uit (P75 piekschouder) met stilstaande warmtepomp: weert nieuwe koude start
    state = SubsystemLiveState(dhw_temp_c=48.0, outdoor_temp_c=6.0, room_temp_c=20.5, room_setpoint_c=20.5)
    horizon = LockoutHorizon(now, spits_start, spits_end, is_currently_advised_off=True)
    decision = hg.evaluate(state, horizon=horizon, is_dhw_running=False, is_heating_active=False)
    assert decision.action == "DEFER"
    assert "geadviseerd uit" in decision.reason.lower()


def test_heating_allows_ongoing_modulated_run_to_continue_through_advised_off():
    hg = HeatingGatekeeper(preheat_lead_mins=60.0, min_preheat_lead_mins=40.0)
    now = datetime(2026, 11, 2, 16, 15, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    spits_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    # In geadviseerd uit maar run is AL actief en gemoduleerd: mag doorlopen in stand auto
    state = SubsystemLiveState(dhw_temp_c=48.0, outdoor_temp_c=6.0, room_temp_c=20.5, room_setpoint_c=20.5)
    horizon = LockoutHorizon(now, spits_start, spits_end, is_currently_advised_off=True)
    decision = hg.evaluate(state, horizon=horizon, is_dhw_running=False, is_heating_active=True)
    assert decision.action == "CONTINUE_RUN"
    assert decision.target_mode == "normal"
    assert "doorlopen" in decision.reason.lower()


def test_battery_reserves_for_spits():
    bg = BatteryGatekeeper(spits_reserve_kwh=4.0, battery_capacity_kwh=15.0)
    now = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)
    spits_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    horizon = LockoutHorizon(now, spits_start, None)

    # Batterij staat op 25% (3.75 kWh), minder dan de benodigde 4.0 kWh voor de spits
    state = SubsystemLiveState(dhw_temp_c=48.0, outdoor_temp_c=10.0, battery_soc_pct=25.0)
    decision = bg.evaluate(state, horizon=horizon, requested_mode="DISCHARGE")
    assert decision.action == "HOLD"
    assert "reserve" in decision.reason.lower()
