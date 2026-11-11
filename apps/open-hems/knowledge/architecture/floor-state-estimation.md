---
type: Invariant
title: Floor (Screed) State Estimation from Manifold Loop Sensors
description: How the planner's initial floor temperature is derived from the underfloor-heating manifold sensors, with settled readings, supply-water correction and explicit provenance.
tags: [architecture, invariant, space_heating, floor, state_estimation, layer2]
status: draft
generated: { by: "agent:claude", at: "2026-10-12T00:00:00Z" }
verified:
  - { by: "process:pytest_floor_state_estimator", at: "2026-10-12T00:00:00Z" }
  - { by: "process:replay_influx_hassio_winter_2025_26", at: "2026-10-12T00:00:00Z" }
  - { by: "process:replay_ha_recorder_2026_09_28_to_10_12", at: "2026-10-12T00:00:00Z" }
sources:
  - id: floor-state-estimator
    resource: layer2_calibration/floor_state_estimator.py
    title: Floor (Screed) State Estimator
    author: agent:claude
  - id: daikin-reader
    resource: integrations/daikin_altherma/reader.py
    title: read_floor_circuit and room climate I/O (manifold, compressor, 3-way valve, heat output, Madoka)
    author: agent:claude
  - id: space-heating-policy
    resource: layer3_scheduling/space_heating_policy.py
    title: Space Heating Policy (floor/room network)
    author: agent:hermes
---

# Floor (Screed) State Estimation from Manifold Loop Sensors

## 1. Problem
`SpaceHeatingPolicy` starts every simulation from a floor (screed) temperature. The only floor-related sensors are the seven UniPi loop sensors on the underfloor-heating manifold. Until 2026-10-12 the planner used their mean directly while the heat pump was heating (that is supply-water temperature, not the screed) and `max(reading, room - 0.2)` otherwise. The same house and weather therefore produced different plans depending on whether the heat pump happened to run at planning time.

## 2. Measured behaviour
Sources: InfluxDB `hassio`, 1-minute means, 2025-11-01..2026-03-31 (representative heating season), and the HA recorder 2026-09-28..2026-10-12 (little heating, kept as a secondary check).
- The manifold has its own circulation pump that always runs. Without heat-pump supply all loop sensors agree within ~0.1 K: the circulating water reads the screed.
- After CV heat stops the supply water fades out in ~30-40 min (114 winter stops: 2-3.5 K/h in the first 20 min, ~1 K/h at 20-40 min). After that the reading is floor-dominated and cools 0.45-0.6 K/h right after a winter run.
- While the heat pump delivers CV heat the loops read roughly $R_w \cdot Q_{th}$ above the screed: $R_w$ median 0.18 K/kW (p25-p75 0.16-0.22) over the 114 winter stops.
- The 3-way valve sensor, not DHW demand, decides where the heat goes: demand stayed 'on' in 9 % of CV-heating minutes, the valve in 1 %. While idle the valve rests on the tank.
- The P1P2 heat output is not reset when the compressor stops: in winter 2025-26 it kept a stale non-zero value in 89 % of idle minutes (up to 23 h at -3.7 kW). Compressor state, not heat output, decides whether CV heat flows.
- The room reference is the Madoka (the heat pump controls on it); the SCO2 living-room sensor reads ~1.4 K lower.

## 3. Invariants

### Invariant 1: A manifold reading is a floor measurement only when settled
The mean loop reading counts as the screed temperature (`Quality.GOOD`) only when the compressor has not delivered CV heat for at least `settle_minutes` (60 min), measured from the latest HA `last_changed` of the compressor or the 3-way valve. During a DHW run the valve feeds the tank, so the loops settle as well.

### Invariant 2: Supply water is corrected, never used raw
While the compressor delivers CV heat the estimate moves (time-constant 15 min) towards `reading - R_w * Q_th` (`Quality.ESTIMATED`). The screed does not cool while heat flows in and is never warmer than the water passing through it.

### Invariant 3: Transitions are bridged, not invented
In the settle window, during DHW runs or with unknown state the previous estimate is held (`Quality.INTERPOLATED`), relaxing towards the Madoka temperature (time-constant 6 h) while no CV heat flows and capped at the reading, for at most 180 min after the last settled/corrected anchor. After that the estimate tracks the best available reading slowly (`Quality.STALE`). Without any valid reading nothing is produced once the hold has expired.

### Invariant 4: Entity isolation and provenance
Entity ids live only in `integrations/daikin_altherma/reader.py` (`read_floor_circuit`, `read_room_climate`); the estimator in Layer 2 is pure. `api/context.py` keeps the previous estimate under the planning lock and records `source`, `quality` and the raw reading in `frame.metadata["floor_state"]`.

## 4. Validation
Every estimate in the hour before a transition into a settled reading is compared with that reading, extrapolated back along the settled cooling rate.
- Winter 2025-26 (271 transitions): bias +0.10 K, mean absolute error 0.15 K, p90 0.26 K. The previous logic on the same events: +0.28 K, 0.28 K, 0.46 K.
- 2026-09-28..10-12 (38 transitions, earlier parameter set): bias -0.02 K, mean absolute error 0.10 K. The previous logic: +0.58 K, 0.58 K.

## 5. Open items
- Since 0.108.0 `SpaceHeatingPolicy` uses the fitted network (see `space-heating-model`). The original note: a grey-box fit of the 2-node network on the same winter (Madoka as room, measured CV heat as input, alternating weeks for training and testing) gives C_floor ~3.9 kWh/K, C_room ~12.5 kWh/K, R_floor_room ~0.83 K/kW (floor time constant ~3.2 h), 77 % of the heat into the floor, UA ~0.31 kW/K and ~0.9 kW internal gains. With those parameters the 6-hour-ahead room error on the test weeks is 0.55 K, against 1.44 K with the current constants (`R_FLOOR_AIR_K_PER_KW = 0.08`, `C_AIR_KWH_PER_K = 3.2`, floor 13.2 kWh/K). A third (pipe-layer) node did not improve the fit.
