"""Floor (screed) state estimator: settled manifold readings, supply-water correction and provenance."""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from integrations.daikin_altherma.reader import read_floor_circuit, FLOOR_MANIFOLD_ENTITIES
from layer2_calibration.floor_state_estimator import (
    FloorCircuitObservation, FloorEstimatorParams, FloorStateEstimate, estimate_floor_state
)
from models.canonical import Quality

AMS = ZoneInfo("Europe/Amsterdam")
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=AMS)


def _obs(minute=0, temps=(24.0,) * 7, compressor_on=False, dhw_active=False, minutes_in_state=120.0, q_kw=0.0):
    return FloorCircuitObservation(
        timestamp=T0 + timedelta(minutes=minute),
        manifold_temps_c=temps,
        compressor_on=compressor_on,
        dhw_active=dhw_active,
        minutes_since_state_change=minutes_in_state,
        heat_output_kw=q_kw,
    )


def _prev(temp_c, minute=-1, source="settled", anchored_minute=None):
    anchored = T0 + timedelta(minutes=minute if anchored_minute is None else anchored_minute)
    return FloorStateEstimate(temp_c, source, Quality.GOOD, T0 + timedelta(minutes=minute), anchored, temp_c)


def test_settled_reading_is_the_screed_temperature():
    """No CV heat for >= 60 min: the circulating manifold water reads the screed directly."""
    est = estimate_floor_state(_obs(temps=(24.1, 24.0, 23.9, None, float("nan"), 85.0, 24.0), minutes_in_state=60.0))
    assert est.source == "settled"
    assert est.quality == Quality.GOOD
    assert est.temp_c == pytest.approx(24.0)  # None, NaN and the implausible 85 C are ignored
    assert est.anchored_at == est.updated_at


def test_settled_reading_is_not_clamped_to_room_temperature():
    """A floor colder than the room is physical (sun on the room air, floor lagging); no room-0.2 clamp."""
    est = estimate_floor_state(_obs(temps=(20.3,) * 7, minutes_in_state=90.0))
    assert est.temp_c == pytest.approx(20.3)


def test_supply_water_during_heating_is_corrected_and_smoothed():
    """While CV heat flows, the reading is R_w*Q above the screed; the estimate moves towards it gradually."""
    p = FloorEstimatorParams()
    prev = _prev(22.0)
    obs = _obs(temps=(25.0,) * 7, compressor_on=True, minutes_in_state=90.0, q_kw=5.0)
    est = estimate_floor_state(obs, prev)
    target = 25.0 - p.water_offset_k_per_kw * 5.0
    assert est.source == "corrected"
    assert est.quality == Quality.ESTIMATED
    assert 22.0 < est.temp_c < target  # one minute of smoothing, never the raw water temperature

    # After a sustained run the estimate converges to the corrected reading
    for minute in range(1, 240):
        est = estimate_floor_state(_obs(minute=minute, temps=(25.0,) * 7, compressor_on=True, minutes_in_state=90.0 + minute, q_kw=5.0), est)
    assert est.temp_c == pytest.approx(target, abs=0.01)


def test_screed_does_not_cool_while_heat_flows_in():
    """Run start: the water has not arrived yet, so the corrected reading is below the floor; hold the floor."""
    prev = _prev(23.0)
    est = estimate_floor_state(_obs(temps=(23.1,) * 7, compressor_on=True, minutes_in_state=2.0, q_kw=6.0), prev)
    assert est.source == "corrected"
    assert est.temp_c == pytest.approx(23.0)


def test_settle_window_holds_previous_estimate_capped_at_reading():
    """Just after a run the reading still carries fading supply water: keep the corrected estimate."""
    prev = _prev(25.3, source="corrected")
    est = estimate_floor_state(_obs(temps=(26.4,) * 7, compressor_on=False, minutes_in_state=10.0), prev)
    assert est.source == "held"
    assert est.quality == Quality.INTERPOLATED
    assert est.temp_c == pytest.approx(25.3)
    # The screed can never be warmer than the water that circulates through it
    est = estimate_floor_state(_obs(minute=1, temps=(25.0,) * 7, compressor_on=False, minutes_in_state=11.0), est)
    assert est.temp_c == pytest.approx(25.0)


def test_dhw_run_is_not_cv_heat_and_settles():
    """With the 3-way valve on the tank the floor loops get no heat-pump water and settle on the screed."""
    prev = _prev(22.5, source="corrected")
    during = estimate_floor_state(_obs(temps=(23.0,) * 7, compressor_on=True, dhw_active=True, minutes_in_state=15.0, q_kw=4.0), prev)
    assert during.source == "held"
    assert during.temp_c == pytest.approx(22.5)  # DHW heat output is not subtracted or attributed to the floor
    later = estimate_floor_state(_obs(minute=50, temps=(22.4,) * 7, compressor_on=True, dhw_active=True, minutes_in_state=65.0, q_kw=4.0), during)
    assert later.source == "settled"
    assert later.temp_c == pytest.approx(22.4)


def test_hold_expiry_tracks_slowly_without_jumping():
    """After max_hold the estimate follows the best available reading slowly and is flagged STALE."""
    p = FloorEstimatorParams()
    prev = FloorStateEstimate(21.0, "held", Quality.INTERPOLATED, T0 - timedelta(minutes=1),
                              T0 - timedelta(minutes=p.max_hold_minutes + 5), 21.5)
    est = estimate_floor_state(_obs(temps=(22.0,) * 7, compressor_on=False, minutes_in_state=5.0), prev)
    assert est.source == "tracking"
    assert est.quality == Quality.STALE
    assert 21.0 < est.temp_c < 21.1


def test_cold_start_uses_best_available_reading():
    est = estimate_floor_state(_obs(temps=(26.0,) * 7, compressor_on=True, minutes_in_state=60.0, q_kw=5.0))
    assert est.source == "cold_start"
    assert est.quality == Quality.STALE
    assert est.temp_c == pytest.approx(26.0 - FloorEstimatorParams().water_offset_k_per_kw * 5.0)
    # A previous estimate older than the cold-start gap is discarded
    stale_prev = _prev(18.0, minute=-int(FloorEstimatorParams().cold_start_gap_minutes) - 10)
    assert estimate_floor_state(_obs(temps=(26.0,) * 7, compressor_on=True, minutes_in_state=60.0, q_kw=5.0), stale_prev).source == "cold_start"


def test_no_reading_holds_within_limit_and_never_invents():
    prev = _prev(23.0)
    held = estimate_floor_state(_obs(temps=(None,) * 7), prev)
    assert held.source == "held" and held.temp_c == 23.0 and held.manifold_reading_c is None
    expired = _prev(23.0, anchored_minute=-int(FloorEstimatorParams().max_hold_minutes) - 1)
    assert estimate_floor_state(_obs(temps=(None,) * 7), expired) is None
    assert estimate_floor_state(_obs(temps=(None,) * 7)) is None


def _states(compressor="off", valve="on", demand="off", heat_w="0", changed=T0 - timedelta(minutes=70), temps=(24.0,) * 7):
    lc = changed.astimezone(ZoneInfo("UTC")).isoformat()
    m = {
        "binary_sensor.hc_mode_compressor": {"state": compressor, "last_changed": lc},
        "binary_sensor.hc_dhw_valve_dhw_tank": {"state": valve, "last_changed": lc},
        "binary_sensor.hc_dhw_dhw_demand": {"state": demand, "last_changed": (T0 - timedelta(minutes=1)).isoformat()},
        "sensor.hc_power_production_heatpump": {"state": heat_w},
    }
    for entity, t in zip(FLOOR_MANIFOLD_ENTITIES, temps):
        m[entity] = {"state": str(t)}
    return m


def test_reader_maps_home_assistant_states():
    """Idle (valve parked on the tank, compressor off for 70 min) reads as a settled floor."""
    obs = read_floor_circuit(_states(), T0)
    assert obs.compressor_on is False
    assert obs.minutes_since_state_change == pytest.approx(70.0)  # DHW demand flicker does not reset the timer
    assert obs.heat_output_kw == 0.0
    assert estimate_floor_state(obs).source == "settled"


def test_reader_uses_valve_not_demand_for_dhw():
    """2026-10-08 15:30: demand 'on' while the valve fed the floor at LWT 30 C. That is CV heat, not DHW."""
    obs = read_floor_circuit(_states(compressor="on", valve="off", demand="on", heat_w="4700"), T0)
    assert obs.dhw_active is False
    assert obs.heat_output_kw == pytest.approx(4.7)
    est = estimate_floor_state(obs, _prev(20.3))
    assert est.source == "corrected"


def test_reader_falls_back_to_demand_when_valve_unavailable():
    obs = read_floor_circuit(_states(compressor="on", valve="unavailable", demand="on", heat_w="3000"), T0)
    assert obs.dhw_active is True
    assert obs.minutes_since_state_change == pytest.approx(1.0)


def test_reader_unknown_compressor_never_settles():
    obs = read_floor_circuit(_states(compressor="unavailable"), T0)
    assert obs.compressor_on is None
    assert obs.minutes_since_state_change is None
    assert estimate_floor_state(obs).source == "cold_start"


def test_held_floor_cools_towards_the_room_without_cv_heat():
    """Winter stops: the pipe-level screed keeps cooling (~0.5 K/h) towards the Madoka while it settles."""
    p = FloorEstimatorParams()
    prev = _prev(25.0, source="corrected")
    obs = FloorCircuitObservation(timestamp=T0 + timedelta(minutes=29), manifold_temps_c=(26.0,) * 7, compressor_on=False,
                                  dhw_active=False, minutes_since_state_change=30.0, heat_output_kw=0.0, room_temp_c=21.0)
    est = estimate_floor_state(obs, prev)
    assert est.source == "held"
    expected = 21.0 + 4.0 * math.exp(-30.0 / p.hold_cooling_tau_minutes)
    assert est.temp_c == pytest.approx(expected, abs=1e-6)
    # While CV heat flows the floor is not cooled, and without a room reading the value is simply held
    warm = estimate_floor_state(FloorCircuitObservation(T0 + timedelta(minutes=29), (26.0,) * 7, False, False, 30.0, 0.0), prev)
    assert warm.temp_c == pytest.approx(25.0)


def test_reader_passes_madoka_room_temperature():
    s = _states()
    s["climate.woonkamer_climate_daikin"] = {"state": "heat", "attributes": {"current_temperature": 21.3}}
    assert read_floor_circuit(s, T0).room_temp_c == pytest.approx(21.3)
    del s["climate.woonkamer_climate_daikin"]
    s["sensor.hc_sensors_temperature_room"] = {"state": "21.1"}
    assert read_floor_circuit(s, T0).room_temp_c == pytest.approx(21.1)


def test_frozen_heat_output_with_compressor_off_is_not_cv_heat():
    """Winter 2025-26: the P1P2 heat output kept its last value (up to -3.7 kW for 23 h) after the compressor stopped."""
    est = estimate_floor_state(_obs(temps=(23.0,) * 7, compressor_on=False, minutes_in_state=90.0, q_kw=3.1))
    assert est.source == "settled"
    assert est.temp_c == pytest.approx(23.0)
