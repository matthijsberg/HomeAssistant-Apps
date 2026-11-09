#!/usr/bin/env python3
"""
Open HEMS Framework & Management Console
========================================
Version: 0.108.23
Generic Energy Management Platform:
  - Multi-Vector Telemetry & Optimization Daemon
  - Domain Router Dispatch to api/routes_*.py
  - Background Layer 1 Sampling & InfluxDB Sync
"""

import argparse
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

# Priority path anchoring
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api import routes_analytics, routes_model, routes_schedule, routes_system
from models.canonical import normalize_power_reading
from site_adapters.daikin_p1p2 import DaikinP1P2StateClassifier
from layer3_scheduling.decision_audit import DecisionAuditLogger
from api.context import (
    ensure_active_canonical_plan, get_web_dir
)
from api.secrets_store import (
    CONFIG_FILE, load_json, load_secrets, ensure_framework_defaults
)
from integrations.homeassistant.client import (
    get_ha_client_config, get_ha_states_map, call_ha_service, make_daikin_ha_actuator
)
from api.infra_diagnostics import (
    write_hems_annotation, log_technical_error
)
from api.energy_feed import (
    AMS_TZ
)
from layer3_scheduling.plan_decision_evaluator import (
    evaluate_and_apply_dhw_run_merger,
    evaluate_and_log_night_boiler_decision
)
from layer3_scheduling.plan_store import PlanStore
from layer4_control.room_thermostat_buffer import (
    RoomThermostatBufferController,
    get_room_thermostat_buffer_controller,
)
from layer4_control.preflight.models import SubsystemLiveState, LockoutHorizon, GatekeeperDecision
from layer4_control.preflight.coordinator import PreflightCoordinator
from layer4_control.dispatch_state import get_dispatch_state
from layer4_control.dhw_run_supervisor import DhwRunSupervisor, DHW_FORCE_MODES, normalize_mode
from layer4_control.dispatch_guard import resolve_current_slot, count_run_minutes_from
from integrations.daikin_altherma.reader import read_dhw_activity, read_room_climate, room_setpoint_service_call
from integrations.homeassistant.client import push_ha_state, CV_FORCED_OFF_KEY

GLOBAL_ROOM_BUFFER_CTRL = get_room_thermostat_buffer_controller()
def _build_dhw_supervisor() -> DhwRunSupervisor:
    """Layer 4 DHW supervisor with the ADR-006 safety-net settings from cfg['dhw_policy'] (read at start-up)."""
    try:
        cfg = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
    except Exception:
        cfg = {}
    return DhwRunSupervisor.from_config(PlanStore.get_instance(), cfg)


DHW_SUPERVISOR = _build_dhw_supervisor()
GLOBAL_PREFLIGHT_COORDINATOR = PreflightCoordinator()
HEARTBEAT_ENTITY = "sensor.openhems_dispatch_heartbeat"

class HemsApiHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = self.rfile.read(length).decode("utf-8")
                return json.loads(body)
        except Exception as e:
            print(f"Error parsing JSON body: {e}")
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # =========================================================================
    # MODULAR HTTP ROUTERS DELEGATION (Fase 2)
    # =========================================================================
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
        query_params = urllib.parse.parse_qs(parsed.query)

        # 0. SRE Healthz & Liveness Probe
        if path == "/healthz" or path == "/health":
            now_ams = datetime.now(ZoneInfo("Europe/Amsterdam"))
            plan = ensure_active_canonical_plan()
            self._send_json({
                "status": "healthy",
                "timestamp": now_ams.isoformat(),
                "plan_slots": len(plan.slots) if plan else 0,
                "plan_is_fresh": getattr(plan, "is_fresh", True) if plan else False,
                "active_dhw_slots": sum(1 for s in plan.slots if s.dhw_kw > 0) if plan else 0,
                "dynamic_peaks_count": len(plan.dynamic_peaks) if plan else 0
            })
            return

        # 1. Dispatch to modular domain routers
        if routes_analytics.handle_get(self, path, query_params):
            return
        if routes_model.handle_get(self, path, query_params):
            return
        if routes_schedule.handle_get(self, path, query_params):
            return
        if routes_system.handle_get(self, path, query_params):
            return

        # 2. Static file serving from web/ and locales/
        if path.startswith("/locales/"):
            from api.i18n import LOCALES_DIR
            clean_rel = path.replace("/locales/", "", 1)
            file_path = (LOCALES_DIR / clean_rel).resolve()
            if file_path.is_relative_to(LOCALES_DIR.resolve()) and file_path.is_file():
                self._serve_static_file(file_path)
                return

        if path.startswith("/static/") or path.startswith("/web/") or path.startswith("/js/") or path.endswith(".js") or path.endswith(".css"):
            clean_rel = path.lstrip("/")
            if clean_rel.startswith("web/"):
                clean_rel = clean_rel[4:]
            elif clean_rel.startswith("static/"):
                clean_rel = clean_rel[7:]
            w_dir = get_web_dir()
            file_path = (w_dir / clean_rel).resolve()
            if file_path.is_relative_to(w_dir.resolve()) and file_path.is_file():
                self._serve_static_file(file_path)
                return

        # 3. HTML Single Page Application fallback
        self._serve_spa()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_json_body()

        if routes_analytics.handle_post(self, path, body):
            return
        if routes_model.handle_post(self, path, body):
            return
        if routes_schedule.handle_post(self, path, body):
            return
        if routes_system.handle_post(self, path, body):
            return

        self._send_json({"error": "Endpoint not found"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_json_body()

        if routes_schedule.handle_put(self, path, body):
            return
        if routes_system.handle_put(self, path, body):
            return

        self._send_json({"error": "Endpoint not found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if routes_system.handle_delete(self, path):
            return

        self._send_json({"error": "Endpoint not found"}, 404)

    # =========================================================================
    # HTML SINGLE PAGE APPLICATION & STATIC ASSETS (Served from web/)
    # =========================================================================
    def _serve_spa(self):
        try:
            active_index = get_web_dir() / "index.html"
            if active_index.exists():
                with open(active_index, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_json({"error": f"web/index.html not found at {active_index}"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _serve_static_file(self, file_path: Path):
        try:
            import mimetypes
            ctype, _ = mimetypes.guess_type(str(file_path))
            ctype = ctype or "application/octet-stream"
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            cache_ctrl = "no-cache" if file_path.suffix in [".js", ".css", ".json"] else "public, max-age=3600"
            self.send_header("Cache-Control", cache_ctrl)
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)



class HemsMqttSubscriberThread(threading.Thread):
    """
    Background subscriber thread connecting directly to MQTT broker (Mosquitto)
    using configured credentials. Ingests high-frequency Modbus (MBMD) and device streams
    into an in-memory cache for zero-latency Layer 1 sampling.

    Protocol hygiene: variable-length "remaining length" decoding, QoS-aware PUBLISH parsing,
    PINGREQ keep-alive, socket closed on every reconnect. Every cached value carries a receive
    timestamp; consumers must use get_fresh() so a silent feed can never freeze a reading.
    """
    KEEPALIVE_S = 60
    STALE_AFTER_S = 120.0

    def __init__(self, host="core-mosquitto", port=1883, user="openhems", pwd=""):
        super().__init__(daemon=True, name="HemsMqttSubscriber")
        self.host = host
        self.port = int(port)
        self.user = user
        self.pwd = pwd
        self.cache: Dict[str, Any] = {}
        self.cache_ts: Dict[str, float] = {}
        self.running = True
        self.connected = False
        self.last_msg_time = 0

    # ------------------------------------------------------------ pure protocol helpers
    @staticmethod
    def encode_remaining_length(n: int) -> bytes:
        out = bytearray()
        while True:
            byte = n % 128
            n //= 128
            if n > 0:
                byte |= 0x80
            out.append(byte)
            if n == 0:
                return bytes(out)

    @staticmethod
    def decode_remaining_length(buf: bytes, start: int = 1) -> Tuple[Optional[int], int]:
        """Returns (value, n_bytes); (None, 0) when the header is incomplete. Raises on malformed input."""
        multiplier, value = 1, 0
        for i in range(4):
            idx = start + i
            if idx >= len(buf):
                return None, 0
            byte = buf[idx]
            value += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                return value, i + 1
            multiplier *= 128
        raise ValueError("Malformed MQTT remaining length")

    @classmethod
    def parse_packets(cls, buf: bytearray) -> Tuple[List[Tuple[str, bytes]], bytearray]:
        """Extracts complete packets from buf. Returns (publishes as (topic, payload), remaining bytes)."""
        publishes: List[Tuple[str, bytes]] = []
        while len(buf) >= 2:
            rem, n_len = cls.decode_remaining_length(buf, 1)
            if rem is None:
                break
            total = 1 + n_len + rem
            if len(buf) < total:
                break
            header = buf[0]
            body = bytes(buf[1 + n_len:total])
            buf = buf[total:]
            if header >> 4 == 3 and len(body) >= 2:  # PUBLISH
                t_len = (body[0] << 8) | body[1]
                topic = body[2:2 + t_len].decode("utf-8", errors="ignore")
                pos = 2 + t_len
                if (header >> 1) & 0x03:  # QoS 1/2 carry a packet identifier
                    pos += 2
                publishes.append((topic, body[pos:]))
        return publishes, buf

    def get_fresh(self, topic: str, max_age_s: Optional[float] = None) -> Optional[Any]:
        ts = self.cache_ts.get(topic)
        if ts is None or (time.time() - ts) > (max_age_s or self.STALE_AFTER_S):
            return None
        return self.cache.get(topic)

    def fresh_snapshot(self, max_age_s: Optional[float] = None) -> Dict[str, Any]:
        limit = max_age_s or self.STALE_AFTER_S
        now = time.time()
        out = {}
        for t, ts in list(self.cache_ts.items()):
            if t not in self.cache:
                continue
            # P1P2 bus state topics only publish on state change (e.g. 3-way valve stays '1' for 45 min)
            t_limit = max(limit, 3600.0) if t.startswith("P1P2/") else limit
            if (now - ts) <= t_limit:
                out[t] = self.cache[t]
        return out

    # ------------------------------------------------------------ connection loop
    def run(self):
        while self.running:
            s = None
            try:
                if not self.pwd:
                    sec = load_secrets()
                    self.pwd = sec.get("mqtt", {}).get("local_mosquitto") or sec.get("mqtt", {}).get("openhems_mqtt") or ""

                s = socket.socket()
                s.settimeout(10)
                s.connect((self.host, self.port))

                flags = 0x02
                if self.user:
                    flags |= 0x80
                if self.pwd:
                    flags |= 0x40
                var_h = bytearray([0, 4]) + b"MQTT" + bytearray([4, flags, 0, self.KEEPALIVE_S])
                client_id = b"openhems-stream"
                payload = bytearray([0, len(client_id)]) + client_id
                if self.user:
                    u_b = self.user.encode()
                    payload += bytearray([0, len(u_b)]) + u_b
                if self.pwd:
                    p_b = self.pwd.encode()
                    payload += bytearray([0, len(p_b)]) + p_b
                body = var_h + payload
                s.sendall(bytes([0x10]) + self.encode_remaining_length(len(body)) + body)
                connack = s.recv(4)
                if not (len(connack) >= 4 and connack[0] >> 4 == 2 and connack[3] == 0):
                    self.connected = False
                    time.sleep(5)
                    continue

                self.connected = True
                for pkt_id, sub_t in enumerate([b"mbmd/#", b"openhems/#", b"P1P2/#"], start=1):
                    sub_body = bytearray([0, pkt_id, 0, len(sub_t)]) + sub_t + bytearray([0])
                    s.sendall(bytes([0x82]) + self.encode_remaining_length(len(sub_body)) + sub_body)

                buf = bytearray()
                s.settimeout(2.0)
                last_ping = time.time()
                while self.running:
                    if time.time() - last_ping >= self.KEEPALIVE_S / 2:
                        s.sendall(b"\xc0\x00")  # PINGREQ
                        last_ping = time.time()
                    try:
                        chunk = s.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf.extend(chunk)
                    publishes, buf = self.parse_packets(buf)
                    now = time.time()
                    for topic, raw in publishes:
                        val_str = raw.decode("utf-8", errors="ignore")
                        try:
                            self.cache[topic] = float(val_str)
                        except ValueError:
                            self.cache[topic] = val_str
                        self.cache_ts[topic] = now
                        self.last_msg_time = now
            except Exception:
                pass
            finally:
                self.connected = False
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            if self.running:
                time.sleep(5)


class HemsBackgroundCollector(threading.Thread):
    """
    Continuous background collector for Layer 1.
    Samples all configured devices every 10s into an in-memory window accumulator.
    Averages values over a 60-second tumble window to eliminate spikes and noise.
    Flushes clean, noise-filtered 1-minute averages to the dedicated openhems InfluxDB.
    """
    def __init__(self, sample_interval_seconds=10, flush_window_seconds=60):
        super().__init__(daemon=True, name="HemsBackgroundCollector")
        self.sample_interval = sample_interval_seconds
        self.flush_window = flush_window_seconds
        self.running = True
        self.last_write_status = "idle"
        self.total_points_written = 0
        self._lock = threading.Lock()
        self._accumulator = {}
        self._last_flush_time = time.time()
        self.sample_count_in_window = 0
        self.last_flush_iso = "Zojuist gestart"
        self.live_hp_disagg = None
        self.mqtt_sub = HemsMqttSubscriberThread()
        self.mqtt_sub.start()
        self.last_actuation = {}
        self._last_retrain_date: Optional[str] = None
        self.live_balance = {
            "p1_import_w": 0.0,
            "p1_export_w": 0.0,
            "net_grid_w": 0.0,
            "solar_w": 0.0,
            "heatpump_w": 0.0,
            "battery_w": 0.0,
            "direct_solar_w": 0.0,
            "total_house_w": 0.0,
            "unallocated_w": 0.0
        }

    def run(self):
        print(f"[Open HEMS Collector & Dispatcher] Started 60s Loop (Sample: {self.sample_interval}s, Flush & Dispatch: {self.flush_window}s)")
        time.sleep(3)
        while self.running:
            try:
                self.sample_devices()
            except Exception as e_samp:
                print(f"[Open HEMS Collector] Error in sample_devices: {e_samp}", flush=True)

            now = time.time()
            if now - self._last_flush_time >= self.flush_window:
                try:
                    self.flush_window_to_influx()
                except Exception as e_flush:
                    print(f"[Open HEMS Collector] Error in flush_window_to_influx: {e_flush}", flush=True)
                self._last_flush_time = now
                try:
                    self.execute_live_dispatch()
                except Exception as e_disp:
                    print(f"[Open HEMS Collector] Error in execute_live_dispatch: {e_disp}", flush=True)
                try:
                    self.push_ha_sensors()
                except Exception as e_push:
                    print(f"[Open HEMS Collector] Error in push_ha_sensors: {e_push}", flush=True)
                try:
                    self.maybe_run_daily_retrain()
                except Exception as e_ret:
                    print(f"[Open HEMS Collector] Error in maybe_run_daily_retrain: {e_ret}", flush=True)
            time.sleep(self.sample_interval)

    def maybe_run_daily_retrain(self) -> None:
        """Runs self-learning model retraining automatically once per night (03:00 local) or when stale (>24h)."""
        from api.context import GLOBAL_MODEL, GLOBAL_DHW_MODEL
        if not GLOBAL_MODEL:
            return
        now_ams = datetime.now(AMS_TZ)
        today_str = now_ams.strftime("%Y-%m-%d")
        if self._last_retrain_date == today_str:
            return

        should_run = (now_ams.hour == 3)
        if not should_run:
            last_tr = GLOBAL_MODEL.params.get("last_trained")
            if not last_tr:
                should_run = True
            else:
                try:
                    dt_tr = datetime.fromisoformat(str(last_tr))
                    if (now_ams - dt_tr.astimezone(AMS_TZ)).total_seconds() > 86400 * 1.5:
                        should_run = True
                except Exception:
                    should_run = True

        if should_run:
            self._last_retrain_date = today_str
            res = GLOBAL_MODEL.retrain_from_openhems()
            if GLOBAL_DHW_MODEL:
                GLOBAL_DHW_MODEL.profile = GLOBAL_DHW_MODEL._load_profile()
            print(f"[Open HEMS Self-Learning] Daily model retrain completed: {res.get('status')}", flush=True)

    def _set_room_setpoint(self, setpoint_c: float) -> bool:
        # Strict Relay-Only Mandate: Open HEMS NEVER writes to climate.hc_room_room_heating on the Daikin.
        # All heat pump control happens strictly via the Smart Grid relays (SG1..SG4).
        return True

    def _log_failsafe(self, reason: Optional[str]) -> None:
        """Logs the Elephant fail-safe once per distinct reason."""
        if reason == getattr(self, "_failsafe_reason", None):
            return
        self._failsafe_reason = reason
        if reason:
            print(f"[Open HEMS Dispatcher] FAIL-SAFE: {reason} -> Elephant baseline (SG2)", flush=True)
            log_technical_error(
                domain="planning",
                event_type="dispatch_failsafe",
                reason="⚠️ Dispatch Fail-safe: Elephant baseline (SG2)",
                explanation=f"Geen geldig actueel planslot ({reason}). Open HEMS valt terug op normaal bedrijf (SG2, 50°C).",
                inputs={"reason": reason},
                category="WARNING"
            )

    def execute_live_dispatch(self):
        """
        Active Layer 4 Dispatch Execution (one Home Assistant snapshot per tick):
          1. Resolve the plan slot that covers *now* from a fresh plan; otherwise fall back to the
             Elephant baseline (normal / SG2) instead of replaying a stale slot.
          2. Observe-only assessments (opportunistic merge, night decision) for audit/UI.
          3. DhwRunSupervisor (single owner of the in-flight run) decides the DHW mode and target.
          4. Room thermostat floor buffer (ownership-aware), DHW climate watchdogs.
          5. Actuate via DaikinActuator, verify every write, publish a heartbeat for the HA dead-man.
        """
        now_utc = datetime.now(timezone.utc)
        effective_mode = None
        try:
            plan = None
            try:
                plan = ensure_active_canonical_plan()
            except Exception as e_plan:
                print(f"[Open HEMS Dispatcher] Planning failed: {e_plan}", flush=True)

            states_map = get_ha_states_map()
            if not states_map:
                print("[Open HEMS Dispatcher] Home Assistant onbereikbaar: geen actuatie mogelijk deze tick", flush=True)
                return

            dhw = read_dhw_activity(states_map)
            t_live = dhw.tank_temp_c
            wp_power_val = dhw.power_w or 0.0

            # 1. Current slot (by timestamp) from a fresh plan, else fail-safe
            cur_slot, stale_reason = resolve_current_slot(plan, now_utc)
            if cur_slot is None:
                requested_mode = "normal"
                slot_target = None
                run_minutes = None
                self._log_failsafe(stale_reason)
            else:
                requested_mode = normalize_mode(cur_slot.mode_code)
                slot_target = getattr(cur_slot, "target_temp_c", None)
                run_minutes = count_run_minutes_from(plan, cur_slot, DHW_FORCE_MODES)
                self._log_failsafe(None)

            # Planning engine of the current plan: plans without the key were made by the DP (ADR-004)
            dhw_engine = str((getattr(plan, "metadata", None) or {}).get("dhw_engine", "dp")) if plan is not None else "daikin_first"

            # 2. Observe-only assessments for the DP engine (never actuate, never mutate the plan).
            #    Daikin-first (ADR-006) has no merger or night decision.
            if plan is not None and dhw_engine == "dp":
                try:
                    evaluate_and_apply_dhw_run_merger(plan, t_live, dhw_power_w=wp_power_val, dhw_valve_on=dhw.valve_on)
                except Exception as e_obs:
                    print(f"[Open HEMS Dispatcher] Merge assessment error: {e_obs}", flush=True)
                if t_live is not None:
                    try:
                        evaluate_and_log_night_boiler_decision(plan, t_live)
                    except Exception as e_night:
                        print(f"[Open HEMS Dispatcher] Night decision log error: {e_night}", flush=True)

            # 3. DHW run supervision (single owner of the in-flight commitment); settings may change at runtime
            try:
                DHW_SUPERVISOR.apply_config(load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {})
            except Exception as e_cfg:
                print(f"[Open HEMS Dispatcher] Supervisor settings not refreshed: {e_cfg}", flush=True)
            decision = DHW_SUPERVISOR.decide(
                requested_mode, slot_target, t_live, now=now_utc, planned_run_minutes=run_minutes,
                dhw_heating_observed=dhw.compressor_heating_dhw, engine=dhw_engine
            )
            mode_to_execute = decision.mode
            target_t = decision.target_temp_c
            if decision.in_flight_action in ("armed", "cleared", "rearmed", "upgraded", "released_no_effect"):
                print(f"[Open HEMS Dispatcher] DHW run {decision.in_flight_action}: mode={mode_to_execute} "
                      f"target={target_t}°C tank={t_live}°C {decision.reason or ''}", flush=True)
                DecisionAuditLogger.log_decision(
                    domain="dhw",
                    decision_type=f"dhw_run_{decision.in_flight_action}",
                    chosen_mode=mode_to_execute,
                    target_temp_c=target_t,
                    inputs={"tank_temp_c": t_live, "planned_mode": requested_mode, "slot_target_c": slot_target,
                            "planned_run_minutes": run_minutes, "dhw_heating_observed": dhw.compressor_heating_dhw,
                            "dhw_engine": dhw_engine},
                    reason=f"DHW run {decision.in_flight_action}",
                    explanation=decision.reason or f"Planslot {requested_mode} → {mode_to_execute} (doel {target_t}°C).",
                    category="WARNING" if decision.in_flight_action == "released_no_effect" else "ACTION"
                )

            # 3b. Pre-Flight Gatekeeper Pipeline (modular multi-subsystem pre-check)
            room_clim = read_room_climate(states_map)
            t_room_val = room_clim.room_temp_c if room_clim.room_temp_c is not None else 20.0
            sp_room_val = room_clim.setpoint_c if room_clim.setpoint_c is not None else 20.0
            t_out_val = None
            for o_ent in ("sensor.wittboy_gw2000a_weather_station_gw2000a_outdoor_temperature", "sensor.altherma_outdoor_temperature"):
                st_o = states_map.get(o_ent, {}).get("state")
                try:
                    if st_o not in (None, "unavailable", "unknown"):
                        t_out_val = float(st_o)
                        break
                except (ValueError, TypeError):
                    pass
            if t_out_val is None:
                t_out_val = 10.0

            batt_soc_val = 50.0
            st_b = states_map.get("sensor.battery_state_of_charge", {}).get("state")
            try:
                if st_b not in (None, "unavailable", "unknown"):
                    batt_soc_val = float(st_b)
            except (ValueError, TypeError):
                pass

            subsystem_live_state = SubsystemLiveState(
                dhw_temp_c=t_live if t_live is not None else 50.0,
                outdoor_temp_c=t_out_val,
                room_temp_c=t_room_val,
                room_setpoint_c=sp_room_val,
                battery_soc_pct=batt_soc_val,
                compressor_dwell_active=False
            )

            try:
                preflight_results = GLOBAL_PREFLIGHT_COORDINATOR.evaluate_all(
                    subsystem_live_state,
                    plan,
                    now=now_utc,
                    is_heating_active=(wp_power_val > 500 and not dhw.valve_on)
                )
                dhw_pf = preflight_results.get("dhw")
                heat_pf = preflight_results.get("heating")

                # Gatekeeper enforcement for DHW: deferral when lockout is too close
                if dhw_pf and dhw_pf.is_deferred and mode_to_execute in DHW_FORCE_MODES:
                    if not (decision and decision.in_flight_action in ("armed", "rearmed", "upgraded")):
                        print(f"[Open HEMS Dispatcher] Pre-Flight DHW DEFER: {dhw_pf.reason}", flush=True)
                        mode_to_execute = "normal"
                        DecisionAuditLogger.log_decision(
                            domain="dhw",
                            decision_type="preflight_dhw_defer",
                            chosen_mode="normal",
                            target_temp_c=target_t,
                            inputs={"tank_temp_c": t_live, "planned_mode": requested_mode, "metrics": dhw_pf.metrics},
                            reason="Pre-Flight Uitstel Boilervat",
                            explanation=dhw_pf.reason,
                            category="DECISION"
                        )
                elif dhw_pf and dhw_pf.action == "EMERGENCY" and mode_to_execute not in DHW_FORCE_MODES:
                    print(f"[Open HEMS Dispatcher] Pre-Flight DHW EMERGENCY: {dhw_pf.reason}", flush=True)
                    mode_to_execute = dhw_pf.target_mode
                    target_t = dhw_pf.target_temp_c or 50.0

                # Gatekeeper enforcement for Space Heating: preheat before lockout or defer short run
                if heat_pf and heat_pf.action == "PREHEAT" and mode_to_execute == "normal" and not dhw.valve_on:
                    mode_to_execute = "advised_on"
                    print(f"[Open HEMS Dispatcher] Pre-Flight CV PREHEAT: {heat_pf.reason}", flush=True)
                elif heat_pf and heat_pf.is_deferred and mode_to_execute == "advised_on":
                    mode_to_execute = "normal"
                    print(f"[Open HEMS Dispatcher] Pre-Flight CV DEFER: {heat_pf.reason}", flush=True)

            except Exception as e_pf:
                print(f"[Open HEMS Dispatcher] Preflight evaluation error: {e_pf}", flush=True)

            # 3c. SG3 (advised_on / Pre-Heat) Anti-Chatter & Minimum Hold Time (30 min)
            # Prevents 1-5 minute relay flapping caused by 60s plan re-evaluations or sensor jitter
            dispatch_st = get_dispatch_state()
            sg3_started_iso = dispatch_st.get("sg3_advised_on_started_at")
            if mode_to_execute == "advised_on":
                if not sg3_started_iso:
                    dispatch_st.set("sg3_advised_on_started_at", now_utc.isoformat())
            elif mode_to_execute == "normal" and sg3_started_iso:
                try:
                    t_sg3 = datetime.fromisoformat(str(sg3_started_iso).replace("Z", "+00:00"))
                    hold_elapsed_mins = (now_utc - t_sg3).total_seconds() / 60.0
                    if hold_elapsed_mins < 30.0:
                        mode_to_execute = "advised_on"
                    else:
                        dispatch_st.set("sg3_advised_on_started_at", None)
                except Exception:
                    dispatch_st.set("sg3_advised_on_started_at", None)
            elif mode_to_execute in ("forced_off", "forced_on", "max_on"):
                # Safety lockouts or DHW always override and clear SG3 hold
                dispatch_st.set("sg3_advised_on_started_at", None)

            # 4a. Space heating pre-heat: Strict Relay-Only Mandate.
            # Open HEMS NEVER writes to climate.hc_room_room_heating or switch.hc_mode_altherma_on.
            # When mode_to_execute == "advised_on", DaikinActuator switches the Smart Grid relay to
            # "Geadviseerd aan" (SG3: S10S=on, S11S=off).
            if GLOBAL_ROOM_BUFFER_CTRL.is_buffering:
                GLOBAL_ROOM_BUFFER_CTRL.request_release(now=now_utc, force=True)

            # Watchdog 2: DHW Setpoint Read-Only Monitor (uit = uit: Open HEMS NEVER forces climate.hc_dhw_dhw_setpoint on or writes its setpoint)
            dhw_cl_temp = states_map.get("climate.hc_dhw_dhw_setpoint", {}).get("attributes", {}).get("temperature")

            # User Mandate: Strict Relay-Only Policy for DHW. Open HEMS NEVER writes to climate.hc_dhw_dhw_setpoint.
            if dhw_cl_temp is not None:
                try:
                    cfg_dhw = load_json(CONFIG_FILE).get("dhw_boiler", {})
                    expected_sp = float(cfg_dhw.get("fallback_setpoint_temp", 48.0))
                    if abs(float(dhw_cl_temp) - expected_sp) > 0.5:
                        log_technical_error(
                            domain="hardware",
                            event_type="dhw_setpoint_anomaly",
                            reason="⚠️ Boilervat Thermostaat Setpoint Afwijking",
                            explanation=f"Boilervat thermostaat staat op {dhw_cl_temp}°C i.p.v. {expected_sp}°C. Open HEMS raakt dit setpoint niet softwarematig aan (relais-only beleid).",
                            inputs={"setpoint": dhw_cl_temp, "expected": expected_sp},
                            category="WARNING"
                        )
                except (ValueError, TypeError):
                    pass

            # Continuous lockout duration (SG1 = S10S off, S11S on)
            cur_lockout_mins = 0.0
            s10_st = states_map.get("switch.warmtepomp_smart_grid_1_s10s", {})
            s11_st = states_map.get("switch.warmtepomp_smart_grid_2_s11s", {})
            if s10_st.get("state") != "on" and s11_st.get("state") == "on":
                lc_str = s11_st.get("last_changed")
                if lc_str:
                    try:
                        lc_dt = datetime.fromisoformat(lc_str.replace("Z", "+00:00"))
                        cur_lockout_mins = max(0.0, (now_utc - lc_dt).total_seconds() / 60.0)
                    except Exception:
                        pass

            # 5. Actuate (CV master ownership persisted in dispatch state)
            actuator = make_daikin_ha_actuator(states_map=states_map, dispatch_state=get_dispatch_state())
            res = actuator.execute_mode(
                requested_mode=mode_to_execute,
                current_cv_switch_state=(dhw.cv_master_on is True),
                target_temp=target_t,
                current_continuous_lockout_mins=cur_lockout_mins
            )
            effective_mode = res.effective_mode

            if not res.success:
                log_technical_error(
                    domain="hardware",
                    event_type="actuation_failed",
                    reason=f"❌ Schakelfout: Actuatie {mode_to_execute} Mislukt",
                    explanation=f"DaikinActuator kon de gewenste stand '{mode_to_execute}' niet doorvoeren naar Home Assistant: {res.error_message}",
                    inputs={
                        "mode_gevraagd": mode_to_execute,
                        "foutmelding": res.error_message,
                        "s10s_doel": res.command.s10s_relay_on,
                        "s11s_doel": res.command.s11s_relay_on,
                        "cv_doel": res.command.cv_master_switch_on
                    },
                    category="ERROR"
                )
            else:
                writes = list(getattr(actuator, "ha_writes", []))
                if writes:
                    time.sleep(0.5)
                    fresh_states = get_ha_states_map()
                    unconfirmed = [
                        f"{eid} (doel '{want}', is '{fresh_states.get(eid, {}).get('state')}')"
                        for eid, want in writes
                        if eid.split(".")[0] in ("input_select", "switch") and fresh_states.get(eid, {}).get("state") != want
                    ]
                    if unconfirmed:
                        # P1P2 bus entities (e.g. switch.hc_mode_altherma_on) can take 1.5-2.5s to echo state back
                        time.sleep(2.0)
                        fresh_states = get_ha_states_map()
                        unconfirmed = [
                            f"{eid} (doel '{want}', is '{fresh_states.get(eid, {}).get('state')}')"
                            for eid, want in writes
                            if eid.split(".")[0] in ("input_select", "switch") and fresh_states.get(eid, {}).get("state") != want
                        ]
                    if unconfirmed:
                        log_technical_error(
                            domain="hardware",
                            event_type="actuation_unconfirmed",
                            reason="❌ Schakeling Niet Bevestigd door Home Assistant",
                            explanation=f"Open HEMS heeft de status omgezet voor {mode_to_execute}, maar Home Assistant bevestigt de toestand niet: {', '.join(unconfirmed)}.",
                            inputs={"mode_gevraagd": mode_to_execute, "onbevestigd": unconfirmed},
                            category="ERROR"
                        )
                    else:
                        mode_titles = {
                            "normal": "⚙️ Smart Grid Relais: Terug naar Ruststand (SG2)",
                            "max_on": "⚡ Smart Grid Relais: DHW Buffer (SG4)",
                            "forced_on": "🚿 Smart Grid Relais: DHW Lading (SG4)",
                            "advised_on": "♨️ Smart Grid Relais: Pre-Heat Vloerbuffer (SG3)",
                            "forced_off": "🚫 Smart Grid Relais: Spitsblokkade (SG1)",
                            "advised_off": "⏸️ Smart Grid Relais: Gereduceerde Modulatie (SG1)"
                        }
                        act_title = mode_titles.get(res.effective_mode, f"⚙️ Smart Grid Relais: {res.effective_mode}")
                        act_desc = f"Writes: {', '.join(f'{e}={w}' for e, w in writes)}."
                        if res.downgrade_reason:
                            act_desc += f" (Veiligheidsinterlock: {res.downgrade_reason})"
                        elif target_t:
                            act_desc += f" Tapwater doel: {target_t}°C."
                        write_hems_annotation(
                            event_type="hardware_actuation",
                            title=act_title,
                            description=act_desc,
                            state_code=res.effective_mode,
                            power_kw=round(wp_power_val / 1000.0, 2),
                            target_temp_c=target_t or 0.0,
                            savings_eur=0.0
                        )
                        DecisionAuditLogger.log_decision(
                            domain="hardware",
                            decision_type="live_actuation",
                            chosen_mode=res.effective_mode,
                            target_temp_c=target_t,
                            inputs={
                                "s10s": res.command.s10s_relay_on,
                                "s11s": res.command.s11s_relay_on,
                                "cv_master": res.command.cv_master_switch_on,
                                "effective_mode": res.effective_mode,
                                "tank_temp_c": round(t_live, 1) if t_live is not None else None,
                                "downgrade_reason": res.downgrade_reason,
                                "writes": writes
                            },
                            reason=act_title,
                            explanation=act_desc,
                            savings_estimate_eur=0.0,
                            category="ACTION"
                        )

            self.last_actuation = {
                "timestamp": datetime.now(AMS_TZ).isoformat(),
                "slot_time": cur_slot.time_label if cur_slot is not None else None,
                "failsafe_reason": stale_reason if cur_slot is None else None,
                "planned_mode": requested_mode,
                "requested_mode": mode_to_execute,
                "effective_mode": res.effective_mode,
                "dhw_run_action": decision.in_flight_action,
                "downgrade_reason": res.downgrade_reason,
                "s10s": res.command.s10s_relay_on,
                "s11s": res.command.s11s_relay_on,
                "cv_master": res.command.cv_master_switch_on,
                "target_dhw_c": target_t,
                "success": res.success
            }
            print(f"[Open HEMS Dispatcher] Live actuation: {requested_mode} -> {mode_to_execute} -> {res.effective_mode} "
                  f"(target {target_t}°C, tank {t_live}°C, S10S={res.command.s10s_relay_on}, S11S={res.command.s11s_relay_on}, "
                  f"CV={res.command.cv_master_switch_on})", flush=True)
        except Exception as e:
            print(f"[Open HEMS Dispatcher] Error executing live dispatch: {e}", flush=True)
        finally:
            # Heartbeat for the Home Assistant dead-man automation (ha/automations/openhems_dispatch_deadman.yaml)
            try:
                push_ha_state(HEARTBEAT_ENTITY, datetime.now(timezone.utc).isoformat(), {
                    "device_class": "timestamp",
                    "friendly_name": "Open HEMS dispatch heartbeat",
                    "effective_mode": effective_mode,
                    "failsafe_reason": getattr(self, "_failsafe_reason", None),
                    "cv_forced_off_by_hems": bool(get_dispatch_state().get(CV_FORCED_OFF_KEY, False)),
                })
            except Exception:
                pass

    def push_ha_sensors(self):
        """Pushes 24h rolling forecast and dispatch sensors to Home Assistant Core."""
        try:
            plan = ensure_active_canonical_plan()
            if not plan or not plan.slots:
                return
            ha_url, ha_tok = get_ha_client_config()
            if ha_url and ha_tok:
                from integrations.homeassistant.sensor_pusher import HomeAssistantSensorPusher
                pusher = HomeAssistantSensorPusher(ha_url, ha_tok)
                pusher.push_plan_sensors(plan)
        except Exception as e:
            print(f"[Open HEMS SensorPusher] Background push error: {e}", flush=True)

    def sample_devices(self):
        cfg = load_json(CONFIG_FILE)
        ha_states = get_ha_states_map()
        if not ha_states:
            return

        def get_val_w(eid, dev=None):
            """Returns value converted to Watt deterministically via canonical normalization."""
            st_obj = ha_states.get(eid, {})
            val_raw = st_obj.get("state")
            unit = st_obj.get("unit") or st_obj.get("attributes", {}).get("unit_of_measurement", "")
            return normalize_power_reading(val_raw, unit=unit, device_cfg=dev or {})

        def get_val_raw(eid):
            st_obj = ha_states.get(eid, {})
            val_raw = st_obj.get("state")
            try:
                return float(val_raw)
            except (ValueError, TypeError):
                return None

        with self._lock:
            for dev in cfg.get("devices", []):
                dev_id = dev.get("id")
                dev_type = dev.get("type", "generic")
                src_type = dev.get("source_type", "homeassistant")

                # P1 Grid Meter (converts kW to W)
                if dev_type in ["grid_meter", "p1_meter"]:
                    p_imp = get_val_w(dev.get("ha_power_entity", "sensor.power_consumption"))
                    p_exp = get_val_w(dev.get("parameters", {}).get("production_entity", "sensor.power_production"))
                    if p_imp is not None:
                        k = f"energy_telemetry|{dev_id}|grid_meter|IMPORT|{src_type}|ELECTRICITY"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "power_w"})
                        entry["sum"] += p_imp
                        entry["count"] += 1
                    if p_exp is not None:
                        k = f"energy_telemetry|{dev_id}|grid_meter|EXPORT|{src_type}|ELECTRICITY"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "power_w"})
                        entry["sum"] += p_exp
                        entry["count"] += 1

                # Solar PV / Inverter (Direct MQTT MBMD / HA Fallback)
                elif dev_type in ["solar_pv", "solar_inverter", "solar"]:
                    p_sol = None
                    if src_type == "mqtt":
                        t_pow = dev.get("mqtt_power_topic", "mbmd/inepro1-103/Power")
                        v_mqtt = self.mqtt_sub.get_fresh(t_pow)
                        if isinstance(v_mqtt, float):
                            p_sol = abs(v_mqtt)
                    if p_sol is None:
                        sol_eid = dev.get("ha_power_entity") or "sensor.zonnepanelen_power"
                        p_sol = get_val_w(sol_eid)
                        if p_sol is None:
                            p_sol = get_val_w("sensor.zonnepanelen_power_avg_5_minutes")
                        if p_sol is not None:
                            p_sol = abs(p_sol)

                    if p_sol is not None:
                        k = f"energy_telemetry|{dev_id}|solar_pv|GENERATION|{src_type}|ELECTRICITY"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "power_w"})
                        entry["sum"] += p_sol
                        entry["count"] += 1

                # Heat Pump (Direct MQTT MBMD + Site Adapter P1P2 Disaggregation)
                elif dev_type == "heat_pump":
                    p_hp = None
                    if src_type == "mqtt":
                        t_pow = dev.get("mqtt_power_topic", "mbmd/inepro1-102/Power")
                        v_mqtt = self.mqtt_sub.get_fresh(t_pow)
                        if isinstance(v_mqtt, float):
                            p_hp = v_mqtt
                    if p_hp is None:
                        p_hp = get_val_w(dev.get("ha_power_entity", "sensor.warmtepomp_power"))

                    if p_hp is not None:
                        # Apply Site-Specific Daikin P1P2 State Classifier
                        disagg = DaikinP1P2StateClassifier.classify(
                            total_power_w=p_hp,
                            mqtt_cache=self.mqtt_sub.fresh_snapshot(),
                            ha_states=ha_states
                        )
                        mode_tag = disagg.mode.lower()

                        # Store total power with mode tag
                        k = f"energy_telemetry|{dev_id}|heat_pump|CONSUMPTION|{src_type}|HEAT|{mode_tag}"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "power_w", "mode": mode_tag})
                        entry["sum"] += p_hp
                        entry["count"] += 1

                        # Track disaggregated live states
                        self.live_hp_disagg = disagg

                # Thermal Buffer (DHW Tank / Boiler)
                elif dev_type in ["thermal_buffer", "dhw_tank", "dhw_boiler"]:
                    t_dhw = get_val_raw(dev.get("ha_temp_entity", "sensor.hc_dhw_temperature_r5t_dhw_tank"))
                    if t_dhw is not None:
                        k = f"energy_telemetry|{dev_id}|thermal_buffer|STORAGE|{src_type}|HEAT"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "temperature_c"})
                        entry["sum"] += t_dhw
                        entry["count"] += 1

                # Battery
                elif dev_type in ["battery", "home_battery", "battery_storage"]:
                    p_bat = get_val_w(dev.get("ha_power_entity", "sensor.battery_power"))
                    if p_bat is not None:
                        flow = "STORAGE_CHARGE" if p_bat >= 0 else "STORAGE_DISCHARGE"
                        k = f"energy_telemetry|{dev_id}|battery|{flow}|{src_type}|ELECTRICITY"
                        entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "power_w"})
                        entry["sum"] += abs(p_bat)
                        entry["count"] += 1

            # Market & Weather Feeds
            epex_val = get_val_raw(cfg.get("providers", {}).get("epex_spot", {}).get("ha_sensor_entity", "sensor.energyzero_today_energy_current_hour_price"))
            if epex_val is not None:
                k = "market_tariffs|epex_spot|1h|spot_electricity"
                entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "price_eur"})
                entry["sum"] += epex_val
                entry["count"] += 1

            # Update Live Pipeline Power Balance (10s snapshot) with direct MQTT priority
            p1_imp = get_val_w("sensor.power_consumption") or 0.0
            p1_exp = get_val_w("sensor.power_production") or 0.0

            # Read Solar (Direct MQTT Inepro 103 -> HA Fallback)
            sol_mqtt = self.mqtt_sub.get_fresh("mbmd/inepro1-103/Power")
            if isinstance(sol_mqtt, float):
                sol = abs(sol_mqtt)
            else:
                sol_raw = get_val_w("sensor.zonnepanelen_power") or get_val_w("sensor.zonnepanelen_power_avg_5_minutes") or 0.0
                sol = abs(sol_raw)

            # Read Heat Pump (Direct MQTT Inepro 102 -> HA Fallback)
            wp_mqtt = self.mqtt_sub.get_fresh("mbmd/inepro1-102/Power")
            if isinstance(wp_mqtt, float):
                wp = wp_mqtt
            else:
                wp = get_val_w("sensor.warmtepomp_power") or 0.0

            bat = get_val_w("sensor.battery_power") or 0.0

            # Mathematical Power Balance (Invariant: battery flows strictly isolated from unallocated load):
            # 1. Net Grid = Import - Export
            net_grid = p1_imp - p1_exp
            # 2. Battery flows: positive = charge (absorbing power), negative = discharge (delivering power)
            bat_charge = max(0.0, bat)
            bat_discharge = max(0.0, -bat)
            # 3. Direct Consumed Solar = Solar produced minus what was pushed to the grid
            dir_sol = max(0.0, sol - p1_exp)
            # 4. Total Real Household Load = Net Grid Import + Solar + Battery Discharge - Battery Charge
            tot_house = max(0.0, net_grid + sol + bat_discharge - bat_charge)
            # 5. Unallocated Load = Total House Load - Heatpump
            unalloc = max(50.0, tot_house - wp)

            hp_mode = self.live_hp_disagg.mode if self.live_hp_disagg else "STANDBY"
            hp_dhw = self.live_hp_disagg.dhw_w if self.live_hp_disagg else 0.0
            hp_heat = self.live_hp_disagg.heating_w if self.live_hp_disagg else 0.0
            hp_cool = self.live_hp_disagg.cooling_w if self.live_hp_disagg else 0.0
            hp_standby = self.live_hp_disagg.standby_w if self.live_hp_disagg else wp

            self.live_balance = {
                "p1_import_w": round(p1_imp, 1),
                "p1_export_w": round(p1_exp, 1),
                "net_grid_w": round(net_grid, 1),
                "solar_w": round(sol, 1),
                "heatpump_w": round(wp, 1),
                "heatpump_mode": hp_mode,
                "heatpump_dhw_w": round(hp_dhw, 1),
                "heatpump_heating_w": round(hp_heat, 1),
                "heatpump_cooling_w": round(hp_cool, 1),
                "heatpump_standby_w": round(hp_standby, 1),
                "battery_w": round(bat, 1),
                "direct_solar_w": round(dir_sol, 1),
                "total_house_w": round(tot_house, 1),
                "unallocated_w": round(unalloc, 1)
            }
            self.sample_count_in_window += 1

            temp_val = get_val_raw(cfg.get("providers", {}).get("open_meteo", {}).get("ha_temp_sensor", "sensor.wittboy_gw2000a_weather_station_gw2000a_outdoor_temperature"))
            if temp_val is not None:
                k = "weather_forecast|wittboy"
                entry = self._accumulator.setdefault(k, {"sum": 0.0, "count": 0, "type": "outdoor_temp_c"})
                entry["sum"] += temp_val
                entry["count"] += 1

    def flush_window_to_influx(self):
        with self._lock:
            if not self._accumulator:
                return
            snapshot = self._accumulator
            self._accumulator = {}
            self.sample_count_in_window = 0
            self.last_flush_iso = datetime.now(AMS_TZ).strftime("%H:%M:%S")

        cfg = load_json(CONFIG_FILE)
        sec = load_secrets()
        active_conn = cfg.get("influxdb_connections", [{}])[0]
        db_name = active_conn.get("database", "openhems")
        db_user = active_conn.get("username", "openhems")
        db_url = active_conn.get("url", "http://a0d7b954-influxdb:8086")
        db_pwd = sec.get("influxdb", {}).get(active_conn.get("id"), "") or sec.get("influxdb", {}).get("local_ha_influxdb", "")

        now_ns = int(time.time() * 1e9)
        lines = []

        for k, v in snapshot.items():
            if v["count"] == 0:
                continue
            mean_val = round(v["sum"] / v["count"], 2)
            parts = k.split("|")
            m_name = parts[0]

            if m_name == "energy_telemetry":
                dev_id, dev_type, flow, src_type, vector = parts[1], parts[2], parts[3], parts[4], parts[5]
                mode_tag = f",mode={parts[6]}" if len(parts) > 6 else ""
                field_name = v["type"]
                lines.append(f"energy_telemetry,device_id={dev_id},device_type={dev_type},flow={flow},source_type={src_type},vector={vector}{mode_tag} {field_name}={mean_val} {now_ns}")
            elif m_name == "market_tariffs":
                provider, res, t_type = parts[1], parts[2], parts[3]
                lines.append(f"market_tariffs,provider={provider},resolution={res},tariff_type={t_type} price_eur={mean_val} {now_ns}")
            elif m_name == "weather_forecast":
                provider = parts[1]
                lines.append(f"weather_forecast,provider={provider} outdoor_temp_c={mean_val} {now_ns}")

        # Add canonical synchronized power balance record to openhems
        b = self.live_balance
        lines.append(
            f"energy_telemetry,source=canonical_accumulator,device_type=balance "
            f"p1_import_w={b['p1_import_w']:.1f},p1_export_w={b['p1_export_w']:.1f},solar_w={b['solar_w']:.1f},"
            f"heatpump_w={b['heatpump_w']:.1f},direct_solar_w={b['direct_solar_w']:.1f},"
            f"total_house_w={b['total_house_w']:.1f},unallocated_w={b['unallocated_w']:.1f} {now_ns}"
        )

        # Add continuous device dispatch state records to openhems (device_dispatch_history)
        cur_hp_mode = "normal"
        if hasattr(self, "last_actuation") and self.last_actuation:
            cur_hp_mode = self.last_actuation.get("effective_mode") or self.last_actuation.get("requested_mode", "normal")
        else:
            try:
                cur_slot, _ = resolve_current_slot(ensure_active_canonical_plan(), datetime.now(timezone.utc))
                if cur_slot is not None:
                    cur_hp_mode = normalize_mode(cur_slot.mode_code)
            except Exception:
                pass

        is_hp_lockout = 1 if cur_hp_mode == "forced_off" else 0
        is_hp_soft = 1 if cur_hp_mode == "advised_off" else 0
        hp_power = b.get("heatpump_w", 0.0)
        lines.append(
            f"device_dispatch_history,device_id=heat_pump,device_type=heat_pump,mode_code={cur_hp_mode} "
            f"is_lockout={is_hp_lockout}i,is_soft_advice={is_hp_soft}i,power_w={hp_power:.1f} {now_ns}"
        )

        if not lines:
            return

        write_url = f"{db_url}/write?" + urllib.parse.urlencode({"u": db_user, "p": db_pwd, "db": db_name})
        payload = "\n".join(lines).encode("utf-8")
        req = urllib.request.Request(write_url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in [200, 204]:
                    self.last_write_status = "success"
                    self.total_points_written += len(lines)
                    print(f"[Open HEMS Collector] Flushed {len(lines)} points to {db_name} (Total: {self.total_points_written})", flush=True)
                else:
                    self.last_write_status = f"status_{resp.status}"
                    print(f"[Open HEMS Collector] Write status: {resp.status}", flush=True)
        except Exception as e:
            print(f"[Open HEMS Collector] Write error: {e}", flush=True)
            self.last_write_status = f"err_{str(e)[:30]}"
            try:
                log_technical_error(
                    domain="database",
                    event_type="influx_write_error",
                    reason="❌ Database Fout: InfluxDB Write Mislukt",
                    explanation=f"Wegschrijven van {len(lines)} telemetrie-punten naar InfluxDB '{db_name}' ({db_url}) mislukt: {e}",
                    inputs={"database": db_name, "points_count": len(lines), "error": str(e)},
                    category="ERROR"
                )
            except Exception:
                pass

GLOBAL_COLLECTOR = None

def run_server(port=8099):
    global GLOBAL_COLLECTOR
    collector = HemsBackgroundCollector(sample_interval_seconds=10, flush_window_seconds=60)
    collector.start()
    GLOBAL_COLLECTOR = collector
    import api.context
    api.context.GLOBAL_COLLECTOR = collector
    class HemsServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = HemsServer(("0.0.0.0", port), HemsApiHandler)
    print(f"Open HEMS Framework Console running on port {port}...")
    server.serve_forever()


def main():
    global CONFIG_FILE
    parser = argparse.ArgumentParser(description="Open HEMS Daemon")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    if args.config:
        CONFIG_FILE = Path(args.config)

    cfg = load_json(CONFIG_FILE)
    ensure_framework_defaults(cfg)
    run_server(args.port)


if __name__ == "__main__":
    main()
