---
type: Invariant
title: DHW Dynamic Peak Bridging & Target Selection
description: Strict rules for calculating dynamic target temperatures during pre-heat runs to bridge thermal drops over hard peak lockouts without crashing below comfort limits.
tags: [architecture, control, dhw, heatpump, preheat, invariant, layer3]
status: stable
generated: { by: "agent:hermes", at: "2026-11-11T20:00:00Z" }
verified:
  - { by: "process:pytest", at: "2026-11-11T20:00:00Z" }
sources:
  - id: dhw-policy
    resource: layer3_scheduling/dhw_policy.py
    title: Daikin-First DHW Policy Engine (ADR-006)
    author: agent:hermes
---

# DHW Dynamic Peak Bridging & Target Selection

## 1. Architectural Principles

### 📉 The Problem (Shower Drop vs Peak Lockout)
During morning routines, heavy DHW demand (e.g. 3.5 kWh_th for showers) translates directly to a large tank temperature drop (e.g. 8.5 °C). If this drop occurs entirely within a forced `HARD_LOCKOUT` (SG1, EPEX peak) where the heat pump is prohibited from running, pre-heating the tank to the default baseline (48.0 °C) is insufficient. The tank will drop to ~39.5 °C, breaching the physical comfort boundary (40.0 °C).

### 🎯 Dynamic Target Bridging Rule
The `DhwPolicy` (Layer 3) must never blindly plan a pre-heat to the static baseline if a known thermal trough lies ahead. Instead, it must dynamically elevate the target temperature for the pre-heat run using the exact predicted thermal drop.

1. **Peak Dip Detection:** The policy scans the autonomous (unheated) trajectory. If the tank drops below $T_{\text{comfort}}$ (default 40 °C) inside a hard lockout, it isolates the contiguous lockout window.
2. **Thermal Drop Calculation:** The exact drop is calculated strictly as the temperature at the start of the lockout minus the lowest temperature reached inside the lockout: 
   $$ \Delta T_{\text{drop}} = T_{\text{start}} - T_{\text{min\_in\_peak}} $$
3. **Target Elevation:** The required target for the pre-heat is then elevated to guarantee the tank lands safely above the comfort boundary after the drop, adding a standard 0.5 °C buffer:
   $$ T_{\text{req}} = T_{\text{comfort}} + \Delta T_{\text{drop}} + 0.5 $$
4. **Clamping:** The elevated target is physically clamped between the normal baseline ($T_{50}$) and the absolute maximum boost limit ($T_{60}$).

### 🧱 Hard Comfort Recovery
If the tank is found to be already below $T_{\text{comfort}}$ (e.g. after a peak lockout ends, or due to unexpected high consumption), the policy enforces an immediate **Hard Comfort Recovery**:
- The system commands a pre-heat to the baseline $T_{50}$ in the very first available (non-lockout) slot.
- This recovery overrides minor economic savings (it will not wait for a slightly cheaper slot hours later) to immediately restore sanitary safety.

## 2. Invariants

* **Single Pre-Heat Run:** The bridging pre-heat must be scheduled as a single, contiguous run (`MODE_FORCED_ON`) ending just before the peak lockout, preventing fragmented 15-minute start/stops.
* **Cost Minimization:** While the *target* is dictated by physics, the *start time* of the run is still chosen to minimize total energy cost over the eligible window.
* **No Software Setpoints:** Layer 4 Actuation strictly enforces this higher target by holding the SG4 relay until the sensor reads $T_{\text{req}}$, NOT by mutating the Daikin's internal thermostat setpoint via the P1P2 API.
