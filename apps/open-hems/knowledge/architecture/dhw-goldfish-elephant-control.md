---
type: Invariant
title: DHW Goldfish / Elephant Control Architecture
description: Strict baseline retention (Elephant) and stateless per-tick evaluation (Goldfish) for heat pump and domestic hot water tank control.
tags: [architecture, control, dhw, heatpump, elephant, goldfish, invariant]
status: stable
generated: { by: "human:matthijs", at: "2026-09-29T00:00:00Z" }
verified:
  - { by: "process:pytest_goldfish_elephant_dhw", at: "2026-09-29T00:00:00Z" }
sources:
  - id: daikin-interlocks
    resource: integrations/daikin_altherma/interlocks.py
    title: Daikin Altherma Hydraulic Interlocks & Relay Mapping
    author: human:matthijs
  - id: openhems-daemon
    resource: daemon.py
    title: Open HEMS Dispatch Daemon & Watchdog Loops
    author: human:matthijs
---

# DHW Goldfish / Elephant Control Architecture

## 1. Architectural Principles

### 🐘 Elephant Invariants (Immutable Baseline State)
The control system enforces a strict, permanent default baseline for normal operation:
1. **Physical Relays:** `SG2 Normaal / Automatisch` (S10S = `off`, S11S = `off`).
2. **Boiler Setpoint:** Exactly **`50.0 °C`** comfort level.
3. **Boiler Mode:** Always **`heat` (AAN)**. Software is strictly forbidden from setting the boiler climate entity to `off`.
4. **Spitsblokkade:** Forced lockout during EPEX peak hours operates **solely via hardware relays** (`SG1 Geforceerd uit`: S10S = `off`, S11S = `on`). The climate thermostat remains on `heat` at 50 °C.
5. **Post-Run Restoration:** Whenever a planned boost run ends or reaches its target temperature, the system unconditionally restores this Elephant baseline.

### 🐠 Goldfish Execution (Stateless Dispatch per Tick)
Every 60-second dispatch cycle evaluates the operational state statelessly:
1. **Active Peak Lockout:** Engages SG1 relays.
2. **Active Boost Run (SG4):**
   - The DP Optimizer calculates the economically optimal peak buffering temperature (e.g., $55.8\text{ }^\circ\text{C}$ or $60.0\text{ }^\circ\text{C}$).
   - While the run is in progress and $T_{\text{tank}} < T_{\text{target}} - 0.2\text{ }^\circ\text{C}$, relays remain in SG4 (S10S = `on`, S11S = `on`) and CV master switch is turned `off` (hydraulic interlock).
3. **Normal / Idle State:**
   - As soon as $T_{\text{tank}} \ge T_{\text{target}} - 0.2\text{ }^\circ\text{C}$ or the scheduled slot expires, the in-flight state is cleared.
   - The system immediately and actively enforces the Elephant baseline (`50.0 °C`, `hvac_mode: heat`, SG2 relays).
   - Inactive/idle slots never inherit future boost temperatures.

## 2. Dynamic Optimal Temperature Definition
- The system **is and remains fully empowered** to determine dynamic optimal target temperatures ($T_{\text{target}} \in [50.0\text{ }^\circ\text{C}, 60.0\text{ }^\circ\text{C}]$) for planned and future runs based on negative/cheap spot tariffs, solar surplus, and standing heat loss.
- This optimal temperature is tracked in `sensor.openhems_dhw_target_temperature` and `CanonicalDispatchPlan.dhw_summary.target_temp_c`.
- However, between runs, the physical thermostat setpoint never lingers at elevated temperatures, preventing unintentional autonomous reheating.
