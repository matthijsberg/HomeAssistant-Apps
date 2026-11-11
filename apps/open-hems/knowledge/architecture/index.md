# Architectural Invariants & Contracts

This directory contains strict design rules and invariant contracts enforced across Open HEMS backend and frontend implementations.

- [Presentation Parity Invariant](./presentation-parity.md) — 1:1 synchronization between summary cards and detail popups
- [Resolution Alignment & Downsampling](./resolution-alignment.md) — Exact temporal parity between 15-minute and 1-hour timelines
- [Forecast Page Three-Tier Segmentation](./forecast-segmentation.md) — Finance, Energy, and Energy Storage visual grouping
- [DHW Goldfish / Elephant Control Architecture](./dhw-goldfish-elephant-control.md) — Strict baseline retention, stateless per-tick evaluation, and single-owner supervision
- [Solar Microclimate Nowcasting & Passive Glazing](./solar-microclimate-nowcasting.md) — GHI pyranometer assimilation and fenestration aperture decoupling
- [Dynamic Peak Lockout Semantics & Contiguous Crests](./peak-lockout-semantics.md) — Macro-clustering vs single contiguous hard lockout windows
- [Universal UTC Slot Grid & Monotonic Alignment](./time-and-slot-alignment.md) — Timezone-safe UTC slot timelines, timestamp matching, and monotonic cache ages
- [Plan Concurrency & PlanStore Immutability](./plan-concurrency.md) — Single-writer serialized planning lock and deep-copy plan publication
- [Actuator State Ownership & User Intent](./actuator-ownership.md) — Persisted ownership for CV master switch, room thermostat, and in-flight DHW runs
- [Battery Telemetry Provenance & Simulation Labeling](./battery-soc-provenance.md) — Priority 3 central planning, live SoC gating, and explicit simulation labeling
- [Heat Pump Model Parameters Schema](./heatpump-model-parameters-schema.md) — Specification of keys, ownership, units, and physical clamping bounds
- [Space Heating Model](./space-heating-model.md) — Fitted building network, Daikin closed loop, measured COP and pre-heat decisions
- [Floor (Screed) State Estimation](./floor-state-estimation.md) — Settled manifold readings, supply-water correction, and provenance of the planner's initial floor temperature
