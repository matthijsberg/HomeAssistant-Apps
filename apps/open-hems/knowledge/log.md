# Open HEMS Knowledge Log

## 2026-10-05
- **Architecture**: Added `solar-microclimate-nowcasting` formalizing omnidirectional pyranometer (Ecowitt Wittboy) GHI ingestion, $C^1$ cosine-eased nowcasting assimilation, and multi-facade passive solar aperture decoupling.
- **Metrics**: Added `passive-solar-gain` defining radiative thermal power entering conditioned building spaces ($kW_{\text{th}}$) vs electrical PV generation.
- **Calibration**: Expanded 3D OLS regression parameter bounds for building fenestration aperture $[0.05, 2.50]$ with 5% daily EWMA governance.

## 2026-09-29
- **Initialization**: Established OKF v0.2 knowledge bundle for Open HEMS.
- **Metrics**: Added definitions for `net-costs`, `solar-allocation`, and `heatpump-cop`.
- **Architecture**: Documented `presentation-parity` and `resolution-alignment` invariants.
- **Computations**: Added `kpi-digest` Attested Computation contract.
