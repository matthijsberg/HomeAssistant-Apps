"""
Unit Tests for Settings API & Comfort Margin Roundtrip (WP4)
============================================================
Verifies:
1. GET /api/settings returns effective settings with dhw_optimizer.comfort_margin.
2. POST /api/settings updates comfort_margin mode, factor, min_margin, fixed_margin.
3. Plan includes comfort_margin_mode, comfort_boundary_c in decision_details.
4. Input validation rejects invalid modes or out-of-range bounds.
"""

import pytest
from unittest.mock import MagicMock
from api import routes_system
from api.secrets_store import CONFIG_FILE, load_json, save_json
from layer3_scheduling.central_planner import CentralPlanner
from layer3_scheduling.dhw_optimizer import DhwOptimizerParams
from tests.unit.test_dhw_optimizer import make_test_slots
from layer1_data_collection.sanitizer import CleanTelemetryFrame
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the live /config/heatpump_config.json and never start a background re-plan from tests."""
    cfg_copy = tmp_path / "heatpump_config.json"
    save_json(cfg_copy, load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {})
    monkeypatch.setattr(routes_system, "CONFIG_FILE", cfg_copy)
    monkeypatch.setattr(routes_system, "ensure_active_canonical_plan", lambda *a, **k: None)
    return cfg_copy


class MockHandler:
    def __init__(self, body=None, path="/api/settings"):
        self.body = body or {}
        self.path = path
        self.sent_json = None
        self.sent_status = 200

    def _read_json_body(self):
        return self.body

    def _send_json(self, data, status=200):
        self.sent_json = data
        self.sent_status = status


def test_get_settings_contains_comfort_margin():
    handler = MockHandler(path="/api/settings")
    res = routes_system.handle_get(handler, "/api/settings", {})
    assert res is True
    assert handler.sent_json is not None
    assert "dhw_optimizer" in handler.sent_json
    cm = handler.sent_json["dhw_optimizer"]["comfort_margin"]
    assert "mode" in cm
    assert cm["mode"] in ("p95", "p50", "fixed")


def test_post_settings_updates_and_validates():
    # 1. Valid update to p50
    body = {
        "dhw_optimizer": {
            "comfort_margin": {
                "mode": "p50",
                "min_margin_c": 0.5
            }
        }
    }
    handler = MockHandler(body=body, path="/api/settings")
    res = routes_system.handle_post(handler, "/api/settings", body)
    assert res is True
    assert handler.sent_status == 200
    assert handler.sent_json is not None
    assert handler.sent_json["dhw_optimizer"]["comfort_margin"]["mode"] == "p50"
    assert handler.sent_json["dhw_optimizer"]["comfort_margin"]["min_margin_c"] == 0.5

    # 2. Invalid mode rejected
    bad_body = {
        "dhw_optimizer": {
            "comfort_margin": {
                "mode": "invalid_mode"
            }
        }
    }
    bad_handler = MockHandler(body=bad_body, path="/api/settings")
    routes_system.handle_post(bad_handler, "/api/settings", bad_body)
    assert bad_handler.sent_status == 400

    # 3. Out-of-bounds factor rejected
    bad_factor_body = {
        "dhw_optimizer": {
            "comfort_margin": {
                "tap_stress_factor": 5.0
            }
        }
    }
    bad_f_handler = MockHandler(body=bad_factor_body, path="/api/settings")
    routes_system.handle_post(bad_f_handler, "/api/settings", bad_factor_body)
    assert bad_f_handler.sent_status == 400


def test_battery_settings_get_and_post():
    # 1. Update battery nominal and max powers
    body = {
        "battery": {
            "nominal_charge_kw": 2.0,
            "max_charge_kw": 4.5,
            "nominal_discharge_kw": 2.2,
            "max_discharge_kw": 4.8,
            "boost_opportunity_spread_eur": 0.25
        }
    }
    handler = MockHandler(body=body, path="/api/settings")
    res = routes_system.handle_post(handler, "/api/settings", body)
    assert res is True
    assert handler.sent_status == 200
    assert handler.sent_json is not None
    bat = handler.sent_json["battery"]
    assert bat["nominal_charge_kw"] == 2.0
    assert bat["max_charge_kw"] == 4.5
    assert bat["nominal_discharge_kw"] == 2.2
    assert bat["max_discharge_kw"] == 4.8
    assert bat["boost_opportunity_spread_eur"] == 0.25

    # 2. Get settings returns battery config
    get_handler = MockHandler(path="/api/settings")
    routes_system.handle_get(get_handler, "/api/settings", {})
    assert get_handler.sent_status == 200
    assert get_handler.sent_json is not None
    assert get_handler.sent_json["battery"]["nominal_charge_kw"] == 2.0
    assert get_handler.sent_json["battery"]["max_charge_kw"] == 4.5

    # 3. Invalid out-of-range bounds rejected
    bad_body = {
        "battery": {
            "max_charge_kw": 50.0
        }
    }
    bad_handler = MockHandler(body=bad_body, path="/api/settings")
    routes_system.handle_post(bad_handler, "/api/settings", bad_body)
    assert bad_handler.sent_status == 400


from tests.unit.test_central_planner_explanations import create_sample_telemetry_frame


def test_planner_reflects_comfort_margin_in_decision_details():
    now_dt = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
    frame = create_sample_telemetry_frame(now_dt, current_dhw_temp=45.0)

    params_p50 = DhwOptimizerParams(comfort_margin_mode="p50", min_comfort_margin_c=0.5)
    plan = CentralPlanner.plan(frame, current_dhw_temp=45.0, dhw_optimizer_params=params_p50, dhw_engine="dp")

    assert plan.dhw_summary is not None
    details = plan.dhw_summary.decision_details
    assert details is not None
    assert details.get("comfort_margin_mode") == "p50"
    assert details.get("comfort_boundary_c") == 40.5


# --------------------------------------------------------------------------- dhw_policy (ADR-006, WP4)
def test_get_settings_contains_dhw_policy_with_defaults():
    handler = MockHandler(path="/api/settings")
    routes_system.handle_get(handler, "/api/settings", {})
    pol = handler.sent_json["dhw_policy"]
    assert pol["engine"] in ("daikin_first", "dp")
    for key in ("preheat_margin_c", "preheat_window_hours", "advance_margin", "advance_max_start_temp_c",
                "boost_max_start_temp_c", "free_price_eur_per_kwh", "sg4_no_effect_timeout_min", "sg4_no_effect_cooldown_min"):
        assert key in pol, key


def test_post_dhw_policy_saves_valid_values_and_allows_switching_rules_off(isolated_config):
    body = {"dhw_policy": {"engine": "daikin_first", "preheat_margin_c": 1.5, "advance_margin": None,
                           "free_price_eur_per_kwh": 0.01}}
    handler = MockHandler(body=body)
    routes_system.handle_post(handler, "/api/settings", body)
    assert handler.sent_status == 200
    pol = handler.sent_json["dhw_policy"]
    assert pol["preheat_margin_c"] == 1.5
    assert pol["advance_margin"] is None
    assert pol["free_price_eur_per_kwh"] == 0.01
    saved = load_json(isolated_config)["dhw_policy"]
    assert saved["advance_margin"] is None and saved["preheat_margin_c"] == 1.5


@pytest.mark.parametrize("bad", [
    {"engine": "magic"},
    {"preheat_margin_c": 9},
    {"boost_max_start_temp_c": None},
    {"advance_margin": "veel"},
    {"unknown_key": 1},
])
def test_post_dhw_policy_rejects_invalid_values(bad, isolated_config):
    before = load_json(isolated_config)
    handler = MockHandler(body={"dhw_policy": bad})
    routes_system.handle_post(handler, "/api/settings", {"dhw_policy": bad})
    assert handler.sent_status == 400
    assert load_json(isolated_config) == before

