---
type: Metric
title: Passive Solar Thermal Gain & PV Substitution Ratio
description: Accounting of solar radiative thermal energy entering fenestration and PV-to-thermal substitution ratio in building envelope modeling.
tags: [thermal, solar, heat, 2r1c, metric, calibration]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_space_heating_policy", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_learned_forecaster", at: "2026-10-09T00:00:00Z" }
sources:
  - id: wittboy-sensor
    resource: sensor.wittboy_gw2000a_weather_station_gw2000a_solar_radiation
    title: Wittboy GW2000A Solar Radiation Sensor
  - id: learned-forecaster
    resource: layer2_calibration/learned_forecaster.py
    title: Hybrid Rank-Checked Building Model Forecaster
    author: agent:hermes
  - id: space-heating-policy
    resource: layer3_scheduling/space_heating_policy.py
    title: Space Heating Policy MPC Controller
    author: agent:hermes
---

# Passive Solar Thermal Gain & PV Substitution Ratio

## 1. Passive Solar Glazing Aperture (`building.c_solar_passive`)
Measures the thermal radiative heat flux ($Q_{\text{solar}}$ in $\text{kW}_{\text{th}}$) entering the conditioned living space directly through transparent building elements (windows, sliding doors, glazed facades).

### Mathematical Formulation
$$Q_{\text{solar}} = c_{\text{solar\_passive}} \cdot \frac{\text{GHI}}{1000}$$

Where:
* $\text{GHI}$: Global Horizontal Irradiance in $\text{W/m}^2$, measured locally by pyranometer or regional solar forecasts.
* $c_{\text{solar\_passive}}$: Calibrated effective glazing aperture in $\text{m}^2$ ($A_{\text{effective\_glass}}$), integrating gross window area ($A_w$), solar heat gain coefficient ($g$), frame fraction ($F_f$), and angular shading factor ($F_s$).
* **Bounds:** $[0.05, 3.50]\text{ m}^2$. Default: $1.15\text{ m}^2$.

## 2. PV-to-Thermal Substitution Ratio (`building.c_solar_pv_ratio`)
When local pyranometer irradiance is unavailable or for coarse space-heating dispatch, rooftop photovoltaic generation correlates strongly with incident solar radiation on the building envelope.

### Mathematical Formulation
$$Q_{\text{solar\_effective}} = c_{\text{solar\_pv\_ratio}} \cdot P_{\text{pv\_kwh}}$$

Where:
* $c_{\text{solar\_pv\_ratio}}$ represents the ratio of thermal gain delivered to the indoor space per kilowatt-hour of rooftop electrical generation ($\text{kWh}_{\text{th}} / \text{kWh}_{\text{pv}}$).
* **Calibration & Ownership:** Owned exclusively by `layer2_calibration/learned_forecaster.py` via rank-checked multi-variable OLS regression on $[\Delta T, E_{\text{pv}}, 1]$.
* **Consumer:** Read directly by `layer3_scheduling/space_heating_policy.py` to offset space-heating demand during sunny intervals.
* **Bounds:** $[0.10, 4.00]\text{ kWh}_{\text{th}}/\text{kWh}_{\text{pv}}$. Default: $0.85$.

## 3. Role in 2R1C Thermal Balance
Passive solar thermal gain acts as a positive heat flux in the indoor room air node:
$$\frac{dT_{\text{room}}}{dt} = \frac{Q_{\text{floor}\to\text{room}} + Q_{\text{solar}} - Q_{\text{loss}}}{C_{\text{air}}}$$

During clear days with low winter solar elevation, $Q_{\text{solar}}$ frequently exceeds envelope transmission losses ($Q_{\text{loss}}$), elevating indoor temperature naturally above setpoint (+1.5 °C to +2.5 °C) without active compressor operation.
