---
type: Invariant
title: Battery Telemetry Provenance, Live State-of-Charge & Simulation Labeling
description: Strict distinction between live hardware telemetry and simulated battery schedules; single-pass Priority 3 planning.
tags: [architecture, invariant, battery, telemetry, simulation, layer3]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_battery_policy", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: battery-policy
    resource: layer3_scheduling/battery_policy.py
    title: Battery LP Optimization & Priority 3 Dispatch Policy
    author: agent:hermes
  - id: central-planner
    resource: layer3_scheduling/central_planner.py
    title: Canonical Multi-Domain Central Planner
    author: agent:hermes
---

# Battery Telemetry Provenance, Live State-of-Charge & Simulation Labeling

## 1. Problem Context
When physical battery hardware (e.g. Deye 10kW Hybrid Inverter) is not yet commissioned or its sensor is offline, software systems must never fabricate a synthetic State-of-Charge (SoC) and present it as live physical hardware telemetry. Furthermore, battery schedules must not be solved redundantly in multiple independent route handlers with divergent initial conditions.

## 2. Invariants

### Invariant 1: Single-Pass Priority 3 Central Planning
The battery is planned **exactly once** within `CentralPlanner` as Priority 3 in the power allocation hierarchy (Baseload $\to$ DHW $\to$ Space Heating $\to$ **Battery Storage** $\to$ Net Export):
* `CentralPlanner` writes the authoritative battery dispatch into `plan.battery_summary` and `plan.device_dispatches`.
* All API endpoints (`/api/schedule/chart-data`, `/api/model/battery-status`, `/api/forecast/series`) read exclusively from this single published plan.

### Invariant 2: Live SoC Telemetry Provenance
* Physical battery dispatch requires a valid, live SoC reading from hardware telemetry (`sensor.battery_soc`).
* If the hardware telemetry reading is missing (`None`), unknown, or unavailable:
  - `is_active = False`
  - `inactive_reason = "NO_LIVE_SOC_TELEMETRY"`
  - The live control loop executes zero battery charge/discharge service calls.

### Invariant 3: Explicit Simulation Labeling
When no physical battery is installed (or telemetry is absent), Open HEMS provides a simulated planning projection if `battery.plan_simulation` is enabled in configuration:
* The canonical plan flags `plan.battery_summary.is_simulation = True`.
* All user interface views and API contracts explicitly label simulated states (`is_simulation: true`, `"Simulatie"` visual badge).
* Simulated profiles are strictly segregated from realized electrical energy accounts in InfluxDB.
