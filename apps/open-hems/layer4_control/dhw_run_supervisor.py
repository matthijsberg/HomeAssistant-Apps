"""
Layer 4: DHW Run Supervisor (single owner of the in-flight DHW run commitment)
==============================================================================
Implements the Goldfish/Elephant contract (knowledge/architecture/dhw-goldfish-elephant-control.md)
and the Layer 4 safety net of ADR-006 as one state machine. It is the ONLY component that registers
or clears the in-flight run in the PlanStore; planners and evaluators only read it.

Per dispatch tick, given the planned slot mode, the slot's run target and the measured tank
temperature, it decides the mode to actuate:

  1. Tank temperature unknown        -> never force DHW blind; Elephant baseline (normal).
  2. Hard peak lockout (forced_off)  -> SG1 wins; any commitment ends.
  3. SG4 without effect              -> no DHW heating measured (3-way valve + compressor power) within
                                        `no_effect_timeout_min` after arming: release to normal (the
                                        actuator restores the CV master) and do not re-arm for
                                        `no_effect_cooldown_min`.
  4. Commitment active               -> continue until T >= target - h, then release to normal
                                        (even if the plan still shows forced slots).
  5. Plan starts a forced run        -> arm a commitment with an expiry; if the tank is already at
                                        target, stay normal.

Targets per engine:
  daikin_first (ADR-006)  the mode decides the target: forced_on = 50 °C, max_on = 60 °C. A running
                          50 °C run may be upgraded to 60 °C when the plan says max_on; it is never
                          re-armed to another plan target (that caused target creep).
  dp (ADR-004)            the slot carries the DP target; a reached target may be re-armed to the next
                          run's higher target (legacy behaviour, removed with the DP in WP5).

Run detection never uses relay state (that would feed Open HEMS' own output back as input).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from layer3_scheduling.dhw_policy import effective_settings

ELEPHANT_SETPOINT_C = 50.0
BOOST_SETPOINT_C = 60.0
DHW_FORCE_MODES = {"forced_on", "max_on", "forced_solar_boost_60", "forced_night_50"}
BOOST_MODES = {"max_on", "forced_solar_boost_60"}


def normalize_mode(mode: Any) -> str:
    val = getattr(mode, "value", mode)
    cleaned = str(val).strip().lower()
    if cleaned.startswith("standardizedstate."):
        cleaned = cleaned.split(".")[-1]
    return cleaned


@dataclass
class DhwDispatchDecision:
    mode: str
    target_temp_c: float
    # "none" | "armed" | "continued" | "cleared" | "rearmed" | "upgraded" | "released_no_effect" | "cooldown"
    in_flight_action: str
    reason: Optional[str] = None


class DhwRunSupervisor:
    def __init__(
        self,
        store: Any,
        hysteresis_c: float = 0.2,
        min_run_minutes: float = 45.0,
        max_run_minutes: float = 180.0,
        elephant_setpoint_c: float = ELEPHANT_SETPOINT_C,
        boost_setpoint_c: float = BOOST_SETPOINT_C,
        no_effect_timeout_min: float = 10.0,
        no_effect_cooldown_min: float = 60.0,
    ):
        self.store = store
        self.hysteresis_c = hysteresis_c
        self.min_run_minutes = min_run_minutes
        self.max_run_minutes = max_run_minutes
        self.elephant_setpoint_c = elephant_setpoint_c
        self.boost_setpoint_c = boost_setpoint_c
        self.no_effect_timeout_min = no_effect_timeout_min
        self.no_effect_cooldown_min = no_effect_cooldown_min
        self._run_key: Optional[str] = None          # started_at of the run whose effect is being tracked
        self._heating_seen = False
        self._stopped_since: Optional[datetime] = None
        self._cooldown_until: Optional[datetime] = None

    @classmethod
    def from_config(cls, store: Any, cfg: Optional[Dict[str, Any]] = None) -> "DhwRunSupervisor":
        sup = cls(store=store)
        sup.apply_config(cfg)
        return sup

    def apply_config(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        """Safety-net settings from cfg['dhw_policy'] (bounds: layer3_scheduling.dhw_policy.SETTINGS_SPEC).
        Called every dispatch tick, so a change made in the web interface applies without a restart."""
        values = effective_settings(cfg)
        self.hysteresis_c = float(values["sg4_release_hysteresis_c"])
        self.no_effect_timeout_min = float(values["sg4_no_effect_timeout_min"])
        self.no_effect_cooldown_min = float(values["sg4_no_effect_cooldown_min"])

    def _expiry_minutes(self, planned_run_minutes: Optional[float]) -> float:
        if planned_run_minutes is None or planned_run_minutes <= 0:
            return self.max_run_minutes
        return max(self.min_run_minutes, min(self.max_run_minutes, 2.0 * float(planned_run_minutes)))

    def _default_target(self, mode: str) -> float:
        return self.boost_setpoint_c if mode in BOOST_MODES else self.elephant_setpoint_c

    def _arm(self, target: float, mode: str, now: datetime, planned_run_minutes: Optional[float],
             started_at: Optional[datetime] = None, heating_observed: bool = False) -> None:
        start = started_at or now
        self.store.register_in_flight_run(
            target_temp_c=target, mode=mode, started_at=start,
            max_duration_min=self._expiry_minutes(planned_run_minutes), source="dhw_run_supervisor")
        if started_at is None:
            self._run_key = start.isoformat()
            self._heating_seen = bool(heating_observed)
            self._stopped_since = None

    def decide(
        self,
        planned_mode: Any,
        slot_target_c: Optional[float],
        tank_temp_c: Optional[float],
        now: Optional[datetime] = None,
        planned_run_minutes: Optional[float] = None,
        dhw_heating_observed: Optional[bool] = None,
        engine: str = "daikin_first",
    ) -> DhwDispatchDecision:
        """
        dhw_heating_observed: telemetry shows the 3-way valve on DHW and the compressor drawing power.
          None (not measured) counts as not observed: SG4 with the CV master off is never held blind.
        engine: "daikin_first" (ADR-006) or "dp" (ADR-004), from plan.metadata["dhw_engine"].
        """
        now = now or datetime.now(timezone.utc)
        mode = normalize_mode(planned_mode)
        in_flight = self.store.get_in_flight_run(now=now)
        h = self.hysteresis_c
        daikin_first = engine != "dp"

        # 1. No valid tank temperature: never force DHW without being able to stop it
        if tank_temp_c is None:
            action = "none"
            if in_flight:
                self.store.clear_in_flight_run()
                action = "cleared"
            if mode in DHW_FORCE_MODES:
                return DhwDispatchDecision("normal", self.elephant_setpoint_c, action,
                                           "Tanktemperatuur onbekend: geen geforceerde DHW-run (Elephant baseline)")
            return DhwDispatchDecision(mode, self.elephant_setpoint_c, action,
                                       "Tanktemperatuur onbekend" if action == "cleared" else None)

        # 2. Hard peak lockout always wins and ends any commitment
        if mode == "forced_off":
            action = "none"
            if in_flight:
                self.store.clear_in_flight_run()
                action = "cleared"
            return DhwDispatchDecision("forced_off", self.elephant_setpoint_c, action,
                                       "Spitsblokkade beëindigt lopende DHW-run" if action == "cleared" else None)

        # 3. SG4 without effect (at start or stalled/diverted to space heating mid-run): release and cool down
        if in_flight:
            key = str(in_flight.get("started_at"))
            if key != self._run_key:
                self._run_key, self._heating_seen, self._stopped_since = key, False, None
            if dhw_heating_observed:
                self._heating_seen = True
                self._stopped_since = None
            elif self._heating_seen and self._stopped_since is None:
                self._stopped_since = now
            try:
                started = datetime.fromisoformat(key)
            except (TypeError, ValueError):
                started = now
            no_start_effect = (not self._heating_seen) and (now - started >= timedelta(minutes=self.no_effect_timeout_min))
            stalled_mid_run = (
                self._heating_seen
                and self._stopped_since is not None
                and (now - self._stopped_since >= timedelta(minutes=self.no_effect_timeout_min))
            )
            if no_start_effect or stalled_mid_run:
                self.store.clear_in_flight_run()
                self._stopped_since = None
                self._cooldown_until = now + timedelta(minutes=self.no_effect_cooldown_min)
                return DhwDispatchDecision(
                    "normal", self.elephant_setpoint_c, "released_no_effect",
                    f"Geforceerd aan (Smart Grid-stand 4) zonder tapwaterverwarming na {self.no_effect_timeout_min:.0f} min: "
                    f"losgelaten en centrale verwarming hersteld; {self.no_effect_cooldown_min:.0f} min geen nieuwe run")

        # 4. Existing commitment
        if in_flight:
            run_target = float(in_flight.get("target_temp_c", self.elephant_setpoint_c))
            run_mode = normalize_mode(in_flight.get("mode", "forced_on"))
            if run_mode not in DHW_FORCE_MODES:
                run_mode = "forced_on"
            started_at = datetime.fromisoformat(str(in_flight.get("started_at"))) if in_flight.get("started_at") else now

            # Daikin-first: a 50 °C run is upgraded to 60 °C when the plan now says max_on
            if daikin_first and mode in BOOST_MODES and run_target < self.boost_setpoint_c - h \
                    and tank_temp_c < self.boost_setpoint_c - h:
                self._arm(self.boost_setpoint_c, mode, now, planned_run_minutes, started_at=started_at)
                return DhwDispatchDecision(mode, self.boost_setpoint_c, "upgraded",
                                           f"Lopende run opgeschaald van {run_target:.0f} naar {self.boost_setpoint_c:.0f} °C")

            if tank_temp_c >= run_target - h:
                self.store.clear_in_flight_run()
                # DP only: the plan may already have the NEXT run with a higher target in this slot
                if (not daikin_first) and mode in DHW_FORCE_MODES and slot_target_c is not None \
                        and tank_temp_c < float(slot_target_c) - h:
                    self._arm(float(slot_target_c), mode, now, planned_run_minutes)
                    return DhwDispatchDecision(mode, float(slot_target_c), "rearmed", None)
                if mode in DHW_FORCE_MODES:
                    return DhwDispatchDecision("normal", self.elephant_setpoint_c, "cleared",
                                               f"Doel {run_target:.1f}°C bereikt ({tank_temp_c:.1f}°C): terug naar Elephant baseline")
                return DhwDispatchDecision(mode, self.elephant_setpoint_c, "cleared",
                                           f"Doel {run_target:.1f}°C bereikt ({tank_temp_c:.1f}°C)")
            # Continue the run regardless of a replanned non-DHW slot (no premature abort)
            exec_mode = mode if mode in DHW_FORCE_MODES else run_mode
            return DhwDispatchDecision(exec_mode, run_target, "continued", None)

        # 5. No commitment: arm one when the plan starts a forced run
        if mode in DHW_FORCE_MODES:
            if self._cooldown_until is not None and now < self._cooldown_until:
                return DhwDispatchDecision("normal", self.elephant_setpoint_c, "cooldown",
                                           "Geen nieuwe geforceerde run: de vorige had geen effect (afkoeltijd)")
            if daikin_first:
                target = self._default_target(mode)       # the mode decides: forced_on = 50 °C, max_on = 60 °C
            else:
                target = float(slot_target_c) if slot_target_c is not None else self._default_target(mode)
            if tank_temp_c >= target - h:
                return DhwDispatchDecision("normal", self.elephant_setpoint_c, "none",
                                           f"Tank al op doel ({tank_temp_c:.1f}°C ≥ {target:.1f}°C): geen run nodig")
            self._arm(target, mode, now, planned_run_minutes, heating_observed=bool(dhw_heating_observed))
            return DhwDispatchDecision(mode, target, "armed", None)

        return DhwDispatchDecision(mode, self.elephant_setpoint_c, "none", None)
