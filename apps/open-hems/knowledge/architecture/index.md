# Architectural Invariants & Contracts

This directory contains strict design rules and invariant contracts enforced across Open HEMS backend and frontend implementations.

- [Presentation Parity Invariant](./presentation-parity.md) — 1:1 synchronization between summary cards and detail popups
- [Resolution Alignment & Downsampling](./resolution-alignment.md) — Exact temporal parity between 15-minute and 1-hour timelines
- [Forecast Page Three-Tier Segmentation](./forecast-segmentation.md) — Finance, Energy, and Energy Storage visual grouping
- [DHW Goldfish / Elephant Control Architecture](./dhw-goldfish-elephant-control.md) — Strict baseline retention and stateless per-tick evaluation for heat pump and DHW buffer
- [Solar Microclimate Nowcasting & Passive Glazing](./solar-microclimate-nowcasting.md) — GHI pyranometer assimilation and fenestration aperture decoupling
