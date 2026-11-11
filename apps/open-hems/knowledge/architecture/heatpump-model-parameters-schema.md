---
type: Invariant
title: Heat Pump Model Parameters Schema & Key Ownership
description: Complete specification of /config/heatpump_model_parameters.json with engineering units, owners (writers), consumers, and physical clamping bounds.
tags: [architecture, schema, parameters, calibration, 2r1c, layer2]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_params_store", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: params-store
    resource: layer2_calibration/params_store.py
    title: Atomic Locked Model Parameters Store
    author: agent:hermes
  - id: learned-forecaster
    resource: layer2_calibration/learned_forecaster.py
    title: Learned Forecaster & FORECASTER_OWNED_KEYS
    author: agent:hermes
---

# Heat Pump Model Parameters Schema & Key Ownership

This document defines the authoritative schema for `/config/heatpump_model_parameters.json`. To prevent race conditions and lost updates during parallel execution, all disk mutations are governed by `layer2_calibration/params_store.py` with an atomic read-merge-write file lock.

## 1. Forecaster-Owned Keys (`FORECASTER_OWNED_KEYS`)
These keys are updated dynamically by the weekly self-calibration and daily learning loop (`layer2_calibration/learned_forecaster.py`). Only these specific keys are overwritten during learning cycles; static and user-configured parameters remain strictly preserved.

| Parameter Key | Engineering Unit | Bounds | Description & Consumers |
|---|---|---|---|
| `building.ua_base_w_per_k` | $\text{W/K}$ | $[50.0, 600.0]$ | Overall thermal transmission loss of the building envelope. Consumed by `SpaceHeatingPolicy` (2R1C thermal model). |
| `building.c_solar_pv_ratio` | $\text{kWh}_{\text{th}} / \text{kWh}_{\text{pv}}$ | $[0.10, 4.00]$ | Thermal gain delivered to indoor living space per kWh of rooftop PV generation. No longer read by `SpaceHeatingPolicy` (since 0.108.0 solar gain uses irradiance, see `space-heating-model`). |
| `building.floor_capacity_kwh_per_k` | $\text{kWh/K}$ | $[5.0, 50.0]$ | Thermal heat capacity of the concrete underfloor heating screed mass ($C_{\text{floor}}$). No longer read by `SpaceHeatingPolicy` (since 0.108.0 the fitted network in `space-heating-model` is used; the forecaster only scales this value with UA, it is not a fit). |
| `unallocated.night_baseload_floor_w` | $\text{W}$ | $[100.0, 800.0]$ | Baseline household electrical consumption during nighttime hours (01:00–05:00). Consumed by `TelemetrySanitizer` and `PowerSlotter`. |
| `solar.performance_ratio_pct` | $\%$ | $[50.0, 110.0]$ | Calibrated system performance ratio vs theoretical clear-sky irradiance. Consumed by solar forecast assimilator. |
| `last_trained` | ISO 8601 UTC | — | Timestamp of the most recent successful calibration run. Consumed by UI Diagnostics. |
| `metrics` | JSON Object | — | Fit quality statistics (`samples_evaluated`, `r_squared`, `rmse_w`, `mae_w`, `mape_pct`). Consumed by UI Model tab. |

## 2. Static Physical Model & Plant Specifications
These parameters are statically declared from commissioning datasheets, physical dimensions, or manual site tuning. The automated forecaster is strictly forbidden from overwriting these keys.

### Building Thermal Envelope (`building`)
* `building.c_wind_w_per_k_ms` ($\text{W/(K}\cdot\text{m/s)}$): Additional transmission loss induced by ambient wind speed. Bounds: $[1.0, 60.0]$. Default: $15.0$. Note: Values outside this range (e.g. historical unscaled artifact $0.208$) are rejected by runtime validators, falling back to default.
* `building.c_solar_passive` ($\text{m}^2$): Effective fenestration aperture for direct solar radiation (GHI). Bounds: $[0.05, 3.50]$. Default: $1.15$.
* `building.target_temp_day_c` ($^\circ\text{C}$): Comfort daytime setpoint. Default: $20.0$.
* `building.target_temp_night_c` ($^\circ\text{C}$): Setback nighttime setpoint. Default: $17.5$.
* `building.summer_lockout_mean_c` ($^\circ\text{C}$): 24h outdoor mean temperature above which space heating is locked out. Default: $15.5$.
* `building.summer_lockout_max_c` ($^\circ\text{C}$): Peak outdoor temperature threshold for summer lockout. Default: $18.0$.

### Heat Pump Hardware (`heat_pump`)
* `heat_pump.nominal_power_w` ($\text{W}$): Rated maximum electrical compressor power (Daikin 18 kW HT: $5500\text{ W}$ el, $18000\text{ W}$ th).
* `heat_pump.standby_power_w` ($\text{W}$): Continuous quiescent electronics draw ($34.0\text{ W}$).
* `heat_pump.flow_temp_cv_c` ($^\circ\text{C}$): Underfloor heating design flow supply temperature ($35.0\text{ }^\circ\text{C}$).
* `heat_pump.flow_temp_dhw_c` ($^\circ\text{C}$): Heat exchanger supply flow temperature during DHW charging ($52.0\text{ }^\circ\text{C}$).
* `heat_pump.carnot_efficiency` (ratio): Thermodynamic Carnot fraction of the R-32 vapor compression cycle ($0.48$).
* `heat_pump.defrost_threshold_c` ($^\circ\text{C}$): Outdoor temperature below which evaporator coil icing triggers defrost cycles ($4.5\text{ }^\circ\text{C}$).
* `heat_pump.defrost_cop_penalty` (ratio): Efficiency multiplier during defrost weather ($0.82$).

### Domestic Hot Water Storage (`dhw_tank` & `dhw_power`)
* `dhw_tank.volume_liters` ($\text{L}$): Rated liquid capacity ($350.0\text{ L}$).
* `dhw_tank.target_temp_c` ($^\circ\text{C}$): Baseline comfort setpoint ($50.0\text{ }^\circ\text{C}$).
* `dhw_tank.standby_loss_w_per_k` ($\text{W/K}$): Calibrated tank cooling loss coefficient ($2.38\text{ W/K}$ on Culemborg site).
* `dhw_power.p_nom_50` ($\text{kW}$): Nominal electrical charging power at $50\text{ }^\circ\text{C}$ tank ($2.72\text{ kW}$). Bounds: $[1.6, 3.5]$.
* `dhw_cop.cop_50` (ratio): Measured COP at $50\text{ }^\circ\text{C}$ tank and $10\text{ }^\circ\text{C}$ outdoor ($2.0$). Bounds: $[1.4, 3.2]$.
