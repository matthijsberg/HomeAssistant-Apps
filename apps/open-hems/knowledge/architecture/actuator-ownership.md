---
type: Invariant
title: Actuator State Ownership & User Intent Preservation
description: Strict ownership tracking for the heat pump CV master switch, room thermostat setpoint, and domestic hot water in-flight states.
tags: [architecture, invariant, actuator, ownership, thermostat, layer4]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_room_thermostat_buffer", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: dispatch-state
    resource: layer4_control/dispatch_state.py
    title: Persisted Dispatch State & Actuator Ownership Store
    author: agent:hermes
  - id: room-thermostat-buffer
    resource: layer4_control/room_thermostat_buffer.py
    title: Room Thermostat Buffer & Setpoint Elevation Watchdog
    author: agent:hermes
---

# Actuator State Ownership & User Intent Preservation

## 1. Problem Context
Automated energy optimization software must never "fight" the human user for control over physical devices. Previously, two severe ownership issues existed:
1. **CV Master Switch Overwrite:** `switch.hc_mode_altherma_on` was unconditionally commanded ON every dispatch cycle. If the homeowner turned heating off (e.g. windows open or leaving home), Open HEMS immediately turned it back on.
2. **Thermostat Setpoint Clashing:** The thermal buffering watchdog previously tracked a hardcoded baseline ($20.0\text{ }^\circ\text{C}$). If the user dialed the thermostat to $19.0\text{ }^\circ\text{C}$ or $21.5\text{ }^\circ\text{C}$, the watchdog reverted the user's explicit change after the run.

## 2. Invariants

### Invariant 1: CV Master Switch Ownership
Open HEMS only touches `switch.hc_mode_altherma_on` to enforce the hydraulic interlock during high-temperature DHW runs (preventing 9 kW auxiliary electric immersion heater engagement):
* When Open HEMS switches the CV master switch OFF for a DHW run, it records `cv_forced_off_by_hems = True` in `/config/open_hems_dispatch_state.json`.
* When the DHW run ends, Open HEMS restores the CV master switch to ON **if and only if** `cv_forced_off_by_hems` is True.
* If the user manually switches heating OFF, `cv_forced_off_by_hems` is False, and Open HEMS leaves it OFF.

### Invariant 2: User Thermostat Baseline Adoption
The room thermostat buffer watchdog (`RoomThermostatBufferWatchdog`):
* Detects when the user manually changes the setpoint outside of an active buffering event and updates the baseline setpoint accordingly.
* When executing a solar pre-heat boost, it elevates the setpoint relative to the **user's current baseline** ($T_{\text{target}} = T_{\text{baseline}} + \Delta T$).
* When releasing, it restores the setpoint strictly back to the user's chosen baseline.
* Setpoint releases are never throttled or blocked by P1P2 write budget shortages.

### Invariant 3: Persisted Ownership State
Actuator ownership flags and in-flight session metadata must survive container restarts and daemon reload cycles:
* State is persisted atomically to `/config/open_hems_dispatch_state.json`.
* Missing state files initialize cleanly without assuming ownership of external actuators.
