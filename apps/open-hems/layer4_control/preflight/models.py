"""
Open HEMS: Pre-Flight Gatekeeper Models
=======================================
Pure dataclasses for gatekeeper decisions, lockout horizon, and live subsystem states.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class GatekeeperDecision:
    action: str                       # START, START_FULL, START_PREEMPTIVE, DEFER, EMERGENCY, IDLE, NORMAL, ISOLATE, HOLD, ALLOW
    reason: str                       # Human-readable explanation
    target_mode: str = "normal"       # SG1 (forced_off), SG2 (normal), SG3 (advised_on), SG4 (max_on/forced_on)
    target_temp_c: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_deferred(self) -> bool:
        return self.action == "DEFER"

    @property
    def is_start(self) -> bool:
        return self.action in ("START", "START_FULL", "START_PREEMPTIVE", "EMERGENCY")


@dataclass(frozen=True)
class LockoutHorizon:
    evaluated_at: datetime
    next_lockout_start: Optional[datetime] = None
    next_lockout_end: Optional[datetime] = None
    is_currently_locked: bool = False
    is_currently_advised_off: bool = False

    @property
    def minutes_until_lockout(self) -> Optional[float]:
        if self.next_lockout_start is None:
            return None
        delta = (self.next_lockout_start - self.evaluated_at).total_seconds() / 60.0
        return max(0.0, delta)

    @property
    def lockout_duration_hours(self) -> float:
        if self.next_lockout_start is None or self.next_lockout_end is None:
            return 0.0
        return max(0.0, (self.next_lockout_end - self.next_lockout_start).total_seconds() / 3600.0)


@dataclass(frozen=True)
class SubsystemLiveState:
    dhw_temp_c: float
    outdoor_temp_c: float
    room_temp_c: float = 20.5
    room_setpoint_c: float = 20.5
    battery_soc_pct: float = 50.0
    compressor_dwell_active: bool = False
    p1p2_write_budget_low: bool = False
