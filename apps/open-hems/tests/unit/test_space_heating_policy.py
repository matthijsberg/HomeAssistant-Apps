import pytest
from layer3_scheduling.space_heating_policy import SpaceHeatingPolicy


def test_summer_lockout():
    """Verify that warm weather (>16C) completely suppresses heating."""
    outdoor_warm = [19.0] * 96
    prices = [0.25] * 96
    solar = [2.0] * 96

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor_warm,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=[]
    )

    assert not summary.is_heating_season
    assert "Zomersluiting" in summary.season_status_label
    assert summary.total_heating_kwh_el == 0.0
    assert summary.preheat_hours == 0.0
    assert summary.lockout_hours == 0.0


def test_heating_season_preheat_and_lockouts():
    """Verify that cold weather activates heating with preheat and peak lockouts."""
    outdoor_cold = [7.0] * 96
    prices = [0.22] * 96
    solar = [0.0] * 96

    # Night valley (02:00 to 05:00, slots 8 to 20): cheap price
    for i in range(8, 20):
        prices[i] = 0.15

    # Morning peak lockout (07:00 to 09:30, slots 28 to 38)
    peaks = [{
        "start_idx": 28,
        "end_idx": 37,
        "is_hard_lockout": True,
        "name": "Ochtendspits"
    }]

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor_cold,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=peaks,
        current_room_temp_c=20.0
    )

    assert summary.is_heating_season
    assert "Stookseizoen" in summary.season_status_label
    assert summary.total_heating_kwh_el > 0.0
    assert summary.preheat_hours > 0.0
    assert summary.lockout_hours > 0.0

    # Verify peak lockout slots have 0 kW
    for s_idx in range(28, 38):
        assert summary.slots[s_idx].heating_kw_el == 0.0
        assert summary.slots[s_idx].mode_code == "forced_off"

    # Verify comfort threshold (min room temp >= 19.5C)
    assert summary.min_projected_room_temp_c >= 19.5


def test_dhw_hydraulic_interlock_cv_pause():
    """Verify that during active DHW slots, space heating is strictly 0 kW."""
    outdoor_cold = [5.0] * 96
    prices = [0.20] * 96
    solar = [0.0] * 96
    dhw_slots = [40, 41, 42, 43]  # 10:00 to 11:00 DHW run

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor_cold,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=dhw_slots,
        dynamic_peaks=[]
    )

    for slot_idx in dhw_slots:
        assert summary.slots[slot_idx].heating_kw_el == 0.0


def test_carnot_cop_calculation():
    """Verify temperature-dependent Carnot COP curve."""
    cop_cold = SpaceHeatingPolicy.calculate_carnot_cop(-5.0)
    cop_mild = SpaceHeatingPolicy.calculate_carnot_cop(10.0)
    cop_warm = SpaceHeatingPolicy.calculate_carnot_cop(18.0)

    assert 2.5 <= cop_cold <= 3.8
    assert 4.0 <= cop_mild <= 5.2
    assert cop_warm >= cop_mild


def test_thermal_cost_calculation():
    """Verify that thermal cost accounts for COP and solar surplus."""
    cost_cold_grid = SpaceHeatingPolicy.calculate_thermal_cost(price_eur=0.25, cop=3.0, solar_kw=0.0)
    cost_mild_grid = SpaceHeatingPolicy.calculate_thermal_cost(price_eur=0.25, cop=5.0, solar_kw=0.0)
    cost_solar_mild = SpaceHeatingPolicy.calculate_thermal_cost(price_eur=0.25, cop=5.0, solar_kw=2.5)

    assert cost_cold_grid > cost_mild_grid
    assert cost_mild_grid > cost_solar_mild
    assert cost_solar_mild <= 0.02


def test_dynamic_thermostat_setpoint():
    """Verify that custom thermostat setpoint (e.g. 21.0C) shifts comfort boundaries."""
    outdoor_cold = [6.0] * 96
    prices = [0.22] * 96
    solar = [0.0] * 96

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor_cold,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=[],
        current_room_temp_c=21.0,
        target_room_temp_c=21.0
    )

    assert summary.target_room_temp_c == 21.0
    assert summary.min_comfort_room_c == 20.5
    assert summary.max_preheat_room_c == 22.2
    assert summary.min_projected_room_temp_c >= 20.5


def test_winter_sun_and_evening_peak_buffering():
    """
    Cold winter day (4C) with midday sun and an expensive evening peak (17:00 - 20:30, 0.40 EUR/kWh,
    0.36 afterwards). Pre-heating before the peak is cheaper than recovering after it, so the planner
    raises the setpoint beforehand and the house coasts through the lockout within comfort.
    """
    outdoor = [4.0] * 96
    prices = [0.24] * 96
    solar = [0.0] * 96

    # Solar between 11:00 and 15:00 (slots 44 to 60)
    for i in range(44, 60):
        solar[i] = 2.8
        prices[i] = 0.18
    for i in range(68, 83):
        prices[i] = 0.40
    for i in range(83, 96):
        prices[i] = 0.36

    # Evening peak lockout (17:00 to 20:30, slots 68 to 82)
    peaks = [{
        "start_idx": 68,
        "end_idx": 82,
        "is_hard_lockout": True,
        "name": "Avondpiek"
    }]

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=peaks,
        current_room_temp_c=20.0,
        current_floor_temp_c=21.5,
        target_room_temp_c=20.0
    )

    # Verify preheat active in midday solar window before peak
    preheat_in_solar = [summary.slots[i].is_preheat_active for i in range(48, 68)]
    assert any(preheat_in_solar), "Preheat buffer must be scheduled before the evening peak"

    # Verify evening peak is strictly forced off
    for s_idx in range(68, 83):
        assert summary.slots[s_idx].heating_kw_el == 0.0
        assert summary.slots[s_idx].mode_code == "forced_off"

    # Coasting through peak: room temp must stay above min comfort (summary.min_comfort_room_c = 19.5C)
    peak_room_temps = [summary.slots[s_idx].room_temp_c for s_idx in range(68, 83)]
    assert min(peak_room_temps) >= summary.min_comfort_room_c, f"Room dropped to {min(peak_room_temps)}C during peak!"


def test_space_heating_disabled_by_thermostat():
    """Verify that when thermostat or circuit is off, heating is strictly 0.0 kW."""
    outdoor_cold = [5.0] * 96
    prices = [0.15] * 96
    solar = [0.0] * 96

    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor_cold,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=[],
        current_room_temp_c=18.5,
        is_heating_enabled=False
    )

    assert not summary.is_heating_season
    assert "Uitgeschakeld" in summary.season_status_label
    assert summary.total_heating_kwh_el == 0.0
    for s in summary.slots:
        assert s.heating_kw_el == 0.0


def test_space_heating_wind_infiltration():
    """Verify that strong wind increases heat loss and floor/room temperature cooling."""
    outdoor = [8.0] * 96
    prices = [0.20] * 96
    solar = [0.0] * 96

    # Case A: Calm wind (1 m/s)
    summary_calm = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=[],
        current_room_temp_c=20.0,
        current_floor_temp_c=21.0,
        wind_speeds_ms=[1.0] * 96,
        is_heating_enabled=False  # Compare passive drift
    )

    # Case B: Gale wind (12 m/s = ~6 Bft)
    summary_gale = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor,
        prices_eur=prices,
        solar_kw=solar,
        active_dhw_slots=[],
        dynamic_peaks=[],
        current_room_temp_c=20.0,
        current_floor_temp_c=21.0,
        wind_speeds_ms=[12.0] * 96,
        is_heating_enabled=False  # Compare passive drift
    )

    # With higher wind, envelope loss is higher, so final room temp is lower
    assert summary_gale.slots[-1].room_temp_c < summary_calm.slots[-1].room_temp_c


def test_thermal_step_never_overshoots_passive_exchange():
    """
    Passive floor->room exchange can never make the room warmer than the floor that heats it.
    Single-step Euler with R_floor_air*C_air ~ 15 min did (2026-10-12 review: room 24.08 > floor 23.56).
    """
    t_room, t_floor = SpaceHeatingPolicy._advance_thermal_state(19.49, 24.5, 0.0, 0.0, 6.2, 0.2926, 0.25)
    assert t_room <= t_floor
    assert 19.49 < t_room and t_floor < 24.5


def test_thermal_step_resolution_parity():
    """AGENTS.md rule 8: 96 quarter-hour steps and 24 hourly steps must describe the same physics."""
    q = (19.5, 22.0)
    h = (19.5, 22.0)
    for _ in range(96):
        q = SpaceHeatingPolicy._advance_thermal_state(q[0], q[1], 3.0, 0.0, 6.0, 0.2926, 0.25)
    for _ in range(24):
        h = SpaceHeatingPolicy._advance_thermal_state(h[0], h[1], 3.0, 0.0, 6.0, 0.2926, 1.0)
    assert abs(q[0] - h[0]) < 0.01
    assert abs(q[1] - h[1]) < 0.01


def test_small_floor_heat_flows_are_not_rounded_away():
    """Rounding the state to 0.01 K per slot used to freeze any floor flow below ~0.26 kW."""
    _, t_floor = SpaceHeatingPolicy._advance_thermal_state(20.0, 20.2, 0.0, 0.0, 20.0, 0.2926, 0.25)
    assert t_floor < 20.195


def test_plan_passive_drift_is_resolution_independent():
    """Same unheated day planned at 15-min and 1-h resolution: room temperatures agree at every hour."""
    out_15m = [6.0 + 0.1 * (i // 4) for i in range(96)]
    out_1h = [6.0 + 0.1 * i for i in range(24)]
    kwargs = dict(active_dhw_slots=[], dynamic_peaks=[], current_room_temp_c=20.0,
                  current_floor_temp_c=21.5, is_heating_enabled=False)
    s15 = SpaceHeatingPolicy.plan_space_heating(out_15m, [0.25] * 96, [0.0] * 96, step_hours=0.25, **kwargs)
    s1h = SpaceHeatingPolicy.plan_space_heating(out_1h, [0.25] * 24, [0.0] * 24, step_hours=1.0, **kwargs)
    for hour in range(24):
        assert abs(s15.slots[hour * 4].room_temp_c - s1h.slots[hour].room_temp_c) <= 0.02
        assert abs(s15.slots[hour * 4].floor_temp_c - s1h.slots[hour].floor_temp_c) <= 0.02


def test_no_preheat_when_it_does_not_pay_and_comfort_holds():
    """Flat prices and a short lockout the house can coast through: "no pre-heat" must win."""
    peaks = [{"start_idx": 68, "end_idx": 77, "is_hard_lockout": True, "name": "Avondpiek"}]
    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=[8.0] * 96, prices_eur=[0.25] * 96, solar_kw=[0.0] * 96, active_dhw_slots=[],
        dynamic_peaks=peaks, current_room_temp_c=20.5, current_floor_temp_c=22.0, target_room_temp_c=20.5)
    assert summary.preheat_hours == 0.0
    assert all(summary.slots[i].heating_kw_el == 0.0 for i in range(68, 78))
    assert min(summary.slots[i].room_temp_c for i in range(68, 79)) >= summary.min_comfort_room_c


def test_daikin_law_follows_weather_room_and_floor():
    """Mean heat output rises when colder, when the room is below setpoint, and falls as the floor warms."""
    q = SpaceHeatingPolicy.daikin_heat_output_kw
    # Around equilibrium at 5 C the floor sits near 25 C (manifold 24-26 C on 2026-10-11/12)
    assert q(0.0, 20.5, 20.5, 25.0) > q(10.0, 20.5, 20.5, 25.0) > 0.0
    assert q(5.0, 21.5, 20.5, 25.0) > q(5.0, 20.5, 20.5, 25.0)        # +1 K setpoint (pre-heat)
    assert q(5.0, 20.5, 20.5, 26.0) < q(5.0, 20.5, 20.5, 25.0)        # warmer floor takes less heat
    assert q(5.0, 20.5, 20.5, 20.0) == SpaceHeatingPolicy.DAIKIN_MAX_HEAT_KW  # cold floor: full output
    assert q(5.0, 20.5, 23.0, 25.0) == 0.0                             # room far above setpoint


def test_measured_cop_curve():
    cop = SpaceHeatingPolicy.calculate_cop
    assert cop(-2.0) == pytest.approx(2.42)
    assert cop(6.0) == pytest.approx(3.56)
    assert cop(-10.0) >= SpaceHeatingPolicy.COP_BOUNDS[0]
    assert cop(2.0) < cop(6.0) < cop(10.0) < cop(14.0)


def test_lockout_recovery_runs_long_and_low_not_in_blocks():
    """No artificial 2-hour blocks: at 6 C the Daikin heats almost continuously at moderate power."""
    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=[6.0] * 96, prices_eur=[0.25] * 96, solar_kw=[0.0] * 96, active_dhw_slots=[],
        dynamic_peaks=[], current_room_temp_c=20.5, current_floor_temp_c=23.0, target_room_temp_c=20.5)
    heated = [s for s in summary.slots[16:] if s.heating_kw_el > 0.05]
    assert len(heated) >= 70                                  # heat in most slots after the first 4 h
    assert max(s.heating_kw_el for s in heated) < 2.0         # moderate electric power, no 2.8-3.2 kW boost


def test_daytime_buffering_skips_expensive_shoulder_and_saves_evening_load():
    """
    Daytime solar/COP window (12:00-16:00) followed by an expensive pre-peak shoulder (16:00-18:00, P75_ADVIES)
    and hard evening lockout (18:00-20:30): pre-heating must happen in the daytime window before the shoulder,
    avoiding the shoulder completely and reducing evening/night consumption.
    """
    outdoor = [1.0] * 32 + [3.0] * 16 + [6.0] * 16 + [3.0] * 8 + [2.0] * 10 + [1.0] * 14
    prices = [0.22] * 32 + [0.24] * 16 + [0.16] * 16 + [0.28] * 8 + [0.42] * 10 + [0.26] * 14
    solar = [0.0] * 44 + [1.5] * 4 + [2.8] * 12 + [0.5] * 4 + [0.0] * 32
    peaks = [{
        "start_idx": 64,
        "end_idx": 81,
        "hard_start_idx": 72,
        "hard_end_idx": 81,
        "is_hard_lockout": True,
        "name": "Avondspits"
    }]
    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=outdoor, prices_eur=prices, solar_kw=solar,
        active_dhw_slots=[], dynamic_peaks=peaks,
        current_room_temp_c=20.5, current_floor_temp_c=23.5, target_room_temp_c=20.5
    )
    assert any(summary.slots[i].is_preheat_active for i in range(44, 64))
    assert not any(summary.slots[i].is_preheat_active for i in range(64, 72))
    assert all(summary.slots[i].heating_kw_el == 0.0 for i in range(64, 82))


def test_autonomous_start_only_at_setpoint_minus_05c():
    """
    When the room starts above setpoint (or after a preheat/lockout while above setpoint - 0.5 C),
    the heat pump stays off in normal mode until T_room drops to setpoint - 0.5 C (min_comfort_room).
    """
    summary = SpaceHeatingPolicy.plan_space_heating(
        outdoor_temps_c=[9.0] * 48,
        prices_eur=[0.25] * 48,
        solar_kw=[0.0] * 48,
        active_dhw_slots=[],
        dynamic_peaks=[],
        current_room_temp_c=21.2,
        current_floor_temp_c=20.8,
        target_room_temp_c=20.5,
    )
    first_heat_idx = next((i for i, s in enumerate(summary.slots) if s.heating_kw_el > 0.05), None)
    assert first_heat_idx is not None
    assert first_heat_idx > 10
    # Before first_heat_idx, room is cooling down from 21.2 C toward 20.0 C (setpoint - 0.5 C) with 0 kW
    assert all(summary.slots[i].heating_kw_el == 0.0 for i in range(first_heat_idx))
    assert summary.slots[first_heat_idx].room_temp_c <= summary.min_comfort_room_c + 0.06


def test_configurable_modulation_floor_and_startup_variables():
    """Verify that modulation floor and startup envelope variables are exposed and configurable."""
    assert SpaceHeatingPolicy.MOD_FLOOR_MIN_W == 700.0
    assert SpaceHeatingPolicy.MOD_FLOOR_REF_10C_W == 730.0
    assert SpaceHeatingPolicy.STARTUP_PEAK_REF_10C_W == 1050.0

    # At 10C outdoor with minimal drive, slot 1 starts near floor (~0.76 kW) and steady state settles at ~0.73 kW
    p_slot1 = SpaceHeatingPolicy.calculate_run_power_kw(10.0, slot_in_run=1, q_drive_th_kw=1.0)
    p_slot2 = SpaceHeatingPolicy.calculate_run_power_kw(10.0, slot_in_run=2, q_drive_th_kw=1.0)
    p_steady = SpaceHeatingPolicy.calculate_run_power_kw(10.0, slot_in_run=12, q_drive_th_kw=1.0)

    assert 0.70 <= p_slot1 <= 0.85
    assert 0.95 <= p_slot2 <= 1.15
    assert 0.70 <= p_steady <= 0.78

    # Custom parameter override via params dict
    custom_p = {"mod_floor_min_w": 650.0, "mod_floor_ref_10c_w": 650.0, "startup_peak_ref_10c_w": 950.0}
    p_custom = SpaceHeatingPolicy.calculate_run_power_kw(10.0, slot_in_run=15, q_drive_th_kw=1.0, params=custom_p)
    assert p_custom == pytest.approx(0.65, abs=0.02)


