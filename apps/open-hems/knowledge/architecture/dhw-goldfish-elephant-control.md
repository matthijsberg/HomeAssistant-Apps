---
type: Invariant
title: DHW Goldfish / Elephant Control Architecture
description: Strict baseline retention (Elephant) and stateless per-tick evaluation (Goldfish) with single-owner supervision for heat pump and domestic hot water tank control.
tags: [architecture, control, dhw, heatpump, elephant, goldfish, invariant, layer4]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_goldfish_elephant_dhw", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: dhw-run-supervisor
    resource: layer4_control/dhw_run_supervisor.py
    title: Layer 4 In-Flight DHW Run Supervisor & Lifetime Arbiter
    author: agent:hermes
  - id: dispatch-guard
    resource: layer4_control/dispatch_guard.py
    title: Fail-Safe Dispatch Guard & Timestamp Alignment
    author: agent:hermes
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

### 🐠 Goldfish Execution & Single-Owner Supervision (Layer 4)
Goldfish rule 3 is exclusively supervised by `layer4_control/dhw_run_supervisor.py`:
1. **Single Owner Principle:** Only `DhwRunSupervisor` is permitted to arm, track, or clear in-flight DHW runs in `PlanStore`. Arming logic has been strictly stripped from `api/context.py`, `CentralPlanner`, and `plan_decision_evaluator.py`.
2. **Telemetry-Only Run Detection:** In-flight runs are detected strictly from physical telemetry (`binary_sensor.hc_dhw_valve_dhw_tank == 'on'` combined with `sensor.warmtepomp_power > 600 W`), NEVER from relay actuation states (preventing positive feedback loops where commanded SG4 relatches itself).
3. **Target per Mode & Release at Target:** Under the Daikin-first policy (ADR-006, `dhw_engine = daikin_first`) the mode decides the target: `forced_on` = 50 °C, `max_on` = 60 °C; a running 50 °C run may be upgraded to 60 °C when the plan says `max_on`, but a run is never re-armed to another plan target. Under the legacy DP engine (ADR-004, until its removal) each slot carries the DP target. When $T_{\text{tank}} \ge T_{\text{target}} - 0.2\text{ }^\circ\text{C}$, the run is immediately cleared and relays return to SG2, even if the plan still shows future forced slots.
4. **Bounded Expiry & Fail-Safe:** Every in-flight run is stamped with a timeout bounded by $\max(45, \min(180, 2 \times \text{planned\_duration\_mins}))$. If the temperature sensor becomes unavailable or fails to reach target, the run times out and drops to SG2.
5. **CV Master Switch Ownership:** To prevent 9 kW auxiliary heaters from firing during DHW runs, Open HEMS turns `switch.hc_mode_altherma_on` OFF. The switch is restored to ON if and only if Open HEMS was the party that turned it off (tracked via `layer4_control/dispatch_state.py` persisted flag `cv_forced_off_by_hems`). Manual user shutdowns are respected.
6. **Stale-Plan Fail-Safe & HA Dead-Man:** If the published plan is older than 15 minutes, or lacks a slot covering the current timestamp, `layer4_control/dispatch_guard.py` unconditionally forces SG2 safe-mode. External dead-man automation (`ha/automations/openhems_dispatch_deadman.yaml`) alerts and resets relays if dispatch heartbeats stop for >10 minutes.
7. **SG4 Effectiveness Check (ADR-006):** If no DHW heating is measured (3-way valve on DHW and compressor power > 600 W; unmeasured counts as not heating) within `sg4_no_effect_timeout_min` (10 min) after arming, the supervisor releases SG4 to SG2 (the actuator restores the CV master under the ownership rule) and does not re-arm for `sg4_no_effect_cooldown_min` (60 min). SG4 with the CV master off is never held blind.
