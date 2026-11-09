"""
Open HEMS Site-Specific Adapter: Daikin Altherma P1P2 State Classifier & Power Disaggregator.
Author: Open HEMS Core Architecture
License: Apache-2.0

Separation Principle:
This module contains site- and hardware-specific classification logic for Daikin Altherma 3 H HT
via P1P2-bridge telemetry and HA entity fallbacks. It is cleanly isolated in `site_adapters/`
so that Open HEMS Core models and scheduling layers remain generic and modular.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class HeatPumpDisaggregation:
    mode: str                    # 'DHW', 'HEATING', 'COOLING', 'STANDBY'
    total_power_w: float
    dhw_w: float
    heating_w: float
    cooling_w: float
    standby_w: float
    confidence: float
    source: str                  # 'mqtt_p1p2', 'ha_entities', 'power_threshold'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "total_power_w": round(self.total_power_w, 1),
            "dhw_w": round(self.dhw_w, 1),
            "heating_w": round(self.heating_w, 1),
            "cooling_w": round(self.cooling_w, 1),
            "standby_w": round(self.standby_w, 1),
            "confidence": self.confidence,
            "source": self.source
        }


class DaikinP1P2StateClassifier:
    """
    Evaluates raw physical inputs from Daikin P1P2 MQTT bridge topics and
    Home Assistant fallback entities to classify current heat pump operational state
    and disaggregate actual electrical power draw into pure physical buckets.
    """

    STANDBY_THRESHOLD_W = 48.0  # Daikin Altherma standby is typically 30-36 W

    @classmethod
    def classify(
        cls,
        total_power_w: float,
        mqtt_cache: Optional[Dict[str, Any]] = None,
        ha_states: Optional[Dict[str, Any]] = None
    ) -> HeatPumpDisaggregation:
        mqtt_cache = mqtt_cache or {}
        ha_states = ha_states or {}
        p_tot = max(0.0, float(total_power_w))

        # 1. Extract MQTT P1P2 Signals & Home Assistant Signals (supports both raw string and state dict)
        def _clean_mqtt(val: Any) -> str:
            if val is None:
                return ""
            if isinstance(val, float) and val.is_integer():
                return str(int(val))
            return str(val).strip()

        def _clean_ha(eid: str) -> str:
            raw = ha_states.get(eid)
            if isinstance(raw, dict):
                raw = raw.get("state")
            if raw is None:
                return ""
            return str(raw).strip().lower()

        p1p2_action = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/C/9/Action_Heating_Cooling_Auto_Off")).lower()
        p1p2_compressor = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/S/1/Compressor"))
        p1p2_dhw_demand = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/S/1/DHW_Demand"))
        p1p2_valve_dhw = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/S/1/Valve_DHW_Tank"))
        p1p2_climate_heat = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/S/1/Climate_Heating"))
        p1p2_climate_cool = _clean_mqtt(mqtt_cache.get("P1P2/P/P1P2MQTT/bridge0/S/1/Climate_Cooling"))

        ha_select = _clean_ha("select.daily_energy_usage_sums_wp")
        ha_compressor = _clean_ha("binary_sensor.hc_mode_compressor")
        ha_dhw_valve = _clean_ha("binary_sensor.hc_dhw_valve_dhw_tank")
        ha_dhw_demand = _clean_ha("binary_sensor.hc_dhw_dhw_demand")
        ha_heat_mode = _clean_ha("binary_sensor.hc_mode_climate_heating")
        ha_cool_mode = _clean_ha("binary_sensor.hc_mode_climate_cooling")

        # 2. Primary Deterministic State Resolution via HA Utility Meter Selector (`select.daily_energy_usage_sums_wp`)
        #    Driven by HA automation 'Heatpump - MQTT - Publish selected ACTION' using pure binary sensors:
        #    - compressor == 'off' -> 'standby'
        #    - compressor == 'on' and valve_dhw == 'on' -> 'dhw'
        #    - compressor == 'on' and climate_heating == 'on' and valve_dhw == 'off' -> 'heating'
        #    - compressor == 'on' and climate_cooling == 'on' and valve_dhw == 'off' -> 'cooling'
        if ha_select in ("standby", "dhw", "heating", "cooling"):
            mode_upper = ha_select.upper()
            return HeatPumpDisaggregation(
                mode=mode_upper,
                total_power_w=p_tot,
                dhw_w=p_tot if mode_upper == "DHW" else 0.0,
                heating_w=p_tot if mode_upper == "HEATING" else 0.0,
                cooling_w=p_tot if mode_upper == "COOLING" else 0.0,
                standby_w=p_tot if mode_upper == "STANDBY" else 0.0,
                confidence=1.0,
                source="ha_entities"
            )

        # 3. Direct Deterministic Binary State Evaluation (when select entity is absent from snapshot):
        #    Check compressor OFF first (pure state, no power thresholds needed when compressor state is known)
        comp_known = (p1p2_compressor in ("0", "1")) or (ha_compressor in ("on", "off")) or (p1p2_action in ("idle", "off", "fan", "heating", "cooling"))
        if comp_known:
            is_comp_off = (p1p2_compressor == "0") or (ha_compressor == "off") or (p1p2_action in ("idle", "off"))
            if is_comp_off:
                return HeatPumpDisaggregation(
                    mode="STANDBY",
                    total_power_w=p_tot,
                    dhw_w=0.0,
                    heating_w=0.0,
                    cooling_w=0.0,
                    standby_w=p_tot,
                    confidence=0.98,
                    source="mqtt_p1p2" if (p1p2_compressor or p1p2_action) else "ha_entities"
                )
        elif p_tot < cls.STANDBY_THRESHOLD_W:
            # Fallback only when no binary compressor state is provided at all
            return HeatPumpDisaggregation(
                mode="STANDBY",
                total_power_w=p_tot,
                dhw_w=0.0,
                heating_w=0.0,
                cooling_w=0.0,
                standby_w=p_tot,
                confidence=1.0,
                source="power_threshold"
            )

        # Decision Tree (Compressor is ON):
        # A. DHW Tank Heating Mode: authoritative signal is the physical 3-way valve (Valve_DHW_Tank).
        valve_known = (p1p2_valve_dhw in ("0", "1")) or (ha_dhw_valve in ("on", "off"))
        if valve_known:
            is_dhw = (p1p2_valve_dhw == "1") or (ha_dhw_valve == "on")
        else:
            is_dhw = (
                p1p2_action == "fan" or
                p1p2_dhw_demand == "1" or
                ha_dhw_demand == "on"
            )
        if is_dhw:
            return HeatPumpDisaggregation(
                mode="DHW",
                total_power_w=p_tot,
                dhw_w=p_tot,
                heating_w=0.0,
                cooling_w=0.0,
                standby_w=0.0,
                confidence=0.98 if p1p2_action or p1p2_dhw_demand else 0.90,
                source="mqtt_p1p2" if p1p2_action or p1p2_dhw_demand else "ha_entities"
            )

        # B. Cooling Mode
        is_cooling = (
            p1p2_action == "cooling" or
            p1p2_climate_cool == "1" or
            ha_cool_mode == "on" or
            ha_select == "cooling"
        )
        if is_cooling:
            return HeatPumpDisaggregation(
                mode="COOLING",
                total_power_w=p_tot,
                dhw_w=0.0,
                heating_w=0.0,
                cooling_w=p_tot,
                standby_w=0.0,
                confidence=0.98 if p1p2_action or p1p2_climate_cool else 0.90,
                source="mqtt_p1p2" if p1p2_action or p1p2_climate_cool else "ha_entities"
            )

        # C. Space Heating (CV) Mode
        is_heating = (
            p1p2_action == "heating" or
            p1p2_climate_heat == "1" or
            ha_heat_mode == "on" or
            ha_select == "heating"
        )
        if is_heating:
            return HeatPumpDisaggregation(
                mode="HEATING",
                total_power_w=p_tot,
                dhw_w=0.0,
                heating_w=p_tot,
                cooling_w=0.0,
                standby_w=0.0,
                confidence=0.98 if p1p2_action or p1p2_climate_heat else 0.90,
                source="mqtt_p1p2" if p1p2_action or p1p2_climate_heat else "ha_entities"
            )

        # D. Explicit Standby / Idle
        if p1p2_action in ["idle", "off"] or ha_compressor == "off" or ha_select == "standby":
            return HeatPumpDisaggregation(
                mode="STANDBY",
                total_power_w=p_tot,
                dhw_w=0.0,
                heating_w=0.0,
                cooling_w=0.0,
                standby_w=p_tot,
                confidence=0.95,
                source="mqtt_p1p2" if p1p2_action else "ha_entities"
            )

        # Default: if power is draw (>48W) and no signal matched, assume heating
        return HeatPumpDisaggregation(
            mode="HEATING",
            total_power_w=p_tot,
            dhw_w=0.0,
            heating_w=p_tot,
            cooling_w=0.0,
            standby_w=0.0,
            confidence=0.60,
            source="fallback_inferred"
        )
