---
type: Invariant
title: Dynamic Peak Lockout Semantics & Contiguous Crest Windows
description: Distinction between macro-clustered peak pricing periods and strict contiguous hard lockout crests (<=150 min) in Open HEMS dispatch.
tags: [architecture, invariant, peak_detection, lockout, layer3]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_peak_detection", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: peak-detection
    resource: layer3_scheduling/peak_detection.py
    title: Dynamic Peak Detection & Anti-Cycling Clustering
    author: agent:hermes
  - id: central-planner
    resource: layer3_scheduling/central_planner.py
    title: Canonical Multi-Domain Central Planner
    author: agent:hermes
---

# Dynamic Peak Lockout Semantics & Contiguous Crest Windows

## 1. Problem Context & Macro-Clustering
EPEX spot price profiles during morning (07:00–09:00) and evening (17:00–21:00) hours frequently present "camel-back" or jagged peaks, where price briefly dips across one or two 15-minute slots before rising again. Blind thresholding causes destructive compressor cycling (short-cycling) and violates Daikin minimum dwell times.

To solve this, `detect_dynamic_price_peaks` applies two-tier clustering:
1. **Macro Peak Envelope (`PeakPeriod`):** Encompasses the entire high-tariff regime for user awareness, visual grouping, and pre-heat coasting advice.
2. **Hard Lockout Crest (`hard_start_idx` to `hard_end_idx`):** Identifies the highest contiguous price block within the macro peak, capped strictly at $\le 150\text{ minutes}$ (10 quarter-hours in winter, 120 minutes in shoulder months).

## 2. Invariants

### Invariant 1: Contiguous Hard Lockout Crest
Inside every recognized macro peak, there is **exactly one** contiguous hard lockout block defined by `hard_start_idx` and `hard_end_idx`. No gaps or re-engagement cycles are permitted within the same peak window.

### Invariant 2: Per-Slot Ground Truth (`slot_lockout_map` & `hard_lockout_slot_indices`)
The per-slot truth for dispatch is strictly represented by:
* `slot_lockout_map[slot_idx]`: Maps slot index to the controlling peak metadata.
* `hard_lockout_slot_indices`: Set of slot indices where compressor heating is hard-locked.

### Invariant 3: Universal Downstream Enforcement
All planning and control modules must strictly respect `hard_lockout_slot_indices`:
1. **DHW DP Optimizer:** Enforces $u_t = 0$ for all $t \in \text{hard\_lockouts}$.
2. **Baseline Feasibility:** The autonomous baseline solver respects the same lockouts.
3. **Space Heating Policy:** Coasting MPC must coast through the hard window without forcing heat pump runs.
4. **In-Flight Run Supervisor:** An active DHW run is **never** forced through a peak lockout; if an in-flight run encounters a hard lockout, it is released to SG1/SG2.
