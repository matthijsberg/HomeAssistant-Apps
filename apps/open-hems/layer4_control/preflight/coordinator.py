"""
Open HEMS: Pre-Flight Coordinator
=================================
Orchestrates pre-flight gatekeeper evaluations across all energy subsystems.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from layer4_control.preflight.models import SubsystemLiveState, LockoutHorizon, GatekeeperDecision
from layer4_control.preflight.dhw_gatekeeper import DhwGatekeeper
from layer4_control.preflight.heating_gatekeeper import HeatingGatekeeper
from layer4_control.preflight.battery_gatekeeper import BatteryGatekeeper


def extract_lockout_horizon(
    plan: Optional[Any],
    now: Optional[datetime] = None
) -> LockoutHorizon:
    """Extracts the next lockout horizon from the active canonical dispatch plan."""
    now_dt = now or datetime.now(timezone.utc)
    if not plan or not getattr(plan, "slots", None):
        return LockoutHorizon(evaluated_at=now_dt)

    first_slot_mode = getattr(plan.slots[0].mode_code, "value", plan.slots[0].mode_code)
    is_currently_locked = (str(first_slot_mode).strip().lower() == "forced_off")
    is_currently_advised_off = (str(first_slot_mode).strip().lower() in ("advised_off", "p75_advies"))

    lockout_start = None
    lockout_end = None
    in_lockout_seq = False

    for slot in plan.slots:
        s_val = getattr(slot.mode_code, "value", slot.mode_code)
        is_lock = (str(s_val).strip().lower() == "forced_off")
        raw_dt = getattr(slot, "dt_iso", None) or getattr(slot, "start_time_iso", None)
        if not raw_dt:
            continue
        try:
            s_time = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))
        except Exception:
            continue

        if is_lock:
            if lockout_start is None:
                lockout_start = s_time
            in_lockout_seq = True
            dur_mins = getattr(slot, "duration_minutes", 15)
            lockout_end = s_time + timedelta(minutes=float(dur_mins))
        elif in_lockout_seq:
            # Reeks is voorbij
            break

    return LockoutHorizon(
        evaluated_at=now_dt,
        next_lockout_start=lockout_start,
        next_lockout_end=lockout_end,
        is_currently_locked=is_currently_locked,
        is_currently_advised_off=is_currently_advised_off
    )


class PreflightCoordinator:
    """Coördineert de preflight evaluatie over alle energiesubsystemen."""

    def __init__(
        self,
        dhw_gatekeeper: Optional[DhwGatekeeper] = None,
        heating_gatekeeper: Optional[HeatingGatekeeper] = None,
        battery_gatekeeper: Optional[BatteryGatekeeper] = None,
    ):
        self.dhw = dhw_gatekeeper or DhwGatekeeper()
        self.heating = heating_gatekeeper or HeatingGatekeeper()
        self.battery = battery_gatekeeper or BatteryGatekeeper()

    def evaluate_all(
        self,
        state: SubsystemLiveState,
        plan: Optional[Any],
        now: Optional[datetime] = None,
        is_heating_active: bool = False,
    ) -> Dict[str, Any]:
        horizon = extract_lockout_horizon(plan, now=now)

        cur_mode = "normal"
        target_t = 50.0
        if plan and getattr(plan, "slots", None):
            val = getattr(plan.slots[0].mode_code, "value", plan.slots[0].mode_code)
            cur_mode = str(val).strip().lower()
            if hasattr(plan.slots[0], "target_temp_c") and plan.slots[0].target_temp_c:
                target_t = plan.slots[0].target_temp_c

        dhw_dec = self.dhw.evaluate(state, horizon, planned_mode=cur_mode, target_temp_c=target_t)
        is_dhw_running = dhw_dec.is_start

        heat_dec = self.heating.evaluate(
            state,
            horizon,
            is_dhw_running=is_dhw_running,
            is_heating_active=is_heating_active
        )
        bat_dec = self.battery.evaluate(state, horizon)

        return {
            "dhw": dhw_dec,
            "heating": heat_dec,
            "battery": bat_dec,
            "horizon": horizon
        }
