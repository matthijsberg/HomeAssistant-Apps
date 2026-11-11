"""
Open HEMS: Heating Gatekeeper
=============================
Pre-Flight poortwachter voor Ruimteverwarming (CV Vloerbuffer).
Bewaakt hydraulische scheiding tijdens DHW, betonbuffer pre-heating en lockout-horizon.
"""

from typing import Optional
from layer4_control.preflight.models import GatekeeperDecision, SubsystemLiveState, LockoutHorizon


class HeatingGatekeeper:
    """Pre-Flight poortwachter voor Ruimteverwarming (CV Vloerbuffer)."""

    DEFAULT_PREHEAT_DELTA_C = 1.0
    DEFAULT_PREHEAT_LEAD_MINS = 90.0
    DEFAULT_MIN_CV_RUN_MINS = 30.0
    DEFAULT_MIN_PREHEAT_LEAD_MINS = 40.0

    def __init__(
        self,
        preheat_delta_c: float = DEFAULT_PREHEAT_DELTA_C,
        preheat_lead_mins: float = DEFAULT_PREHEAT_LEAD_MINS,
        min_cv_run_mins: float = DEFAULT_MIN_CV_RUN_MINS,
        min_preheat_lead_mins: float = DEFAULT_MIN_PREHEAT_LEAD_MINS,
    ):
        self.preheat_delta_c = preheat_delta_c
        self.preheat_lead_mins = preheat_lead_mins
        self.min_cv_run_mins = min_cv_run_mins
        self.min_preheat_lead_mins = min_preheat_lead_mins

    def evaluate(
        self,
        state: SubsystemLiveState,
        horizon: Optional[LockoutHorizon] = None,
        is_dhw_running: bool = False,
        is_heating_active: bool = False,
    ) -> GatekeeperDecision:
        # 1. Hydraulische isolatie: CV MOET UIT als boiler draait (blokkeert 9kW BUH)
        if is_dhw_running:
            return GatekeeperDecision(
                action="ISOLATE",
                reason="Hydraulische uitsluiting: CV-schakelaar geforceerd UIT ter bescherming tegen 9 kW back-up heater tijdens tapwater.",
                target_mode="off"
            )

        # 2. Lockout-horizon checks
        if horizon and horizon.minutes_until_lockout is not None:
            mins_left = horizon.minutes_until_lockout

            # A. Te dicht op de spits voor een nieuwe run: voorkom inefficiënte korte run van < 30 min
            if not is_heating_active and 0 < mins_left < self.min_cv_run_mins:
                min_comfort = state.room_setpoint_c - 0.5
                if state.room_temp_c >= min_comfort:
                    return GatekeeperDecision(
                        action="DEFER",
                        reason=f"Spitsblok start over {mins_left:.0f}m (< {self.min_cv_run_mins:.0f}m minimum runduur). "
                               f"Kamer ({state.room_temp_c:.1f}°C) comfortabel genoeg (>= {min_comfort:.1f}°C); run uitgesteld tot na de spits.",
                        target_mode="normal",
                        metrics={"minutes_until_lockout": mins_left, "min_cv_run_mins": self.min_cv_run_mins}
                    )

            # B. Geadviseerd uit respecteren & nuanceren:
            # - Als er AL een run bezig is (en gemoduleerd draait): laat deze gerust doorlopen in stand auto (geen koude herstartkosten later).
            # - Als de pomp stilstaat: GEEN nieuwe run starten tijdens geadviseerd uit (starten kost relatief veel energie bij verhoogd tarief).
            if horizon.is_currently_advised_off:
                if is_heating_active:
                    return GatekeeperDecision(
                        action="CONTINUE_RUN",
                        reason=f"Lopende stookrun gedetecteerd tijdens geadviseerd uit (P75 piekschouder); "
                               f"mag gemoduleerd doorlopen in stand auto om koude herstartverliezen te voorkomen.",
                        target_mode="normal",
                        metrics={"is_heating_active": True, "is_advised_off": True}
                    )
                else:
                    min_comfort = state.room_setpoint_c - 0.5
                    if state.room_temp_c >= min_comfort:
                        return GatekeeperDecision(
                            action="DEFER",
                            reason=f"Geadviseerd uit (P75 piekschouder) actief en pomp staat stil. "
                                   f"Nieuwe koude start geweerd (kamer {state.room_temp_c:.1f}°C >= {min_comfort:.1f}°C) om startverliezen bij verhoogd tarief te voorkomen.",
                            target_mode="normal",
                            metrics={"is_heating_active": False, "is_advised_off": True}
                        )

            # C. Spits-anticipatie: Betonbuffer preventief voorverwarmen mits voldoende effectieve aanlooptijd (minimaal 40 min)
            if self.min_preheat_lead_mins <= mins_left <= self.preheat_lead_mins:
                target_elevated = state.room_setpoint_c + self.preheat_delta_c
                return GatekeeperDecision(
                    action="PREHEAT",
                    reason=f"Spitsblok start over {mins_left:.0f}m. "
                           f"Kamerthermostaat preventief verhoogd naar {target_elevated:.1f}°C (+{self.preheat_delta_c:.1f}°C) om betonbuffer op te laden.",
                    target_mode="advised_on",
                    target_temp_c=target_elevated,
                    metrics={"minutes_until_lockout": mins_left, "preheat_target_c": target_elevated}
                )

        return GatekeeperDecision(action="NORMAL", reason="Normaal stooklijnbedrijf.", target_mode="normal")
