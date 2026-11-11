"""
Integrations: Daikin Altherma Telemetry Reader
==============================================
Reads raw hardware states and temperatures from P1P2 MQTT bridge or HA states.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from layer2_calibration.floor_state_estimator import FloorCircuitObservation


@dataclass
class DaikinTelemetry:
    tank_temperature_c: Optional[float]
    outdoor_temperature_c: Optional[float]
    room_temperature_c: Optional[float]
    flow_temperature_c: Optional[float]
    electrical_power_w: float
    heat_power_w: float
    current_mode: str
    cv_master_switch_on: bool
    is_heating_enabled: bool = True


class DaikinReader:
    """Telemetry parser and reader for Daikin Altherma."""

    @classmethod
    def parse_raw_state(cls, state_dict: Dict[str, Any]) -> DaikinTelemetry:
        return DaikinTelemetry(
            tank_temperature_c=state_dict.get("tank_temperature_c"),
            outdoor_temperature_c=state_dict.get("outdoor_temperature_c"),
            room_temperature_c=state_dict.get("room_temperature_c"),
            flow_temperature_c=state_dict.get("flow_temperature_c"),
            electrical_power_w=float(state_dict.get("electrical_power_w", 0.0)),
            heat_power_w=float(state_dict.get("heat_power_w", 0.0)),
            current_mode=str(state_dict.get("current_mode", "standby")),
            cv_master_switch_on=bool(state_dict.get("cv_master_switch_on", True)),
            is_heating_enabled=bool(state_dict.get("is_heating_enabled", True))
        )

    @classmethod
    def is_space_heating_circuit_enabled(cls, states_map: Dict[str, Any], cv_forced_off_by_hems: bool = False) -> bool:
        """
        Determines if space heating (CV) is physically and logically enabled in Home Assistant.
        Multi-Entity Rule: If ANY authoritative heating entity reports 'off', heating is disabled.
        Authoritative entities:
          1. switch.hc_mode_altherma_on (Master Daikin Climate Enable switch)
          2. climate.hc_room_room_heating (Daikin Room Heating Circuit)
          3. climate.woonkamer_climate_daikin (Living Room Thermostat)
        """
        if not states_map:
            return True

        master_sw = states_map.get("switch.hc_mode_altherma_on", {}).get("state")
        if master_sw == "off" and not cv_forced_off_by_hems:
            # Off by the user. When Open HEMS switched it off for the DHW interlock, heating stays enabled.
            return False

        circuit = states_map.get("climate.hc_room_room_heating", {}).get("state")
        if circuit == "off" and not cv_forced_off_by_hems:
            # Note: on the P1P2 bus, climate.hc_room_room_heating automatically reports 'off' whenever
            # switch.hc_mode_altherma_on is turned off by Open HEMS for the DHW hydraulic interlock.
            return False

        thermostat = states_map.get("climate.woonkamer_climate_daikin", {}).get("state")
        if thermostat == "off":
            return False

        return True

    @classmethod
    def is_dhw_circuit_enabled(cls, states_map: Dict[str, Any]) -> bool:
        """
        Determines if Domestic Hot Water (DHW / Tapwater) is enabled.
        Respects 'uit = uit': if the boiler is turned off on the heat pump or in HA
        (climate.hc_dhw_dhw_setpoint == 'off', binary_sensor.hc_dhw_dhw == 'off',
        or input_boolean.vacation_mode == 'on'), DHW is disabled.
        """
        if not states_map:
            return True
        if states_map.get("climate.hc_dhw_dhw_setpoint", {}).get("state") == "off":
            return False
        if states_map.get("binary_sensor.hc_dhw_dhw", {}).get("state") == "off":
            return False
        if states_map.get("input_boolean.vacation_mode", {}).get("state") == "on":
            return False
        return True


# ----------------------------------------------------------------------------
# Live telemetry helpers (entity ids live here, never in core layers)
# ----------------------------------------------------------------------------
DHW_TANK_TEMP_ENTITY = "sensor.hc_dhw_temperature_r5t_dhw_tank"
HEAT_PUMP_POWER_ENTITY = "sensor.warmtepomp_power"
DHW_DEMAND_ENTITY = "binary_sensor.hc_dhw_dhw_demand"
DHW_VALVE_ENTITY = "binary_sensor.hc_dhw_valve_dhw_tank"
CV_MASTER_SWITCH_ENTITY = "switch.hc_mode_altherma_on"
ROOM_CLIMATE_ENTITY = "climate.woonkamer_climate_daikin"
# Room heating circuit of the Daikin (P1P2): the setpoint Open HEMS reads and writes for floor pre-heat
ROOM_HEATING_CIRCUIT_ENTITY = "climate.hc_room_room_heating"
ROOM_SETPOINT_STEP_C = 0.5
WRITE_BUDGET_ENTITY = "number.hc_bridge_write_budget"
MADOKA_ROOM_SENSOR_ENTITY = "sensor.hc_sensors_temperature_room"
COMPRESSOR_ENTITY = "binary_sensor.hc_mode_compressor"
HEAT_OUTPUT_ENTITY = "sensor.hc_power_production_heatpump"
# UniPi loop sensors on the underfloor-heating manifold (its circulation pump always runs)
FLOOR_MANIFOLD_ENTITIES = tuple(f"sensor.warmtepomp_vloerverwarming_sensor_{i}" for i in range(1, 8))

_INVALID_STATES = (None, "", "unknown", "unavailable", "none")


def _as_float(raw: Any, lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
    if raw in _INVALID_STATES:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if (lo is not None and val < lo) or (hi is not None and val > hi):
        return None
    return val


@dataclass
class DhwActivity:
    """Snapshot of DHW-relevant telemetry. None means: not measured / invalid (never invented)."""
    tank_temp_c: Optional[float]
    power_w: Optional[float]
    valve_on: bool
    cv_master_on: Optional[bool]

    @property
    def compressor_heating_dhw(self) -> bool:
        """Telemetry-only run detection: 3-way valve on DHW AND compressor drawing power."""
        return bool(self.valve_on and self.power_w is not None and self.power_w > 600.0)


@dataclass
class RoomClimate:
    room_temp_c: Optional[float]
    setpoint_c: Optional[float]
    write_budget: Optional[float] = None


def read_dhw_activity(states_map: Dict[str, Any]) -> DhwActivity:
    states_map = states_map or {}
    tank = _as_float(states_map.get(DHW_TANK_TEMP_ENTITY, {}).get("state"), 10.0, 95.0)
    power = _as_float(states_map.get(HEAT_PUMP_POWER_ENTITY, {}).get("state"), 0.0, 25000.0)
    valve_st = states_map.get(DHW_VALVE_ENTITY, {}).get("state")
    if valve_st in ("on", "off"):
        valve = (valve_st == "on")
    else:
        valve = (states_map.get(DHW_DEMAND_ENTITY, {}).get("state") == "on")
    cv_raw = states_map.get(CV_MASTER_SWITCH_ENTITY, {}).get("state")
    cv_on = True if cv_raw == "on" else (False if cv_raw == "off" else None)
    return DhwActivity(tank_temp_c=tank, power_w=power, valve_on=valve, cv_master_on=cv_on)


def read_room_climate(states_map: Dict[str, Any]) -> RoomClimate:
    """Room temperature from the Madoka (the heat pump controls on it); setpoint from the room heating circuit."""
    states_map = states_map or {}
    attrs = states_map.get(ROOM_CLIMATE_ENTITY, {}).get("attributes", {}) or {}
    room = _as_float(attrs.get("current_temperature"), 5.0, 40.0)
    circuit_attrs = states_map.get(ROOM_HEATING_CIRCUIT_ENTITY, {}).get("attributes", {}) or {}
    setpoint = _as_float(circuit_attrs.get("temperature"), 5.0, 30.0)
    if setpoint is None:
        setpoint = _as_float(states_map.get("sensor.hc_room_room_heating_setpoint", {}).get("state"), 5.0, 30.0)
    write_budget = _as_float(states_map.get(WRITE_BUDGET_ENTITY, {}).get("state"), 0.0, 1000.0)
    return RoomClimate(room_temp_c=room, setpoint_c=setpoint, write_budget=write_budget)


def room_setpoint_service_call(setpoint_c: float) -> Tuple[str, str, Dict[str, Any]]:
    """HA service call (domain, service, data) that sets the room heating setpoint, snapped to the unit's step."""
    snapped = round(round(float(setpoint_c) / ROOM_SETPOINT_STEP_C) * ROOM_SETPOINT_STEP_C, 1)
    return "climate", "set_temperature", {"entity_id": ROOM_HEATING_CIRCUIT_ENTITY, "temperature": snapped}


def _parse_last_changed(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None


def read_floor_circuit(states_map: Dict[str, Any], now: datetime) -> FloorCircuitObservation:
    """
    Snapshot for the floor state estimator: manifold loop temperatures, compressor and 3-way valve state,
    and the measured heat output. minutes_since_state_change counts from the latest change of the compressor
    or valve (HA last_changed), so it never overstates how long the circuit has been without CV heat.

    The 3-way valve position decides where the heat goes. DHW *demand* is not used when the valve is
    readable: it stayed 'on' during 9 % of CV-heating minutes (2026-09-28..10-12, e.g. 10-08 15:30 at
    LWT 30 C), whereas the valve was 'on' in 99 % of DHW-run minutes and 1 % of CV-run minutes.
    """
    states_map = states_map or {}
    temps = tuple(_as_float(states_map.get(e, {}).get("state"), 5.0, 60.0) for e in FLOOR_MANIFOLD_ENTITIES)
    comp_raw = states_map.get(COMPRESSOR_ENTITY, {}).get("state")
    compressor_on = True if comp_raw == "on" else (False if comp_raw == "off" else None)
    heat_w = _as_float(states_map.get(HEAT_OUTPUT_ENTITY, {}).get("state"), -20000.0, 30000.0)

    dhw_entity = DHW_VALVE_ENTITY
    if states_map.get(DHW_VALVE_ENTITY, {}).get("state") not in ("on", "off"):
        dhw_entity = DHW_DEMAND_ENTITY  # valve unreadable: demand is the only DHW signal left
    dhw_active = states_map.get(dhw_entity, {}).get("state") == "on"

    minutes = None
    if compressor_on is not None and now.tzinfo is not None:
        changes = [
            _parse_last_changed(states_map.get(e, {}).get("last_changed"))
            for e in (COMPRESSOR_ENTITY, dhw_entity)
        ]
        known = [c for c in changes if c is not None]
        if known:
            minutes = max(0.0, (now - max(known)).total_seconds() / 60.0)

    room = read_room_climate(states_map).room_temp_c
    if room is None:
        room = _as_float(states_map.get(MADOKA_ROOM_SENSOR_ENTITY, {}).get("state"), 5.0, 40.0)

    return FloorCircuitObservation(
        timestamp=now,
        manifold_temps_c=temps,
        compressor_on=compressor_on,
        dhw_active=dhw_active,
        minutes_since_state_change=minutes,
        heat_output_kw=heat_w / 1000.0 if heat_w is not None else None,
        room_temp_c=room,
    )
