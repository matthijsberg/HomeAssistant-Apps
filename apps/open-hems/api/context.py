import sys
from pathlib import Path
import json
import urllib.parse
import urllib.request
import urllib.error
import threading
import time
from typing import Any, Dict, Optional

ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from layer1_data_collection.sanitizer import TelemetrySanitizer
from layer3_scheduling.central_planner import CentralPlanner
from layer3_scheduling.plan_store import get_plan_store

from layer2_calibration.learned_forecaster import HybridForecastingModel
from layer2_calibration.dhw_thermal_model import DhwThermalModel
from layer2_calibration.floor_state_estimator import FloorStateEstimate, estimate_floor_state

GLOBAL_MODEL = HybridForecastingModel()
GLOBAL_DHW_MODEL = DhwThermalModel()

GLOBAL_COLLECTOR = None

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

# Site-specific adapters (decoupled from core engine)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/addons/open-hems")
sys.path.insert(0, "/opt/open-hems")

from api.secrets_store import (
    CONFIG_FILE, PARAMS_FILE, load_json
)
from api.http_client import safe_urlopen
from integrations.homeassistant.client import (
    get_ha_states_map
)
from api.energy_feed import (
    calculate_poa_solar_kw, get_epex_tariffs_cached
)
from layer3_scheduling.plan_decision_evaluator import evaluate_and_log_planner_decisions

def get_web_dir() -> Path:
    """Dynamically resolves the active web directory for instant hot-reloading during development."""
    # 1. Direct host config mount (instant hot-reload if mapped)
    live_config_web = Path("/config/addons/open-hems/web")
    if (live_config_web / "index.html").exists():
        return live_config_web
    # 2. Shared storage mount
    live_share_web = Path("/share/addons/open-hems/web")
    if (live_share_web / "index.html").exists():
        return live_share_web
    # 3. Built-in container web dir fallback
    return Path(__file__).resolve().parent.parent / "web"

WEB_DIR = get_web_dir()
INDEX_HTML_PATH = WEB_DIR / "index.html"


GLOBAL_CENTRAL_CACHE = {
    "timestamp": 0,
    "15m": None,
    "1h": None
}

from layer1_data_collection.geo_location import get_geo_coordinates

_LAST_PLAN_MONOTONIC: Optional[float] = None
_PLAN_LOCK = threading.Lock()
PLAN_CACHE_SECONDS = 60.0

# Previous floor state estimate; read and written only inside _compute_and_publish_plan (under _PLAN_LOCK)
_LAST_FLOOR_ESTIMATE: Optional[FloorStateEstimate] = None

# Open-Meteo is hourly data; refetching it every planning cycle only burns the rate limit.
_WEATHER_CACHE: Dict[str, Any] = {"key": None, "ts": 0.0, "data": None}
WEATHER_CACHE_SECONDS = 600.0

_INVALID = (None, "", "unknown", "unavailable", "none")


def _state_float(states_map: Dict[str, Any], entity_id: str, lo: float, hi: float) -> Optional[float]:
    raw = states_map.get(entity_id, {}).get("state")
    if raw in _INVALID:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if lo <= val <= hi else None


def _attr_float(states_map: Dict[str, Any], entity_id: str, attr: str, lo: float, hi: float) -> Optional[float]:
    raw = states_map.get(entity_id, {}).get("attributes", {}).get(attr)
    if raw in _INVALID:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if lo <= val <= hi else None


def _plan_is_cached(store) -> bool:
    return (
        store.get_plan() is not None
        and _LAST_PLAN_MONOTONIC is not None
        and (time.monotonic() - _LAST_PLAN_MONOTONIC) < PLAN_CACHE_SECONDS
    )


def ensure_active_canonical_plan(force_refresh=False, horizon_hours=48.0):
    """
    Ensures an authoritative, synchronized CanonicalDispatchPlan is cached in PlanStore.

    Concurrency contract:
    - At most one planning run executes at a time (the lock is held for compute AND publish).
    - Callers that already have a plan never wait for a running replan; they get the current plan.
    - Cache age uses time.monotonic(), so DST transitions and wall-clock jumps cannot freeze it.
    """
    global _LAST_PLAN_MONOTONIC
    store = get_plan_store()
    current_plan = store.get_plan()

    if not force_refresh and _plan_is_cached(store):
        return current_plan

    if current_plan is not None and not force_refresh:
        if not _PLAN_LOCK.acquire(blocking=False):
            return current_plan  # another thread is replanning right now
    else:
        _PLAN_LOCK.acquire()
    try:
        if not force_refresh and _plan_is_cached(store):
            return store.get_plan()
        plan = _compute_and_publish_plan(store, horizon_hours)
        _LAST_PLAN_MONOTONIC = time.monotonic()
        return plan
    finally:
        _PLAN_LOCK.release()


def _fetch_weather(geo_lat, geo_lon, raw_solar, has_solar_plan, s_cfg, s_kwp, s_tilt, s_az, s_inv):
    """Open-Meteo hourly forecast with a short cache. Returns (raw_solar, raw_weather)."""
    key = f"{geo_lat},{geo_lon}"
    now_mono = time.monotonic()
    m_data = None
    if _WEATHER_CACHE["key"] == key and (now_mono - _WEATHER_CACHE["ts"]) < WEATHER_CACHE_SECONDS:
        m_data = _WEATHER_CACHE["data"]
    if m_data is None:
        url_m = f"https://api.open-meteo.com/v1/forecast?latitude={geo_lat}&longitude={geo_lon}&hourly=temperature_2m,shortwave_radiation,wind_speed_10m&timezone=Europe%2FAmsterdam&forecast_days=3"
        req_m = urllib.request.Request(url_m, headers={"User-Agent": "OpenHEMS/1.0"})
        try:
            with safe_urlopen(req_m, timeout=5) as r_m:
                m_data = json.loads(r_m.read().decode())
            _WEATHER_CACHE.update({"key": key, "ts": now_mono, "data": m_data})
        except Exception as e_om:
            if _WEATHER_CACHE.get("data") is not None:
                m_data = _WEATHER_CACHE["data"]
            else:
                raise e_om

    raw_weather = []
    m_times = m_data.get("hourly", {}).get("time", [])
    m_rads = m_data.get("hourly", {}).get("shortwave_radiation", [])
    m_temps = m_data.get("hourly", {}).get("temperature_2m", [])
    m_winds = m_data.get("hourly", {}).get("wind_speed_10m", [])
    s_eff = float(s_cfg.get("efficiency_factor", 0.88))
    try:
        p_disk = load_json(PARAMS_FILE)
        pr_pct = p_disk.get("solar", {}).get("performance_ratio_pct")
        if pr_pct is not None and 50.0 <= float(pr_pct) <= 110.0:
            s_eff = round(float(pr_pct) / 100.0, 4)
    except Exception:
        pass
    ams = ZoneInfo("Europe/Amsterdam")

    existing_solar_times = {s["dt"].strftime("%Y-%m-%d %H:00") for s in raw_solar}
    from datetime import timedelta
    for idx_m, (t, rad, tmp) in enumerate(zip(m_times, m_rads, m_temps)):
        if tmp is None:
            continue
        k_t = t.replace('T', ' ')[:13] + ':00'
        dt_h = datetime.strptime(k_t, "%Y-%m-%d %H:%M").replace(tzinfo=ams)
        next_rad = m_rads[idx_m + 1] if (idx_m + 1 < len(m_rads) and m_rads[idx_m + 1] is not None) else rad
        rad_interval = (0.5 * float(rad or 0.0) + 0.5 * float(next_rad or 0.0)) if rad is not None else 0.0
        if rad is not None and (not has_solar_plan or dt_h.strftime("%Y-%m-%d %H:00") not in existing_solar_times):
            poa_kw = calculate_poa_solar_kw(
                dt_h + timedelta(minutes=30), rad_interval,
                kwp=s_kwp, tilt_deg=s_tilt, azimuth_deg=s_az, inverter_limit_kw=s_inv, eff=s_eff
            )
            raw_solar.append({"dt": dt_h, "solar_kw": poa_kw})
        w_kmh = float(m_winds[idx_m]) if (idx_m < len(m_winds) and m_winds[idx_m] is not None) else 0.0
        raw_weather.append({
            "dt": dt_h,
            "temperature": float(tmp),
            "wind_speed_ms": round(w_kmh / 3.6, 2),
            "solar_radiation_w_m2": round(rad_interval, 1)
        })
    return raw_solar, raw_weather


def _battery_context(cfg: Dict[str, Any], states_map: Dict[str, Any]) -> Dict[str, Any]:
    """Battery presence from config; SoC strictly from live telemetry (None when unavailable)."""
    bat_dev = next(
        (d for d in cfg.get("devices", []) if isinstance(d, dict) and d.get("type") in ("home_battery", "battery", "battery_storage")),
        {}
    )
    installed = bool(bat_dev.get("installed", False) and bat_dev.get("enabled", False))
    soc_entity = bat_dev.get("ha_soc_entity") or cfg.get("battery", {}).get("ha_soc_entity") or "sensor.battery_state_of_charge"
    return {
        "installed": installed,
        # Without an installed battery, keep a clearly labelled what-if plan for the battery views
        # (battery.plan_simulation, default on). It never enters the real energy balance.
        "simulate": bool(cfg.get("simulate_battery", False) or cfg.get("battery", {}).get("plan_simulation", True)),
        "soc_pct": _state_float(states_map, soc_entity, 0.0, 100.0) if installed else None,
        "simulation_initial_soc_pct": float(cfg.get("battery", {}).get("simulation_initial_soc_pct", 50.0)),
    }


def _compute_and_publish_plan(store, horizon_hours: float):
    now_ams = datetime.now(ZoneInfo("Europe/Amsterdam"))

    # 1. Fetch EPEX prices from dedicated Day-Ahead cache (+ price forecast beyond day-ahead)
    raw_prices, _, _ = get_epex_tariffs_cached(is_15m=True)

    # 2. Fetch Solar & Weather Forecast (48-hour rolling horizon)
    horizon_slots = int(horizon_hours * 4)
    cfg = load_json(CONFIG_FILE)
    s_cfg = cfg.get("solar", {})
    s_kwp = float(s_cfg.get("kwp", 5.76))
    s_inv = float(s_cfg.get("inverter_max_w", 5500)) / 1000.0
    s_tilt = float(s_cfg.get("tilt_degrees", 34))
    s_az = float(s_cfg.get("azimuth_degrees", 225))
    s_cal = float(s_cfg.get("calibration_factor", 1.18))
    use_fs = s_cfg.get("forecast_provider", "open_meteo_poa") == "forecast_solar"

    geo_lat, geo_lon = get_geo_coordinates(cfg)
    raw_solar = []
    if use_fs:
        try:
            from layer1_data_collection.forecast_solar import ForecastSolarProvider
            fs_prov = ForecastSolarProvider(
                lat=geo_lat, lon=geo_lon, tilt=s_tilt,
                azimuth_deg_south=s_az - 180.0,
                kwp=s_kwp, inverter_max_kw=s_inv,
                calibration_factor=s_cal
            )
            raw_solar = fs_prov.get_calibrated_quarter_slots(now_ams, horizon_slots=horizon_slots, step_mins=15)
        except Exception as e_fs:
            print(f"Warning fetching Forecast.Solar: {e_fs}")

    has_solar_plan = any(s.get("solar_kw", 0.0) > 0.05 for s in raw_solar)
    if not has_solar_plan:
        raw_solar = []

    raw_weather = []
    try:
        raw_solar, raw_weather = _fetch_weather(geo_lat, geo_lon, raw_solar, has_solar_plan, s_cfg, s_kwp, s_tilt, s_az, s_inv)
    except Exception as e_w:
        print(f"Warning fetching Open-Meteo in ensure_active_canonical_plan: {e_w}")
        if not raw_solar and not use_fs:
            try:
                from layer1_data_collection.forecast_solar import ForecastSolarProvider
                fs_prov = ForecastSolarProvider(
                    lat=geo_lat, lon=geo_lon, tilt=s_tilt,
                    azimuth_deg_south=s_az - 180.0,
                    kwp=s_kwp, inverter_max_kw=s_inv,
                    calibration_factor=s_cal
                )
                raw_solar = fs_prov.get_calibrated_quarter_slots(now_ams, horizon_slots=horizon_slots, step_mins=15)
            except Exception:
                pass

    # 3. One Home Assistant snapshot for this planning run; every sensor is parsed independently
    states_map = get_ha_states_map() or {}
    from integrations.daikin_altherma.reader import DaikinReader, read_dhw_activity
    dhw_activity = read_dhw_activity(states_map)

    cur_dhw = dhw_activity.tank_temp_c if (dhw_activity.tank_temp_c is not None and 20.0 <= dhw_activity.tank_temp_c <= 75.0) else None
    last_hw_time = now_ams if cur_dhw is not None else None

    live_dhw_setpoint = _state_float(states_map, "sensor.hc_dhw_dhw_setpoint", 35.0, 65.0)
    if live_dhw_setpoint is None:
        live_dhw_setpoint = _attr_float(states_map, "climate.hc_dhw_dhw_setpoint", "temperature", 35.0, 65.0)

    # Room reference is the Madoka: the heat pump controls on it. No fallback to other room sensors
    # (the SCO2 sensor reads ~1.4 K lower and would shift every comfort bound).
    cur_room = _attr_float(states_map, "climate.woonkamer_climate_daikin", "current_temperature", 15.0, 35.0)
    if cur_room is None:
        cur_room = _state_float(states_map, "sensor.hc_sensors_temperature_room", 15.0, 35.0)
    from integrations.daikin_altherma.reader import read_room_climate
    from layer4_control.room_thermostat_buffer import get_room_thermostat_buffer_controller
    room_sp = read_room_climate(states_map).setpoint_c
    cur_thermostat_sp = (
        (room_sp if room_sp is not None and 15.0 <= room_sp <= 25.0 else None)
        or _attr_float(states_map, "climate.woonkamer_climate_daikin", "target_temp_low", 15.0, 25.0)
        or 20.0
    )
    buffer_ctrl = get_room_thermostat_buffer_controller()
    cur_baseline_comfort, is_buffering = buffer_ctrl.resolve_effective_baseline(cur_thermostat_sp, now=now_ams)

    # Screed temperature from the manifold loop sensors: a settled reading when no CV heat has flowed for a
    # while, otherwise corrected for the supply-water offset (knowledge/architecture/floor-state-estimation.md)
    global _LAST_FLOOR_ESTIMATE
    from integrations.daikin_altherma.reader import read_floor_circuit
    floor_est = estimate_floor_state(read_floor_circuit(states_map, now_ams), previous=_LAST_FLOOR_ESTIMATE)
    if floor_est is not None:
        _LAST_FLOOR_ESTIMATE = floor_est
        cur_floor = round(floor_est.temp_c, 2)
    else:
        cur_floor = cur_room

    # 3b. Local Microclimate Observation Nudging (Wittboy & Rooftop Inverter)
    live_t_out = None
    for ent in ["sensor.wittboy_gw2000a_weather_station_gw2000a_outdoor_temperature", "sensor.temperatuur_buiten"]:
        live_t_out = _state_float(states_map, ent, -40.0, 50.0)
        if live_t_out is not None:
            break
    live_solar_kw = None
    for ent in ["sensor.zonnepanelen_power_avg_5_minutes", "sensor.inepro_metering_pro_380_active_power"]:
        v = _state_float(states_map, ent, -20000.0, 20000.0)
        if v is not None:
            live_solar_kw = round(abs(v) / 1000.0, 3)
            break
    w_kmh = _state_float(states_map, "sensor.wittboy_gw2000a_weather_station_gw2000a_wind_speed", 0.0, 250.0)
    live_wind_ms = round(w_kmh / 3.6, 2) if w_kmh is not None else None
    live_solar_rad_w_m2 = _state_float(states_map, "sensor.wittboy_gw2000a_weather_station_gw2000a_solar_radiation", 0.0, 1600.0)

    # 4. Circuit enablement (a CV master switched off by our own DHW interlock is not "heating off")
    from layer4_control.dispatch_state import get_dispatch_state
    from integrations.homeassistant.client import CV_FORCED_OFF_KEY
    cv_off_by_hems = bool(get_dispatch_state().get(CV_FORCED_OFF_KEY, False))
    is_cv_enabled = DaikinReader.is_space_heating_circuit_enabled(states_map, cv_forced_off_by_hems=cv_off_by_hems)
    is_dhw_enabled = DaikinReader.is_dhw_circuit_enabled(states_map)

    # 5. Extract unallocated profile
    grid_96 = []
    if GLOBAL_MODEL and GLOBAL_MODEL.profile:
        grid_96 = GLOBAL_MODEL.profile.get("profile_96_quarters", [])

    # 6. Sanitize telemetry and apply Local Microclimate Observation Nudging
    frame = TelemetrySanitizer.sanitize(
        now=now_ams,
        raw_prices=raw_prices,
        raw_solar=raw_solar,
        raw_weather=raw_weather,
        raw_unallocated_matrix=grid_96,
        current_dhw_temp=cur_dhw,
        current_room_temp=cur_room,
        current_floor_temp=cur_floor,
        target_room_temp=cur_baseline_comfort,
        thermostat_setpoint=cur_thermostat_sp,
        is_buffering=is_buffering,
        last_hardware_reading_time=last_hw_time,
        is_space_heating_enabled=is_cv_enabled,
        is_dhw_enabled=is_dhw_enabled,
        live_outdoor_temp_c=live_t_out,
        live_solar_kw=live_solar_kw,
        live_wind_speed_ms=live_wind_ms,
        live_solar_radiation_w_m2=live_solar_rad_w_m2,
        horizon_slots=horizon_slots,
        step_mins=15
    )
    if floor_est is not None:
        frame.metadata["floor_state"] = {
            "temp_c": round(floor_est.temp_c, 2),
            "source": floor_est.source,
            "quality": floor_est.quality.value,
            "manifold_reading_c": round(floor_est.manifold_reading_c, 2) if floor_est.manifold_reading_c is not None else None,
        }

    # 6b. Past lockout duration and dwell time from live relay states (SG1 = S10S off, S11S on)
    past_lockout_mins = 0
    mins_since_last_lockout = 999
    try:
        s10_st = states_map.get("switch.warmtepomp_smart_grid_1_s10s", {})
        s11_st = states_map.get("switch.warmtepomp_smart_grid_2_s11s", {})
        sg_opt = states_map.get("input_select.warmtepomp_smart_grid_modus", {}).get("state")
        s10_on = (s10_st.get("state") == "on")
        s11_on = (s11_st.get("state") == "on")
        is_sg1_active = (not s10_on and s11_on) or (sg_opt == "Geforceerd uit")
        disp_st = get_dispatch_state()
        now_utc_lk = datetime.now(timezone.utc)
        if is_sg1_active:
            lc_str = s11_st.get("last_changed") or states_map.get("input_select.warmtepomp_smart_grid_modus", {}).get("last_changed")
            diff_mins = 1.0
            if lc_str:
                lc_dt = datetime.fromisoformat(lc_str.replace("Z", "+00:00"))
                diff_mins = max(0.0, (now_utc_lk - lc_dt).total_seconds() / 60.0)
            # Never truncate an active lockout (<60s old) to 0 minutes, which would look like 'not locked out + 0m cooldown'
            past_lockout_mins = max(1, int(round(diff_mins)))
            mins_since_last_lockout = 0
            disp_st.set("last_hard_lockout_active_at", now_utc_lk.isoformat())
        else:
            last_lk_iso = disp_st.get("last_hard_lockout_active_at")
            if last_lk_iso:
                lk_dt = datetime.fromisoformat(str(last_lk_iso).replace("Z", "+00:00"))
                mins_since_last_lockout = max(1, int(round((now_utc_lk - lk_dt).total_seconds() / 60.0)))
    except Exception as e_lk:
        print(f"Warning determining lockout history: {e_lk}")

    # 7. Plan & Publish (the in-flight DHW commitment is owned by Layer 4; never armed here)
    model_params = load_json(PARAMS_FILE)
    from layer3_scheduling.dhw_specs import DhwTankSpec
    from layer3_scheduling.dhw_optimizer import DhwOptimizerParams
    dhw_spec = DhwTankSpec.from_config(cfg, live_setpoint_c=live_dhw_setpoint)
    dhw_opt_params = DhwOptimizerParams.from_config(cfg)

    plan = CentralPlanner.plan(
        frame,
        current_dhw_temp=cur_dhw,
        model_parameters=model_params,
        dhw_spec=dhw_spec,
        dhw_optimizer_params=dhw_opt_params,
        past_continuous_lockout_mins=past_lockout_mins,
        mins_since_last_lockout=mins_since_last_lockout,
        store=store,
        dhw_compressor_running=dhw_activity.compressor_heating_dhw,
        battery_context=_battery_context(cfg, states_map),
    )
    try:
        evaluate_and_log_planner_decisions(plan, frame)
    except Exception as e_pld:
        print(f"Warning in evaluate_and_log_planner_decisions: {e_pld}")
    return plan
