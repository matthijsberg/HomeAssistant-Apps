"""
Layer 4: Room Thermostat Floor Buffer Controller
================================================
Manages thermal floor pre-buffering via living room thermostat setpoint modulation
with strict chattering prevention, rate limiting and setpoint OWNERSHIP.

Key Invariants:
1. Ownership:
   - Open HEMS only ever reverts a setpoint that it wrote itself. A setpoint changed by the
     user (or an HA schedule) is adopted as the new baseline and never overwritten.
2. Rate Limiting (elevations only):
   - Maximum 2 setpoint adjustments per rolling hour and 6 per rolling 24 hours before a new
     elevation is allowed. Restoring the baseline is ALWAYS allowed (never strand an elevated
     setpoint because a budget is exhausted).
3. Minimum Run Duration:
   - Once elevated for pre-heat, the setpoint remains elevated for at least 45 minutes
     to prevent short-cycling the compressor on the massive concrete floor.
4. Persistence:
   - Baseline, buffering state, last written setpoint and change history survive restarts
     (optional PersistentState), so a restart mid-preheat can never ratchet the baseline up.
"""

from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone
import threading


class RoomThermostatBufferController:
    MAX_CHANGES_PER_HOUR = 2
    MAX_CHANGES_PER_24H = 6
    MIN_RUN_DURATION_SECONDS = 45 * 60  # 45 minutes minimum run
    MAX_PREHEAT_SAFETY_TEMP_C = 23.5    # Absolute upper thermal safety ceiling for room setpoint
    MAX_PREHEAT_DELTA_ABOVE_BASE_C = 3.0  # Max setpoint offset above baseline (e.g. 20.5->23.5, 14.0->17.0)
    MAX_FLOOR_TEMP_FOR_PREHEAT_C = 26.5   # Stop pre-heating once concrete floor itself is thoroughly charged
    MIN_WRITE_BUDGET_FOR_PREHEAT = 3.0    # Require >=3 P1P2 tokens (1 up + 1 restore + 1 safety margin)
    OWNERSHIP_TOLERANCE_C = 0.25        # Setpoint within this band of our last write is "ours"
    WRITE_SETTLE_SECONDS = 180          # HA state may lag our write; don't judge ownership meanwhile
    STATE_KEY = "room_thermostat_buffer"

    def __init__(self, default_baseline_c: float = 20.5, state: Optional[Any] = None):
        self.baseline_temp_c: float = default_baseline_c
        self.is_buffering: bool = False
        self.buffering_started_at: Optional[datetime] = None
        self.change_history: List[datetime] = []
        self.last_elevated_setpoint_c: Optional[float] = None  # our pre-heat value, until seen restored
        self.last_write_at: Optional[datetime] = None
        self._state = state
        self._restore()

    # ------------------------------------------------------------------ persistence
    def _restore(self) -> None:
        if self._state is None:
            return
        raw: Dict[str, Any] = self._state.get(self.STATE_KEY) or {}
        if not raw:
            return

        def _dt(v: Any) -> Optional[datetime]:
            try:
                return datetime.fromisoformat(v) if v else None
            except (TypeError, ValueError):
                return None

        self.baseline_temp_c = float(raw.get("baseline_temp_c", self.baseline_temp_c))
        self.is_buffering = bool(raw.get("is_buffering", False))
        self.buffering_started_at = _dt(raw.get("buffering_started_at"))
        self.change_history = [d for d in (_dt(x) for x in raw.get("change_history", [])) if d]
        self.last_elevated_setpoint_c = raw.get("last_elevated_setpoint_c")
        self.last_write_at = _dt(raw.get("last_write_at"))

    def _persist(self) -> None:
        if self._state is None:
            return
        self._state.set(self.STATE_KEY, {
            "baseline_temp_c": self.baseline_temp_c,
            "is_buffering": self.is_buffering,
            "buffering_started_at": self.buffering_started_at.isoformat() if self.buffering_started_at else None,
            "change_history": [t.isoformat() for t in self.change_history],
            "last_elevated_setpoint_c": self.last_elevated_setpoint_c,
            "last_write_at": self.last_write_at.isoformat() if self.last_write_at else None,
        })

    def _record_write(self, setpoint_c: float, kind: str, now: datetime) -> None:
        self.change_history.append(now)
        if kind == "elevate":
            self.last_elevated_setpoint_c = round(float(setpoint_c), 2)
        self.last_write_at = now

    # ------------------------------------------------------------------ helpers
    def clean_history(self, now: datetime) -> None:
        """Prunes historical change timestamps older than 24 hours."""
        cutoff = now - timedelta(hours=24)
        self.change_history = [t for t in self.change_history if t > cutoff]

    def can_change(self, now: datetime) -> Tuple[bool, str]:
        """Rate-limit check for ELEVATIONS: max 2 changes/hour, max 6 changes/24h."""
        self.clean_history(now)
        one_hour_ago = now - timedelta(hours=1)
        changes_1h = sum(1 for t in self.change_history if t > one_hour_ago)
        if changes_1h >= self.MAX_CHANGES_PER_HOUR:
            return False, f"Uurlimiet bereikt ({changes_1h}/{self.MAX_CHANGES_PER_HOUR} wijzigingen in het afgelopen uur)"

        changes_24h = len(self.change_history)
        if changes_24h >= self.MAX_CHANGES_PER_24H:
            return False, f"24-uurs limiet bereikt ({changes_24h}/{self.MAX_CHANGES_PER_24H} wijzigingen in de afgelopen 24 uur)"

        return True, "OK"

    def _is_our_value(self, setpoint_c: Optional[float]) -> bool:
        if setpoint_c is None or self.last_elevated_setpoint_c is None:
            return False
        sp = float(setpoint_c)
        raw_elev = float(self.last_elevated_setpoint_c)
        snapped_elev = round(round(raw_elev / 0.5) * 0.5, 1)
        return (
            abs(sp - raw_elev) <= self.OWNERSHIP_TOLERANCE_C
            or abs(sp - snapped_elev) <= self.OWNERSHIP_TOLERANCE_C
        )

    def _settling(self, now: datetime) -> bool:
        return self.last_write_at is not None and (now - self.last_write_at).total_seconds() < self.WRITE_SETTLE_SECONDS

    # ------------------------------------------------------------------ public API
    def request_preheat(
        self,
        current_room_temp_c: Optional[float],
        current_setpoint_c: Optional[float],
        now: Optional[datetime] = None,
        write_budget: Optional[float] = None,
        current_floor_temp_c: Optional[float] = None
    ) -> Optional[float]:
        """
        Requests elevating room thermostat by at least +1.0°C above current temperature
        to trigger active floor buffering. Returns the target temperature, or None if rejected.
        Strictly checks P1P2 write_budget (>= 3 tokens) so restoring the previous baseline is guaranteed.
        """
        now = now or datetime.now(timezone.utc)
        if self.is_buffering or current_room_temp_c is None:
            return None

        if write_budget is not None and float(write_budget) < self.MIN_WRITE_BUDGET_FOR_PREHEAT:
            return None  # insufficient P1P2 write budget to guarantee restoring baseline afterwards

        if current_floor_temp_c is not None and float(current_floor_temp_c) >= self.MAX_FLOOR_TEMP_FOR_PREHEAT_C:
            return None  # floor screed is already thermally charged

        allowed, _ = self.can_change(now)
        if not allowed:
            return None

        # Capture the user's baseline (down to 10.0°C for vacation/frost-protection mode),
        # but never one of our own leftover elevated values
        if current_setpoint_c and 10.0 <= float(current_setpoint_c) <= 25.0:
            if not self._is_our_value(current_setpoint_c):
                self.baseline_temp_c = float(current_setpoint_c)

        # Dynamic ceiling: at most +3.0°C above baseline (e.g. 23.5°C at 20.5°C base, 17.0°C at 14.0°C vacation),
        # and never above the absolute hardware ceiling MAX_PREHEAT_SAFETY_TEMP_C (23.5°C).
        safety_ceiling = min(
            self.MAX_PREHEAT_SAFETY_TEMP_C,
            round(self.baseline_temp_c + self.MAX_PREHEAT_DELTA_ABOVE_BASE_C, 1)
        )
        if current_room_temp_c + 1.0 > safety_ceiling + 1e-6:
            return None  # room is already too warm relative to baseline+3.0°C to pre-heat

        # Target: at least 1.0°C above current room temperature AND at least 1.0°C above baseline
        elevated_target = max(current_room_temp_c + 1.0, self.baseline_temp_c + 1.0)
        elevated_target = min(safety_ceiling, round(elevated_target, 1))
        if elevated_target <= self.baseline_temp_c + self.OWNERSHIP_TOLERANCE_C:
            return None  # no headroom below the safety ceiling; an elevation would be indistinguishable

        self._record_write(elevated_target, "elevate", now)
        self.is_buffering = True
        self.buffering_started_at = now
        self._persist()
        return elevated_target

    def request_release(
        self,
        now: Optional[datetime] = None,
        force: bool = False
    ) -> Optional[float]:
        """
        Requests releasing preheat and returning room thermostat to baseline setpoint.
        Enforces the 45-minute minimum run unless force=True. Never blocked by the change budget.
        Returns the baseline temperature to restore, or None if release is delayed.
        """
        now = now or datetime.now(timezone.utc)
        if not self.is_buffering:
            return None

        if not force and self.buffering_started_at:
            elapsed_sec = (now - self.buffering_started_at).total_seconds()
            if elapsed_sec < self.MIN_RUN_DURATION_SECONDS:
                return None

        self.clean_history(now)
        self._record_write(self.baseline_temp_c, "restore", now)
        self.is_buffering = False
        self.buffering_started_at = None
        self._persist()
        return self.baseline_temp_c

    def watchdog_check(
        self,
        current_setpoint_c: Optional[float],
        now: Optional[datetime] = None
    ) -> Optional[float]:
        """
        Ownership-aware failsafe:
        - While buffering: if someone else changed the setpoint, hand control back (adopt it).
        - While idle: if OUR elevated value is still lingering (e.g. a restore write failed),
          restore the baseline. A setpoint the user chose is adopted as baseline, never reverted.
        Returns the setpoint to write, or None.
        """
        now = now or datetime.now(timezone.utc)
        if current_setpoint_c is None or self._settling(now):
            return None

        if self.is_buffering:
            if not self._is_our_value(current_setpoint_c):
                # User/automation took over during pre-heat: stop buffering, adopt their setpoint
                self.is_buffering = False
                self.buffering_started_at = None
                self.baseline_temp_c = float(current_setpoint_c)
                self.last_elevated_setpoint_c = None
                self._persist()
            return None

        if self._is_our_value(current_setpoint_c):
            # Our pre-heat value is still there while idle (restore failed / restart): restore it
            self._record_write(self.baseline_temp_c, "restore", now)
            self._persist()
            return self.baseline_temp_c
        if self.last_elevated_setpoint_c is not None:
            self.last_elevated_setpoint_c = None  # seen restored (or replaced by the user)
            self._persist()

        if 10.0 <= float(current_setpoint_c) <= 25.0 and abs(float(current_setpoint_c) - self.baseline_temp_c) > 0.05:
            # Idle and not ours: the user's setpoint is the baseline
            self.baseline_temp_c = float(current_setpoint_c)
            self._persist()
        return None

    def resolve_effective_baseline(
        self,
        current_setpoint_c: Optional[float],
        now: Optional[datetime] = None
    ) -> Tuple[float, bool]:
        """
        Resolves the true baseline comfort setpoint and whether Open HEMS buffering is active.
        - Respects the P1P2 write settling window so an in-flight write never cancels buffering
          or adopts a lingering pre-heat value as the user's baseline.
        - If Open HEMS is buffering and current_setpoint_c matches our elevated write (or its 0.5 C Daikin step):
          returns (self.baseline_temp_c, True).
        - If Open HEMS is buffering but current_setpoint_c was modified (user intervention):
          stops buffering, adopts the new setpoint as baseline, returns (new_setpoint, False).
        - If Open HEMS is idle:
          ignores our own lingering pre-heat value; otherwise adopts current_setpoint_c as baseline.
        """
        now = now or datetime.now(timezone.utc)
        if current_setpoint_c is None or self._settling(now):
            return round(self.baseline_temp_c, 1), self.is_buffering

        sp = float(current_setpoint_c)
        if self.is_buffering:
            if not self._is_our_value(sp):
                # User changed thermostat during preheat: stop buffering, adopt user setpoint
                self.is_buffering = False
                self.buffering_started_at = None
                self.baseline_temp_c = sp
                self.last_elevated_setpoint_c = None
                self._persist()
                return round(self.baseline_temp_c, 1), False
            return round(self.baseline_temp_c, 1), True

        if self._is_our_value(sp):
            # Our elevated setpoint is still lingering while idle (restore in flight or pending watchdog)
            return round(self.baseline_temp_c, 1), False

        # Idle: user setpoint on thermostat is adopted as baseline
        if 10.0 <= sp <= 25.0 and abs(sp - self.baseline_temp_c) > 0.05:
            self.baseline_temp_c = sp
            self._persist()
        return round(self.baseline_temp_c, 1), False


_GLOBAL_BUFFER_CONTROLLER: Optional[RoomThermostatBufferController] = None
_BUFFER_LOCK = threading.Lock()


def get_room_thermostat_buffer_controller() -> RoomThermostatBufferController:
    global _GLOBAL_BUFFER_CONTROLLER
    with _BUFFER_LOCK:
        if _GLOBAL_BUFFER_CONTROLLER is None:
            from layer4_control.dispatch_state import get_dispatch_state
            _GLOBAL_BUFFER_CONTROLLER = RoomThermostatBufferController(default_baseline_c=20.0, state=get_dispatch_state())
        return _GLOBAL_BUFFER_CONTROLLER

