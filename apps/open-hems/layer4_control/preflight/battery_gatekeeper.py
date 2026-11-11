"""
Open HEMS: Battery Gatekeeper
=============================
Pre-Flight poortwachter voor de 15 kWh Thuisaccu.
Bewaakt spitsreservering en voorkomt ongewenst ontladen vlak voor dure piekuren.
"""

from typing import Optional
from layer4_control.preflight.models import GatekeeperDecision, SubsystemLiveState, LockoutHorizon


class BatteryGatekeeper:
    """Pre-Flight poortwachter voor de 15 kWh Thuisaccu."""

    def __init__(self, spits_reserve_kwh: float = 4.0, battery_capacity_kwh: float = 15.0):
        self.spits_reserve_kwh = spits_reserve_kwh
        self.battery_capacity_kwh = battery_capacity_kwh

    def evaluate(
        self,
        state: SubsystemLiveState,
        horizon: Optional[LockoutHorizon] = None,
        requested_mode: str = "IDLE"
    ) -> GatekeeperDecision:
        if horizon and horizon.minutes_until_lockout is not None and horizon.minutes_until_lockout <= 60.0:
            current_kwh = (state.battery_soc_pct / 100.0) * self.battery_capacity_kwh
            if current_kwh < self.spits_reserve_kwh and requested_mode == "DISCHARGE":
                return GatekeeperDecision(
                    action="HOLD",
                    reason=f"Spitsblok nadert over {horizon.minutes_until_lockout:.0f}m. Accu ({current_kwh:.1f} kWh) "
                           f"onder vereiste spitsreserve ({self.spits_reserve_kwh:.1f} kWh); ontladen geblokkeerd.",
                    target_mode="HOLD",
                    metrics={
                        "current_kwh": current_kwh,
                        "spits_reserve_kwh": self.spits_reserve_kwh,
                        "minutes_until_lockout": horizon.minutes_until_lockout
                    }
                )
        return GatekeeperDecision(action="ALLOW", reason="Batterij-actie toegestaan.", target_mode=requested_mode)
