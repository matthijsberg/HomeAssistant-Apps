"""
Home Assistant Core REST API Client
===================================
Handles all HTTP communications, entity discovery, and service calls to Home Assistant Core.
"""

import os
import ssl
import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Tuple, Optional, Dict, Any, List

from api.secrets_store import load_secrets, load_json, HA_API_CONFIG
from integrations.daikin_altherma.actuator import DaikinActuator


_WORKING_HA_BASE_URL: Optional[str] = None

# Endpoints on the Home Assistant OS internal network present self-signed certificates.
# Anything else (e.g. a public hostname) must be TLS-verified: the long-lived token travels along.
_INTERNAL_HA_HOSTS = ("172.30.32.1", "homeassistant", "supervisor", "localhost", "127.0.0.1")

CV_FORCED_OFF_KEY = "cv_master_forced_off_by_hems"


def ha_ssl_context(url: Optional[str]) -> ssl.SSLContext:
    """TLS context for a Home Assistant URL: verification is only relaxed for internal hosts."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    ctx = ssl.create_default_context()
    if host in _INTERNAL_HA_HOSTS:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_ha_client_config() -> Tuple[str, str]:
    """
    Returns (ha_url, token) for Home Assistant Core REST API.
    Auto-discovers and caches the responsive endpoint among:
      - Direct internal HA Docker bridge: https://172.30.32.1:8123
      - Direct internal Docker service name: https://homeassistant:8123
      - User-configured URL in secrets
      - http://supervisor/core
    """
    global _WORKING_HA_BASE_URL
    sec = load_secrets()
    ha_sec = sec.get("homeassistant", {})
    token = ha_sec.get("token") or os.environ.get("HASS_TOKEN", "")

    if not token and HA_API_CONFIG.exists():
        cfg = load_json(HA_API_CONFIG)
        token = cfg.get("HASS_TOKEN")

    if not token and os.path.exists("/data/options.json"):
        try:
            with open("/data/options.json") as f:
                opts = json.load(f)
                token = opts.get("homeassistant_token") or token
        except Exception:
            pass

    if _WORKING_HA_BASE_URL is not None:
        return _WORKING_HA_BASE_URL, token

    configured_url = ha_sec.get("url") or os.environ.get("HASS_URL")
    candidates = [
        "https://172.30.32.1:8123",
        "https://homeassistant:8123",
        configured_url,
        "http://supervisor/core",
        "https://hass.b3rg.nl:8123"
    ]
    seen = set()
    uniq_candidates = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            uniq_candidates.append(c)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for candidate in uniq_candidates:
        try:
            req = urllib.request.Request(f"{candidate}/api/states/zone.home", headers=headers)
            with urllib.request.urlopen(req, timeout=1.5, context=ha_ssl_context(candidate)) as r:
                if r.status in [200, 201]:
                    _WORKING_HA_BASE_URL = str(candidate)
                    return _WORKING_HA_BASE_URL, token
        except Exception:
            continue

    default_url = configured_url or "https://172.30.32.1:8123"
    return default_url, token


def fetch_ha_entities() -> List[Dict[str, Any]]:
    """Queries Home Assistant Core REST API for available entities for dropdown selection."""
    ha_url, token = get_ha_client_config()
    if not token:
        return []

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ctx = ha_ssl_context(ha_url)

    try:
        req = urllib.request.Request(f"{ha_url}/api/states", headers=headers)
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            states = json.loads(r.read().decode("utf-8"))
            filtered = []
            for s in states:
                eid = s.get("entity_id", "")
                domain = eid.split(".")[0]
                if domain in ["sensor", "switch", "climate", "binary_sensor", "input_boolean", "input_select", "select", "weather", "number"]:
                    attrs = s.get("attributes", {}) or {}
                    fname = attrs.get("friendly_name") or eid
                    filtered.append({
                        "entity_id": eid,
                        "friendly_name": fname,
                        "domain": domain,
                        "unit": attrs.get("unit_of_measurement"),
                        "state": s.get("state"),
                        "attributes": attrs,
                        "last_changed": s.get("last_changed"),
                        "last_updated": s.get("last_updated")
                    })
            return sorted(filtered, key=lambda x: x["friendly_name"].lower())
    except Exception as e:
        print(f"Warning fetching HA entities: {e}")
        return []


def get_ha_states_map() -> Dict[str, Dict[str, Any]]:
    """Returns a dict mapping entity_id -> state dict from HA Core."""
    return {e["entity_id"]: e for e in fetch_ha_entities()}


def call_ha_service_detailed(domain: str, service: str, service_data: dict) -> Tuple[bool, Optional[str]]:
    """Calls a Home Assistant Core REST API service and returns success status plus error message."""
    global _WORKING_HA_BASE_URL
    ha_url, token = get_ha_client_config()
    if not token:
        return False, "Geen Home Assistant token geconfigureerd in options.json of environment"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ctx = ha_ssl_context(ha_url)

    url = f"{ha_url}/api/services/{domain}/{service}"
    try:
        req = urllib.request.Request(url, data=json.dumps(service_data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            if r.status in [200, 201]:
                return True, None
            return False, f"HTTP status {r.status}"
    except urllib.error.HTTPError as he:
        return False, f"HTTP Fout {he.code}: {he.reason}"
    except urllib.error.URLError as ue:
        _WORKING_HA_BASE_URL = None
        return False, f"Verbindingsfout naar HA ({ha_url}): {ue.reason}"
    except Exception as e:
        _WORKING_HA_BASE_URL = None
        return False, str(e)


def call_ha_service(domain: str, service: str, service_data: dict) -> bool:
    """Calls a Home Assistant Core REST API service and logs if the call fails."""
    success, err_msg = call_ha_service_detailed(domain, service, service_data)
    if not success:
        print(f"Error calling HA service {domain}.{service}: {err_msg}")
    return success


def push_ha_state(entity_id: str, state: Any, attributes: Optional[Dict[str, Any]] = None) -> bool:
    """Creates/updates a state object in Home Assistant (e.g. the dispatch heartbeat sensor)."""
    ha_url, token = get_ha_client_config()
    if not token:
        return False
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps({"state": state, "attributes": attributes or {}}).encode("utf-8")
    try:
        from api.http_client import safe_urlopen
        req = urllib.request.Request(f"{ha_url}/api/states/{entity_id}", data=body, headers=headers, method="POST")
        with safe_urlopen(req, timeout=5, context=ha_ssl_context(ha_url)) as r:
            return r.status in (200, 201)
    except Exception as e:
        print(f"Warning pushing HA state {entity_id}: {e}")
        return False


def make_daikin_ha_actuator(
    states_map: Optional[Dict[str, Dict[str, Any]]] = None,
    dispatch_state: Optional[Any] = None,
) -> DaikinActuator:
    """
    Creates a configured DaikinActuator delegating select, switch and climate calls to Home Assistant Core.

    states_map: the tick's single HA snapshot (fetched if omitted).
    dispatch_state: PersistentState used for CV-master ownership. Open HEMS only switches the CV
      master back ON if Open HEMS itself switched it OFF (hydraulic DHW interlock). A CV master the
      user switched off (summer, holiday) is never turned back on.
    The returned actuator exposes `ha_writes`: the list of (entity_id, desired_state) written this tick.
    """
    states_map = dict(states_map) if states_map is not None else get_ha_states_map()
    writes: List[Tuple[str, str]] = []

    def select_caller(option_name: str) -> bool:
        eid = "input_select.warmtepomp_smart_grid_modus"
        curr_opt = states_map.get(eid, {}).get("state")

        # Transition-only actuation & manual override protection:
        # Open HEMS sets the option once upon a mode transition. Once successfully commanded,
        # Open HEMS does not touch it again within the same mode window, respecting user overrides in HA.
        last_dispatched = dispatch_state.get("last_dispatched_smart_grid_option") if dispatch_state else None
        if last_dispatched == option_name:
            return True

        if curr_opt == option_name:
            # Already in target state: record as dispatched without redundant service calls
            if dispatch_state:
                dispatch_state.set("last_dispatched_smart_grid_option", option_name)
            return True

        ok = call_ha_service("input_select", "select_option", {"entity_id": eid, "option": option_name})
        if not ok:
            raise RuntimeError(f"Home Assistant service call mislukt voor {eid} -> {option_name}")
        states_map[eid] = {"state": option_name}
        writes.append((eid, option_name))
        if dispatch_state:
            dispatch_state.set("last_dispatched_smart_grid_option", option_name)
        return True

    def switch_caller(switch_name: str, state: bool):
        # Strict Relay-Only Mandate: Open HEMS ONLY controls the physical Smart Grid relays (S10S / S11S).
        # It must NEVER touch switch.hc_mode_altherma_on (cv_master) on the Daikin P1P2 bus.
        if switch_name == "cv_master":
            if dispatch_state:
                dispatch_state.set(CV_FORCED_OFF_KEY, False)
            return True
        entity_map = {
            "s10s": "switch.warmtepomp_smart_grid_1_s10s",
            "s11s": "switch.warmtepomp_smart_grid_2_s11s",
        }
        eid = entity_map.get(switch_name)
        if not eid:
            return True
        curr_raw = states_map.get(eid, {}).get("state")
        curr_state = (curr_raw == "on")
        if curr_state == state:
            # Idempotent guard: switch already in desired state
            if switch_name in ("s10s", "s11s") and dispatch_state:
                dispatch_state.set(f"last_dispatched_{switch_name}", state)
            return True
        if switch_name in ("s10s", "s11s") and dispatch_state:
            last_sw = dispatch_state.get(f"last_dispatched_{switch_name}")
            if last_sw == state:
                # Transition-only: already commanded once, respect user manual override
                return True
        if curr_raw in (None, "unknown", "unavailable"):
            raise RuntimeError(f"{eid} is {curr_raw}; schakelen overgeslagen")
        service = "turn_on" if state else "turn_off"
        ok = call_ha_service("switch", service, {"entity_id": eid})
        if not ok:
            raise RuntimeError(f"Home Assistant service call mislukt voor {eid} -> {service}")
        states_map[eid] = {"state": "on" if state else "off"}
        writes.append((eid, "on" if state else "off"))
        if switch_name in ("s10s", "s11s") and dispatch_state:
            dispatch_state.set(f"last_dispatched_{switch_name}", state)
        return True

    def climate_caller(climate_name: str, temp: float):
        # Strict Relay-Only Mandate: Open HEMS must NEVER write to any Daikin climate entity
        # (neither climate.hc_dhw_dhw_setpoint nor climate.hc_room_room_heating).
        return True

    actuator = DaikinActuator(
        switch_caller=switch_caller,
        climate_caller=climate_caller,
        select_caller=select_caller
    )
    actuator.ha_writes = writes  # type: ignore[attr-defined]
    return actuator
