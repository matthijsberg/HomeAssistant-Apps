---
type: Invariant
title: Space Heating Model (Building Network, Daikin Loop, Measured COP)
description: How SpaceHeatingPolicy predicts room, floor, heat and electricity, which parameters it uses, where they come from, and how pre-heat is decided.
tags: [architecture, invariant, space_heating, model, daikin, layer3]
status: draft
generated: { by: "agent:claude", at: "2026-10-13T00:00:00Z" }
verified:
  - { by: "process:pytest_space_heating_policy", at: "2026-10-13T00:00:00Z" }
  - { by: "process:planner_replay_influx_hassio_winter_2025_26", at: "2026-10-13T00:00:00Z" }
sources:
  - id: space-heating-policy
    resource: layer3_scheduling/space_heating_policy.py
    title: Space Heating Policy
    author: agent:claude
  - id: floor-state-estimation
    resource: knowledge/architecture/floor-state-estimation.md
    title: Floor (Screed) State Estimation
    author: agent:claude
---

# Space Heating Model

## 1. Why
The previous policy imposed an electric power curve with start-up boost and taper, switched it with a simulated room thermostat (2 h minimum run), coupled floor and air with R = 0.08 K/kW and used a Carnot COP. Replayed over winter 2025-26 it planned 37 % too little electricity and showed short high-power blocks, while the Daikin really runs for many hours at moderate power.

## 2. Model
All parameters were fitted on InfluxDB `hassio`, 2025-11-01..2026-03-31, 15-minute slots, alternating ISO weeks for training and testing. The room reference is the Madoka (the heat pump controls on it).

**Building (2-node network)**, UA fixed to the calibrated envelope value (`building.ua_base_w_per_k`):

| Parameter | Value | Meaning |
|---|---|---|
| `C_ROOM_KWH_PER_K` | 12.8 kWh/K | room node: air, walls, furniture |
| `C_FLOOR_KWH_PER_K` | 3.75 kWh/K | screed node, time constant ~3.2 h |
| `R_FLOOR_ROOM_K_PER_KW` | 0.85 K/kW | floor to room |
| `FLOOR_HEAT_SHARE` | 0.77 | share of heat-pump output into the floor (rest: LT radiators) |
| `INTERNAL_GAINS_KW` | 0.68 kW | appliances, people, tank losses |
| `SOLAR_APERTURE_M2` | 6.8 m² | kW_th per kW/m² global horizontal irradiance (Open-Meteo forecast) |

Open-loop with measured heat input, test weeks: Madoka error 0.18 / 0.55 / 0.84 K at 1 / 6 / 24 h (previous constants: 1.58 / 1.44 / 1.14 K). A third (pipe-layer) node did not improve the fit. Solar gain is not identifiable from PV power (the Daikin regulates it away), but is from irradiance.

**Daikin (closed loop)**: mean heat output per slot
`Q = clip(1.57 * (28.66 - 0.192*T_out + 8.0*(setpoint - T_room) - T_floor), 0, 8.4)` kW_th, re-evaluated every 2.5 min. Below the minimum modulation the real unit cycles; per slot that averages out. Fitted in closed loop (no measured heat input): Madoka error 0.66 / 0.72 / 0.70 K at 6 / 12 / 24 h on the test weeks; 24 h heat within 5 %. Known limitation: above the setpoint the model gives too little heat (measured 2-3 kW at 0.5-1.5 K above setpoint, model 0-1.5 kW), just below it too much; per day the energy matches.

**COP**: measured heat / Inepro electricity per outdoor temperature, defrost included: 2.42 (-2 C), 2.64 (2 C), 3.56 (6 C), 4.52 (10 C), 5.48 (14 C), linearly interpolated, clamped 1.8-6.0. The Carnot COP is no longer used for planning.

## 3. Invariants
1. The policy predicts the Daikin; it never imposes a power schedule. Hard peak lockouts and DHW runs set the heat to zero; soft peak advice is SG2 normal for the Daikin.
2. Pre-heat is a room setpoint offset of +1 K (the lever `RoomThermostatBufferController` applies on `climate.hc_room_room_heating`). Per hard lockout the policy evaluates 0-4 h of pre-heat and keeps the cheapest option, including a comfort penalty below target - 0.5 K. "No pre-heat" is always a candidate and wins unless pre-heat saves at least 0.05 EUR.
3. The policy reads only `building.ua_base_w_per_k` and `building.c_wind_w_per_k_ms` from the parameter file. `building.floor_capacity_kwh_per_k`, `building.c_solar_pv_ratio` and `heat_pump.modulation_curve` belong to the previous model and are ignored.

## 4. Planner replay
100 plans over the winter (every 6 h, days with a constant setpoint, perfect weather), 24 h ahead from the measured state: electricity 26.2 kWh planned vs 26.4 kWh measured (previous policy 16.7 kWh), per-plan error 7.0 kWh (previous 11.6), Madoka error 0.81 / 0.82 / 0.91 K at 6 / 12 / 24 h (previous 0.94 / 1.04 / 1.24 K).
