"""
Open HEMS: Pre-Flight Thermodynamic Estimator
=============================================
Calculates physical run duration for the 350L DHW tank and standby loss during lockouts.
"""

from typing import Optional
from models.physics import dhw_electric_power_kw, dhw_cop

DHW_TANK_CAPACITY_KWH_PER_K = 350.0 * 1.163 / 1000.0  # 0.407 kWh/K
DHW_STANDBY_LOSS_K_PER_HOUR = 0.25                    # ~6 K/dag bij 20°C ambient


def estimate_dhw_run_duration_mins(
    t_start_c: float,
    t_target_c: float = 50.0,
    t_outdoor_c: Optional[float] = 10.0,
    params: Optional[dict] = None
) -> float:
    """Schat de opwarmduur in minuten voor het 350L boilervat."""
    if t_start_c >= t_target_c:
        return 0.0

    delta_t = t_target_c - t_start_c
    q_th_kwh = DHW_TANK_CAPACITY_KWH_PER_K * delta_t

    # Gemiddelde temperatuur tijdens de run voor COP en elektrisch vermogen
    t_mid = (t_start_c + t_target_c) / 2.0
    p_el = dhw_electric_power_kw(t_mid, t_outdoor_c=t_outdoor_c, params=params)
    cop = dhw_cop(t_mid, t_outdoor_c=t_outdoor_c, params=params)

    p_th = max(1.0, p_el * cop)  # Thermisch vermogen in kW
    duration_hours = q_th_kwh / p_th
    return round(duration_hours * 60.0, 1)


def estimate_dhw_standby_loss_c(duration_hours: float) -> float:
    """Schat het temperatuurverlies in Kelvin over een gegeven tijdsduur."""
    return round(max(0.0, duration_hours * DHW_STANDBY_LOSS_K_PER_HOUR), 2)
