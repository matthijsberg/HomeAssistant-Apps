"""
Unit Tests for LearnedForecaster Model Governance & Calibration Pipeline
========================================================================
Verifies:
1. Invariant #3 compliance: Recommendations must be 100% derived from empirical input samples,
   never from hardcoded synthetic constants. Changing input telemetry directly alters proposed values.
2. Absolute absence of hardcoded mock recommendations ('heating_modulation', 'dhw_standby').
3. Dynamic auto_applied logic based on drift_pct vs auto_accept_threshold (never hardcoded True).
4. Sample size guards (<14 stookdagen suppresses premature building_ua recommendation).
"""

import json
import unittest.mock as mock
import pytest
from layer2_calibration.learned_forecaster import HybridForecastingModel


from models.physics import calculate_carnot_cop


def _make_influx_response(unalloc_val: float, ua_slope_kwh_per_k: float, num_heating_days: int = 20) -> dict:
    """Helper to generate clean InfluxDB series with controlled ground truth parameters."""
    base_ts = 1758000000
    unalloc_values = []
    for q in range(96 * 7):
        ts = base_ts + q * 900
        unalloc_values.append([ts, unalloc_val])

    cv_values = []
    tout_values = []
    for d in range(num_heating_days):
        ts_day = base_ts + d * 86400
        tout = 5.0 + (d % 8) * 1.0  # tout varies 5.0C .. 12.0C -> dt_k varies 14.5 .. 7.5
        dt_k = 19.5 - tout
        cop = calculate_carnot_cop(tout)
        th_kwh = ua_slope_kwh_per_k * dt_k
        el_kwh = th_kwh / cop
        cv_values.append([ts_day, el_kwh])
        tout_values.append([ts_day, tout])

    return {
        "results": [
            {"series": [{"name": "energy_telemetry", "values": unalloc_values}]},
            {"series": [{"name": "energy_telemetry", "values": cv_values}]},
            {"series": [{"name": "energy_telemetry", "values": tout_values}]}
        ]
    }


def test_recommendations_strictly_derived_from_input_samples():
    """Verify that recommendations are purely functional transformations of InfluxDB inputs."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 5.0,
        "rolling_window_days": 90,
        "learning_rate_ewma": 1.0
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    # --- Scenario A: UA target ~350 W/K (slope = 350 * 24 / 1000 = 8.4 kWh/K), Baseload = 220W ---
    target_ua_a = 350.0
    slope_a = (target_ua_a * 24.0) / 1000.0
    baseload_a = 220.0
    mock_payload_a = json.dumps(_make_influx_response(baseload_a, slope_a, 20)).encode("utf-8")

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = mock_payload_a
        mock_url.return_value.__enter__.return_value = mock_resp

        res_a = forecaster.retrain_from_openhems(reload_params=False)
        assert res_a["status"] == "success"

        recs_list_a = res_a["recommendations"]["recommendations"]
        recs_a = {r["id"]: r for r in recs_list_a}

        # Guaranteed absence of mock items
        assert "heating_modulation" not in recs_a
        assert "dhw_standby" not in recs_a

        # Output derived directly from input A
        assert recs_a["building_ua"]["proposed_value"] == pytest.approx(target_ua_a, abs=5.0)
        assert recs_a["night_baseload"]["proposed_value"] == pytest.approx(baseload_a, abs=1.0)

    # --- Scenario B: Change input telemetry (UA target ~270 W/K, Baseload = 310W) ---
    target_ua_b = 270.0
    slope_b = (target_ua_b * 24.0) / 1000.0
    baseload_b = 310.0
    mock_payload_b = json.dumps(_make_influx_response(baseload_b, slope_b, 20)).encode("utf-8")

    # Reset base params
    forecaster.params["building"]["ua_base_w_per_k"] = 300.0
    forecaster.params["unallocated"]["night_baseload_floor_w"] = 250.0

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = mock_payload_b
        mock_url.return_value.__enter__.return_value = mock_resp

        res_b = forecaster.retrain_from_openhems(reload_params=False)
        assert res_b["status"] == "success"

        recs_list_b = res_b["recommendations"]["recommendations"]
        recs_b = {r["id"]: r for r in recs_list_b}

        # Output changes dynamically with inputs
        assert recs_b["building_ua"]["proposed_value"] == pytest.approx(target_ua_b, abs=5.0)
        assert recs_b["night_baseload"]["proposed_value"] == pytest.approx(baseload_b, abs=1.0)
        assert recs_b["building_ua"]["proposed_value"] != recs_a["building_ua"]["proposed_value"]
        assert recs_b["night_baseload"]["proposed_value"] != recs_a["night_baseload"]["proposed_value"]


def test_auto_applied_is_dynamically_evaluated():
    """Verify that auto_applied is never hardcoded and honors auto_accept_threshold."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 3.0,  # 3% tolerance
        "rolling_window_days": 90
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    # 1. Large drift (UA 340 vs 300 = +13.3% > 3% threshold) -> auto_applied MUST be False
    mock_payload_large = json.dumps(_make_influx_response(250.0, 340.0 * 24.0 / 1000.0, 20)).encode("utf-8")
    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = mock_payload_large
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        recs = {r["id"]: r for r in res["recommendations"]["recommendations"]}
        assert recs["building_ua"]["auto_applied"] is False
        assert recs["building_ua"]["drift_pct"] > 3.0

    # 2. Small drift (UA 303 vs 300 = +1.0% <= 3% threshold) -> auto_applied MUST be True
    mock_payload_small = json.dumps(_make_influx_response(250.0, 303.0 * 24.0 / 1000.0, 20)).encode("utf-8")
    forecaster.params["building"]["ua_base_w_per_k"] = 300.0
    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = mock_payload_small
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        recs = {r["id"]: r for r in res["recommendations"]["recommendations"]}
        assert recs["building_ua"]["auto_applied"] is True
        assert recs["building_ua"]["drift_pct"] <= 3.0


def test_sample_size_guard_suppresses_premature_ua_recommendation():
    """Verify that insufficient stookdagen (<14) suppresses building_ua recommendation."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 5.0,
        "rolling_window_days": 90
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    # Only 5 heating days (insufficient sample size)
    mock_payload_insufficient = json.dumps(_make_influx_response(250.0, 8.0, num_heating_days=5)).encode("utf-8")
    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = mock_payload_insufficient
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        rec_ids = [r["id"] for r in res["recommendations"]["recommendations"]]
        assert "building_ua" not in rec_ids
        assert "night_baseload" in rec_ids


def test_multivariable_building_loss_calibration():
    """Verify that when PV/weather data is present, 3D regression produces wind and solar coefficients."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {
            "ua_base_w_per_k": 320.0,
            "c_wind_w_per_k_ms": 0.208,
            "c_solar_passive": 0.056,
            "floor_capacity_kwh_per_k": 14.5
        },
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 5.0,
        "rolling_window_days": 90,
        "learning_rate_ewma": 1.0
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    base_ts = 1758000000
    unalloc_values = [[base_ts + q * 900, 250.0] for q in range(96 * 7)]
    cv_values = []
    tout_values = []
    pv_values = []
    for d in range(25):
        ts_day = base_ts + d * 86400
        tout = 4.0 + (d % 6) * 1.5
        dt_k = 19.5 - tout
        pv_kwh = 5.0 + (d % 10) * 2.0
        th_kwh = 7.5 * dt_k - 0.08 * pv_kwh
        el_kwh = th_kwh / calculate_carnot_cop(tout)
        cv_values.append([ts_day, el_kwh])
        tout_values.append([ts_day, tout])
        pv_values.append([ts_day, pv_kwh])

    mock_data = {
        "results": [
            {"series": [{"name": "energy_telemetry", "values": unalloc_values}]},
            {"series": [{"name": "energy_telemetry", "values": cv_values}]},
            {"series": [{"name": "energy_telemetry", "values": tout_values}]},
            {"series": [{"name": "energy_telemetry", "values": pv_values}]}
        ]
    }

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        assert res["status"] == "success"
        recs = {r["id"]: r for r in res["recommendations"]["recommendations"]}

        assert "building_ua" in recs
        # Synthetic truth: Q_th = 7.5·ΔT − 0.08·E_pv  ->  UA = 7.5·1000/24 = 312.5 W/K, PV ratio 0.08.
        # (The former collinear 3-D fit always returned its hard-coded fallback of 292.6 W/K.)
        assert abs(recs["building_ua"]["proposed_value"] - 312.5) < 2.0
        assert "c_solar_pv_ratio" in recs
        assert abs(recs["c_solar_pv_ratio"]["proposed_value"] - 0.08) < 0.02
        # No wind series in the query: the wind coefficient is not identifiable and must not be "calibrated"
        assert "c_wind" not in recs


def test_retrain_uses_trimmed_mean_and_filters_frozen_hp_meter_quarters():
    """Verify 7x96 profile uses P0-P95 trimmed mean and skips frozen heat pump meter quarters."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 5.0,
        "rolling_window_days": 90,
        "learning_rate_ewma": 1.0,
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    # Pick a specific timestamp in summer/early autumn (all in CEST, no DST shift) across 8 weeks
    base_ts = 1754395200  # 2025-08-05 12:00 UTC (all 9 weeks stay in CEST)
    unalloc_values = []
    # 6 weeks at 350W base, 2 weeks with 1150W appliance usage -> median would be 350W, trimmed mean is 550W
    for w in range(6):
        unalloc_values.append([base_ts + w * 7 * 86400, 350.0, 40.0, 2.5])
    for w in range(6, 8):
        unalloc_values.append([base_ts + w * 7 * 86400, 1150.0, 40.0, 3.1])
    # Add 1 frozen-meter anomaly: hp_w=116W, hp_std=0.0, unalloc=2400W -> must be excluded from historical model
    unalloc_values.append([base_ts + 8 * 7 * 86400, 2400.0, 116.0, 0.0])

    mock_data = {
        "results": [
            {"series": [{"name": "energy_telemetry", "values": unalloc_values}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
        ]
    }

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        assert res["status"] == "success"

        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(base_ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Amsterdam"))
        learned_val = forecaster.profile["profile_96_quarters"][dt.weekday()][dt.hour * 4 + dt.minute // 15]
        # Must reflect the 8 valid samples (mean = 550.0W), NOT 350W (median) and NOT ~755W (if frozen meter were included)
        assert learned_val == pytest.approx(550.0, abs=1.0)


def test_retrain_calibrates_season_aware_pv_yield_ratio():
    """Verify pv_yield_ratio (solar.performance_ratio_pct) calibrates against season-aware POA clear-sky reference."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "solar": {"performance_ratio_pct": 88.0},
        "auto_accept_max_drift_pct": 10.0,
        "rolling_window_days": 90,
        "learning_rate_ewma": 1.0,
    }
    forecaster.profile = {"profile_96_quarters": [[250.0] * 96 for _ in range(7)]}

    # Mid-October timestamps (clear-sky POA_100 over Oct 14-21 averages ~18.3 kWh/day; 16.1 kWh actual = ~88% PR)
    oct_ts = 1760400000  # Oct 2025
    unalloc_values = [[oct_ts + q * 900, 300.0] for q in range(16)]
    pv_values = [[oct_ts + d * 86400, 16.1] for d in range(8)]

    mock_data = {
        "results": [
            {"series": [{"name": "energy_telemetry", "values": unalloc_values}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": pv_values}]},
        ]
    }

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        assert res["status"] == "success"
        recs = {r["id"]: r for r in res["recommendations"]["recommendations"]}
        assert "pv_yield_ratio" in recs
        assert 84.0 <= recs["pv_yield_ratio"]["proposed_value"] <= 92.0


def test_retrain_updates_tap_demand_with_recency_and_streak_boost():
    """Verify that repeated new evening showers on a weekday (e.g. Tuesday training) adapt quickly (>80% after 3 weeks)."""
    forecaster = HybridForecastingModel()
    forecaster.secrets = {"influxdb": {"local_ha_influxdb": "dummy_pw"}}
    forecaster.params = {
        "building": {"ua_base_w_per_k": 300.0},
        "unallocated": {"night_baseload_floor_w": 250.0},
        "auto_accept_max_drift_pct": 5.0,
        "rolling_window_days": 90,
        "learning_rate_ewma": 0.05,  # standard 5% EWMA
    }
    forecaster.profile = {
        "profile_96_quarters": [[250.0] * 96 for _ in range(7)],
        "tap_demand_profile_96": [[0.010] * 96 for _ in range(7)],
        "dhw_profile_96_quarters": [[14.0] * 96 for _ in range(7)],
    }

    # Generate 8 weeks of 15m tank temperature history
    # Pick a Tuesday evening 20:30 CEST (2025-08-05 18:30 UTC is Tuesday 20:30 CEST)
    base_ts = 1754395200  # 2025-08-05 12:00 UTC (Tuesday 14:00 CEST)
    unalloc_values = []
    tank_values = []
    dhw_el_values = []

    # 8 weeks * 7 days * 96 quarters = 5376 quarters
    # For weeks 0..4 (first 5 Tuesdays): no shower at 20:30 (tank stays steady at 50.0°C)
    # For weeks 5..7 (last 3 Tuesdays): heavy shower at 20:30 (quarter +26 from 14:00 -> 20:30, tank drops 50.0 -> 48.5°C = ~0.60 kWh_th)
    total_q = 8 * 7 * 96
    for q in range(total_q):
        ts = base_ts + q * 900
        week_idx = q // (7 * 96)
        q_in_week = q % (7 * 96)
        unalloc_values.append([ts, 300.0, 35.0, 1.0])
        dhw_el_values.append([ts, 0.0])
        if q_in_week == 26 and week_idx >= 5:
            tank_values.append([ts, 48.5])  # 1.5°C drop in 15m -> ~0.60 kWh_th draw-off
        else:
            tank_values.append([ts, 50.0])

    mock_data = {
        "results": [
            {"series": [{"name": "energy_telemetry", "values": unalloc_values}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": []}]},
            {"series": [{"name": "energy_telemetry", "values": tank_values}]},
            {"series": [{"name": "energy_telemetry", "values": dhw_el_values}]},
        ]
    }

    with mock.patch("urllib.request.urlopen") as mock_url, \
         mock.patch("layer2_calibration.learned_forecaster.save_json"), \
         mock.patch("layer2_calibration.learned_forecaster._persist_params"):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        res = forecaster.retrain_from_openhems(reload_params=False)
        assert res["status"] == "success"

        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        target_dt = datetime.fromtimestamp(base_ts + 26 * 900, tz=timezone.utc).astimezone(ZoneInfo("Europe/Amsterdam"))
        dow = target_dt.weekday()
        q_idx = target_dt.hour * 4 + target_dt.minute // 15
        learned_tap = forecaster.profile["tap_demand_profile_96"][dow][q_idx]
        # Draw-off per shower is ~0.60 kWh_th. After 3 consecutive weeks, streak boost (>80%) must raise learned_tap above 0.45 kWh_th
        assert learned_tap >= 0.45
        assert forecaster.profile["dhw_profile_96_quarters"][dow][q_idx] >= 600.0


def test_daikin_classifier_handles_ha_state_dicts_and_numeric_mqtt():
    """Verify DaikinP1P2StateClassifier extracts state strings from HA state dicts and numeric MQTT payloads."""
    from site_adapters.daikin_p1p2.classifier import DaikinP1P2StateClassifier

    # Case 1: MQTT expired (empty), HA states map contains full state dicts from get_ha_states_map()
    ha_states = {
        "binary_sensor.hc_dhw_valve_dhw_tank": {"entity_id": "binary_sensor.hc_dhw_valve_dhw_tank", "state": "on"},
        "binary_sensor.hc_mode_climate_heating": {"entity_id": "binary_sensor.hc_mode_climate_heating", "state": "on"},
    }
    res = DaikinP1P2StateClassifier.classify(total_power_w=3200.0, mqtt_cache={}, ha_states=ha_states)
    assert res.mode == "DHW"
    assert res.dhw_w == 3200.0
    assert res.heating_w == 0.0

    # Case 2: MQTT cache has float 1.0 (parsed from "1" by HemsMqttSubscriberThread)
    mqtt_cache = {"P1P2/P/P1P2MQTT/bridge0/S/1/Valve_DHW_Tank": 1.0}
    res_mqtt = DaikinP1P2StateClassifier.classify(total_power_w=2800.0, mqtt_cache=mqtt_cache, ha_states={})
    assert res_mqtt.mode == "DHW"
    assert res_mqtt.dhw_w == 2800.0

    # Case 3: Pure deterministic priority via select.daily_energy_usage_sums_wp regardless of power draw
    ha_select_states = {
        "select.daily_energy_usage_sums_wp": {"entity_id": "select.daily_energy_usage_sums_wp", "state": "dhw"},
    }
    res_sel = DaikinP1P2StateClassifier.classify(total_power_w=35.0, mqtt_cache={}, ha_states=ha_select_states)
    assert res_sel.mode == "DHW"
    assert res_sel.dhw_w == 35.0
    assert res_sel.confidence == 1.0




