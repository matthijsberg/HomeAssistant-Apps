---
type: Architecture Invariant
title: Solar Microclimate Nowcasting & Passive Glazing Calibration
description: Ingestion of omnidirectional Global Horizontal Irradiance (GHI W/m2) via local pyranometers (Ecowitt Wittboy) and Open-Meteo, decoupling building passive thermal gains from rooftop PV array orientation.
tags: [weather, solar, nowcasting, 2r1c, architecture]
status: stable
generated: { by: "agent:hermes", at: "2026-10-05T08:15:00Z" }
verified:
  - { by: "process:pytest_nowcasting", at: "2026-10-05T08:15:00Z" }
sources:
  - id: wittboy-sensor
    resource: sensor.wittboy_gw2000a_weather_station_gw2000a_solar_radiation
    title: Ecowitt Wittboy WS90 / GW2000A Solar Radiation Sensor
  - id: open-meteo-api
    resource: https://api.open-meteo.com/v1/forecast
    title: Open-Meteo Shortwave Radiation Forecast
---

# Solar Microclimate Nowcasting & Passive Glazing Calibration

## Architectural Problem
Prior architectures derived building passive solar thermal gain directly from rooftop photovoltaic electrical generation:
$$Q_{\text{solar}} = c_{\text{solar}} \cdot P_{\text{pv\_kw}}$$

This introduced severe physical errors:
1. **Azimuth Blindness:** When rooftop panels face South-West (e.g. 225° SW), they generate negligible electricity during morning hours (08:30–11:30). However, vertical windows on the South-East facade receive direct, perpendicular low-angle solar irradiance, rapidly warming the building interior.
2. **Inverter & Tilt Distortions:** Roof slope (34°), inverter clipping (5.5 kW ceiling), and panel efficiency (18–21%) distorted the estimate of total atmospheric energy hitting the building envelope.
3. **Pessimistic Coasting:** The 2R1C model predicted immediate room cooling during sunny autumn/winter mornings, triggering premature and unnecessary floor pre-heat cycles.

## Invariant Principles

### 1. Separation of Electrical PV Generation from Atmospheric Irradiance
The system treats electrical generation and atmospheric solar irradiance as strictly orthogonal vectors:
* **Photovoltaic Power ($P_{\text{pv}}$ in kW):** Governed by panel tilt, azimuth, temperature coefficient, and inverter bounds. Used exclusively for electrical dispatch, battery arbitrage, and self-consumption accounting.
* **Global Horizontal Irradiance ($GHI$ in $\text{W/m}^2$):** Measured omnidirectionally on the horizontal plane by a local pyranometer (Ecowitt Wittboy GW2000A). Represents total atmospheric energy independent of building or roof angles.

### 2. Multi-Facade Passive Thermal Aperture
Thermal solar gain entering the room envelope ($Q_{\text{solar}}$ in $\text{kW}_{\text{th}}$) is modeled directly from horizontal irradiance:
$$Q_{\text{solar}} = A_{\text{effective\_glass}} \cdot \frac{\text{GHI}}{1000}$$

Where $A_{\text{effective\_glass}}$ (in $\text{m}^2$) represents the total effective solar aperture of the building envelope, combining:
* South-East glazing (morning gain)
* South-West glazing (afternoon gain)
* Window solar heat gain coefficient (g-value) and internal shading factors.

### 3. Realtime Observation Nowcasting ($C^1$ Cosine Easing)
To bridge regional Numerical Weather Predictions (NWP from Open-Meteo) with live local microclimate observations (Wittboy):
$$\text{GHI}_{\text{assimilated}}(t) = \text{GHI}_{\text{forecast}}(t) + \Delta_{\text{live}} \cdot w(t)$$

With $C^1$ continuous cosine easing weight:
$$w(t) = \begin{cases} 
1.0 & \text{for } t \le 0 \\
0.5 \cdot \left(1 + \cos\left(\frac{\pi t}{H}\right)\right) & \text{for } 0 < t < H \\
0.0 & \text{for } t \ge H 
\end{cases}$$
Where $H = 2.0\text{ hours}$. This ensures zero-derivative smoothness at both boundaries, preventing artificial step-changes or optimizer chatter while anchoring the immediate plan in ground truth.

### 4. Slow-Drift Self-Learning Governance (EWMA)
Daily calibration updates the effective solar aperture $A_{\text{effective\_glass}}$ via 3D Ordinary Least Squares (OLS) regression over heating days:
$$A_{\text{glass}}^{(t)} = (1 - \alpha) \cdot A_{\text{glass}}^{(t-1)} + \alpha \cdot A_{\text{glass, OLS}}$$
With learning rate $\alpha = 0.05$ (5% daily weight). Physical clamping bounds $[0.05, 2.50]$ prevent sensor glitches or anomalous weather days from destabilizing the core building model.
