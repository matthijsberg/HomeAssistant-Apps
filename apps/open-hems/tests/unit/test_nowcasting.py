"""
Unit Tests for ObservationNowcaster (Local Microclimate Nudging)
===============================================================
"""

import pytest
import math
from layer1_data_collection.nowcasting import ObservationNowcaster


def test_nudge_solar_forecast_anchoring():
    """Verify that slot 0 is anchored to live inverter solar power and decays smoothly."""
    raw_solar = [1.5, 1.6, 1.7, 1.8, 1.5, 1.0, 0.5, 0.0]
    live_solar = 1.0  # Real solar is 0.5 kW lower due to local clouds

    nudged = ObservationNowcaster.nudge_solar_forecast(
        raw_solar,
        live_solar_kw=live_solar,
        slot_hours=0.25,
        horizon_hours=2.0
    )

    # Slot 0 must match live reading exactly
    assert nudged[0] == 1.0

    # Intermediate slots must be lower than raw, but converging back toward raw
    assert nudged[1] < raw_solar[1]
    diff_slot_1 = raw_solar[1] - nudged[1]
    diff_slot_4 = raw_solar[4] - nudged[4]
    assert diff_slot_1 > diff_slot_4, "Discrepancy must decay smoothly over time"

    # Night slot (0.0) remains strictly 0.0
    assert nudged[-1] == 0.0


def test_nudge_temperature_forecast_anchoring():
    """Verify that outdoor temperature anchors to local Wittboy reading."""
    raw_temps = [15.0, 15.2, 15.4, 15.6, 15.8, 16.0]
    live_temp = 17.0  # Local garden is 2.0C warmer

    nudged = ObservationNowcaster.nudge_temperature_forecast(
        raw_temps,
        live_temp_c=live_temp,
        slot_hours=0.25,
        horizon_hours=2.0
    )

    assert nudged[0] == 17.0
    assert nudged[1] > raw_temps[1]
    # By hour 1.25 (index 5), diff is smaller than 2.0
    assert (nudged[5] - raw_temps[5]) < 2.0


def test_nudge_with_none_preserves_raw():
    """Verify that missing sensor gracefully returns the unnudged raw forecast."""
    raw = [10.0, 11.0, 12.0]
    assert ObservationNowcaster.nudge_temperature_forecast(raw, None) == raw
    assert ObservationNowcaster.nudge_solar_forecast(raw, None) == raw
    assert ObservationNowcaster.nudge_wind_forecast(raw, None) == raw


def test_sanitizer_preserves_poa_solar_forecast_without_nowcast_bump():
    """Verify TelemetrySanitizer relies on the POA solar forecast without short-term live inverter nudging."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from layer1_data_collection.sanitizer import TelemetrySanitizer

    ams = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 10, 14, 11, 45, tzinfo=ams)
    raw_prices = [{"dt": now, "price": 0.25}]
    raw_solar = [{"dt": now, "solar_kw": 1.70}]
    raw_weather = [{"dt": now, "temperature": 14.0, "wind_speed_ms": 3.0, "solar_radiation_w_m2": 320.0}]

    frame = TelemetrySanitizer.sanitize(
        now=now,
        raw_prices=raw_prices,
        raw_solar=raw_solar,
        raw_weather=raw_weather,
        raw_unallocated_matrix=[[400.0] * 96 for _ in range(7)],
        current_dhw_temp=48.0,
        last_hardware_reading_time=now,
        live_solar_kw=0.50,
        live_solar_radiation_w_m2=100.0,
        live_outdoor_temp_c=15.5,
        horizon_slots=4,
    )

    assert frame.slots[0].solar_kw == 1.70
    assert frame.slots[0].solar_rad_w_m2 == 320.0
    assert frame.slots[0].outdoor_temp_c == 15.5

