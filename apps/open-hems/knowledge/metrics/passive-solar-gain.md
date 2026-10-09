---
type: Metric
title: Passive Solar Thermal Gain
description: Accounting of solar radiative thermal energy entering the building envelope through fenestration, distinct from electrical PV power.
tags: [thermal, solar, heat, 2r1c, metric]
status: stable
generated: { by: "agent:hermes", at: "2026-10-05T08:15:00Z" }
verified:
  - { by: "process:pytest_space_heating_policy", at: "2026-10-05T08:15:00Z" }
sources:
  - id: wittboy-sensor
    resource: sensor.wittboy_gw2000a_weather_station_gw2000a_solar_radiation
    title: Wittboy GW2000A Solar Radiation Sensor
---

# Passive Solar Thermal Gain (Passieve Zonnewinst)

## Definition
Measures the thermal radiative heat flux ($Q_{\text{solar}}$ in $\text{kW}_{\text{th}}$) entering the conditioned living space directly through transparent building elements (windows, sliding doors, glazed facades).

Unlike rooftop photovoltaic generation ($P_{\text{pv}}$ in $\text{kW}_{\text{el}}$), passive solar gain directly heats the indoor air and internal thermal mass (concrete floor screed and walls) without electrical conversion losses.

## Mathematical Formulation
$$Q_{\text{solar}} = A_{\text{effective\_glass}} \cdot \frac{\text{GHI}}{1000}$$

Where:
* $\text{GHI}$: Global Horizontal Irradiance in $\text{W/m}^2$, measured locally by pyranometer or provided by regional weather forecasting.
* $A_{\text{effective\_glass}}$: Calibrated effective glazing aperture in $\text{m}^2$, integrating gross window area ($A_w$), solar heat gain coefficient ($g$), frame fraction ($F_f$), and angular shading ($F_s$).

## Role in 2R1C Thermal Balance
Passive solar thermal gain acts as a free positive heat source in the indoor room air node:
$$\frac{dT_{\text{room}}}{dt} = \frac{Q_{\text{floor}\to\text{room}} + Q_{\text{solar}} - Q_{\text{loss}}}{C_{\text{air}}}$$

During clear autumn and winter days with low solar elevation, $Q_{\text{solar}}$ frequently exceeds total transmission losses ($Q_{\text{loss}}$), causing room temperature to naturally rise above setpoint (+1.5°C to +2.5°C) without active space heating.

## Polarity & Units
* **Engineering Unit:** $\text{kW}_{\text{th}}$ (instantaneous power) or $\text{kWh}_{\text{th}}$ (cumulative energy per interval).
* **Polarity:** Always non-negative ($Q_{\text{solar}} \ge 0$). In thermal balance charts, it is rendered as an incoming heat flux reducing net required heat pump thermal output.
