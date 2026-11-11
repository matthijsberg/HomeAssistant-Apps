# Open HEMS Knowledge Log

## 2026-10-13
- **Architecture (Space Heating Model)**: Added `space-heating-model`: fitted 2-node building network (Madoka as room), Daikin closed-loop heat output instead of an imposed power curve and thermostat state machine, measured COP per outdoor temperature, and per-lockout pre-heat chosen as the cheapest of 0-4 h setpoint offset including "no pre-heat". Planner replay over winter 2025-26: 26.2 vs 26.4 kWh/day electricity (previous policy 16.7).
- **Schema**: `building.floor_capacity_kwh_per_k`, `building.c_solar_pv_ratio` and `heat_pump.modulation_curve` are no longer read by `SpaceHeatingPolicy`.

## 2026-10-12
- **Architecture (Space Heating State Estimation)**:
  - Added `floor-state-estimation`: the manifold loop sensors read the screed only when the compressor has delivered no CV heat for 60 min (manifold pump always circulates); while heating the supply-water offset ($R_w \approx 0.18$ K/kW, 114 winter stops) is removed and smoothed; transitions are held with explicit quality flags and relax towards the Madoka temperature. The 3-way valve, not DHW demand, decides where heat goes; the compressor, not the (stale-prone) P1P2 heat output, decides whether CV heat flows. Validated on winter 2025-26 (InfluxDB `hassio`).
  - Room setpoint for floor pre-heat is read and written on `climate.hc_room_room_heating` (0.5 °C steps); the Madoka is the only room reference.
  - `SpaceHeatingPolicy` integrates the floor/room network with sub-steps of at most 10 % of the fastest time constant and no longer rounds its state, restoring 15-min / 1-h resolution parity.

## 2026-10-09
- **Architecture (Control Logic Overhaul & Layer 4 Supervision)**:
  - Added `dhw-goldfish-elephant-control` update: single-owner `DhwRunSupervisor`, telemetry-only run detection (valve + compressor power, never relay feedback), bounded in-flight run expiry (45–180 min), and immediate release at target temperature.
  - Added `peak-lockout-semantics`: distinguished macro-clustered peak pricing periods from strict contiguous hard lockout crests ($\le 150\text{ min}$); passed per-slot lockout truth to DP optimizer, baseline, and space heating.
  - Added `time-and-slot-alignment`: formalized universal UTC slot grid (DST-safe), timestamp-based slot matching, and monotonic cache ages (`time.monotonic()`).
  - Added `plan-concurrency`: serialized single-writer planning lock covering compute and publish in `api/context.py`, non-blocking HTTP plan readers, and deep-copy plan immutability in `PlanStore`.
  - Added `actuator-ownership`: persisted ownership for CV master switch (`cv_forced_off_by_hems`) and room thermostat setpoint in `/config/open_hems_dispatch_state.json`; user setpoint changes are adopted as new baselines rather than clobbered.
  - Added `battery-soc-provenance`: unified battery planning as Priority 3 in `CentralPlanner`; live SoC gating for physical dispatches; explicit labeling of simulated plans.
  - Added `heatpump-model-parameters-schema`: complete formal specification of all keys in `/config/heatpump_model_parameters.json` with units, owners (`FORECASTER_OWNED_KEYS` via locked `params_store`), consumers, and physical clamping bounds.
  - Hardened fail-safe dispatch: stale plans (>15 min) or missing covering slots fall back unconditionally to SG2, paired with external Home Assistant dead-man watchdog (`ha/automations/openhems_dispatch_deadman.yaml`).
- **Metrics**: Updated `passive-solar-gain` to formally decouple direct glazing aperture ($c_{\text{solar\_passive}}$ in $\text{m}^2$) from electrical PV-to-thermal substitution ratio ($c_{\text{solar\_pv\_ratio}}$ in $\text{kWh}_{\text{th}}/\text{kWh}_{\text{pv}}$).
- **Calibration**: Replaced degenerate 3D OLS with rank-checked multi-variable OLS regression on $[\Delta T, E_{\text{pv}}, 1]$, ensuring stable matrix conditioning, zero synthetic fallbacks, and parameter write-locking.

## 2026-10-05
- **Architecture**: Added `solar-microclimate-nowcasting` formalizing omnidirectional pyranometer (Ecowitt Wittboy) GHI ingestion, $C^1$ cosine-eased nowcasting assimilation, and multi-facade passive solar aperture decoupling.
- **Metrics**: Added `passive-solar-gain` defining radiative thermal power entering conditioned building spaces ($kW_{\text{th}}$) vs electrical PV generation.
- **Calibration**: *Note (corrected 2026-10-09):* An earlier attempt at 3D OLS regression was numerically degenerate and has been replaced with the rank-checked $[\Delta T, E_{\text{pv}}, 1]$ model.

## 2026-09-29
- **Initialization**: Established OKF v0.2 knowledge bundle for Open HEMS.
- **Metrics**: Added definitions for `net-costs`, `solar-allocation`, and `heatpump-cop`.
- **Architecture**: Documented `presentation-parity` and `resolution-alignment` invariants.
- **Computations**: Added `kpi-digest` Attested Computation contract.
