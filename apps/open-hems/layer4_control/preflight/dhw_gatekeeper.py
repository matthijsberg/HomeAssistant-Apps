"""
Open HEMS: DHW Gatekeeper
=========================
Pre-Flight poortwachter voor het 350L Daikin boilervat.
Bepaalt of een opwarmcyclus mag starten, uitgesteld moet worden of direct geëscaleerd wordt.
"""

from typing import Optional
from layer4_control.preflight.models import GatekeeperDecision, SubsystemLiveState, LockoutHorizon
from layer4_control.preflight.estimator import estimate_dhw_run_duration_mins, estimate_dhw_standby_loss_c


class DhwGatekeeper:
    """
    Pre-Flight poortwachter voor het 350L Daikin boilervat.
    Bepaalt of een opwarmcyclus mag starten, uitgesteld moet worden of direct geëscaleerd wordt.
    """

    def __init__(
        self,
        emergency_floor_c: float = 38.0,
        comfort_buffer_c: float = 40.0,
        standard_target_c: float = 50.0,
        min_completion_ratio: float = 0.80
    ):
        self.emergency_floor_c = emergency_floor_c
        self.comfort_buffer_c = comfort_buffer_c
        self.standard_target_c = standard_target_c
        self.min_completion_ratio = min_completion_ratio

    def evaluate(
        self,
        state: SubsystemLiveState,
        horizon: LockoutHorizon,
        planned_mode: str = "normal",
        target_temp_c: Optional[float] = None
    ) -> GatekeeperDecision:
        target_c = target_temp_c or self.standard_target_c

        # 1. Nood-comfort: Vat onder noodgrens (Priority 1)
        if state.dhw_temp_c < self.emergency_floor_c:
            return GatekeeperDecision(
                action="EMERGENCY",
                reason=f"🚨 Boilervat ({state.dhw_temp_c:.1f}°C) onder noodgrens van {self.emergency_floor_c:.1f}°C. Directe noodopwarming geactiveerd.",
                target_mode="max_on" if target_c >= 55.0 else "forced_on",
                target_temp_c=target_c,
                metrics={"current_temp_c": state.dhw_temp_c, "emergency_floor_c": self.emergency_floor_c}
            )

        # 2. Reeds op gewenste doeltemperatuur
        if state.dhw_temp_c >= (target_c - 0.5):
            return GatekeeperDecision(
                action="IDLE",
                reason=f"Boilervat ({state.dhw_temp_c:.1f}°C) is reeds op doeltemperatuur ({target_c:.1f}°C). Geen run nodig.",
                target_mode="normal",
                target_temp_c=target_c
            )

        # 3. Hardware / Dwell-time beveiliging
        if state.compressor_dwell_active:
            return GatekeeperDecision(
                action="DEFER",
                reason="Compressor dwell-time (minimale rusttijd) is actief ter bescherming van de compressor.",
                target_mode="normal"
            )

        # Als de planner geen actie vraagt, respecteren we dat
        if planned_mode in ("normal", "off", "standby") and state.dhw_temp_c >= self.comfort_buffer_c:
            return GatekeeperDecision(
                action="NORMAL",
                reason=f"Geen opwarming gevraagd door planning; vat ({state.dhw_temp_c:.1f}°C) boven comfortbuffer.",
                target_mode="normal"
            )

        # 4. Horizon & Spits-anticipatie (Kan de run worden afgemaakt?)
        est_duration_mins = estimate_dhw_run_duration_mins(
            t_start_c=state.dhw_temp_c,
            t_target_c=target_c,
            t_outdoor_c=state.outdoor_temp_c
        )
        mins_to_lockout = horizon.minutes_until_lockout

        if mins_to_lockout is not None:
            min_required_time = est_duration_mins * self.min_completion_ratio
            if mins_to_lockout < min_required_time:
                # We halen de run waarschijnlijk niet vóór de spits.
                # Bepaal afkoeling tijdens de spits:
                expected_loss = estimate_dhw_standby_loss_c(horizon.lockout_duration_hours)
                temp_after_lockout = state.dhw_temp_c - expected_loss

                if temp_after_lockout >= self.comfort_buffer_c:
                    # Vat blijft warm genoeg tijdens de spits -> Wachten loont!
                    return GatekeeperDecision(
                        action="DEFER",
                        reason=f"Spitsblok start over {mins_to_lockout:.0f}m (run duurt {est_duration_mins:.0f}m). "
                               f"Vat blijft met naar verwachting {temp_after_lockout:.1f}°C boven comfortgrens ({self.comfort_buffer_c:.1f}°C). "
                               f"Opwarming uitgesteld tot na de spits.",
                        target_mode="normal",
                        metrics={
                            "est_duration_mins": est_duration_mins,
                            "mins_to_lockout": mins_to_lockout,
                            "temp_after_lockout": temp_after_lockout
                        }
                    )
                else:
                    # Vat zou te koud worden tijdens de spits -> Nu alvast maximaal laden!
                    return GatekeeperDecision(
                        action="START_PREEMPTIVE",
                        reason=f"Spitsblok nadert over {mins_to_lockout:.0f}m, maar zonder lading zakt vat naar {temp_after_lockout:.1f}°C "
                               f"(onder comfortgrens van {self.comfort_buffer_c:.1f}°C). Pre-emptieve deellading gestart.",
                        target_mode="max_on" if target_c >= 55.0 else "forced_on",
                        target_temp_c=target_c,
                        metrics={
                            "est_duration_mins": est_duration_mins,
                            "mins_to_lockout": mins_to_lockout,
                            "temp_after_lockout": temp_after_lockout
                        }
                    )

        # 5. Geen belemmeringen: run normaal starten
        return GatekeeperDecision(
            action="START_FULL",
            reason=f"Opwarming gestart naar {target_c:.1f}°C (geschatte duur: {est_duration_mins:.0f}m, geen blokkades).",
            target_mode="max_on" if target_c >= 55.0 else "forced_on",
            target_temp_c=target_c,
            metrics={"est_duration_mins": est_duration_mins}
        )
