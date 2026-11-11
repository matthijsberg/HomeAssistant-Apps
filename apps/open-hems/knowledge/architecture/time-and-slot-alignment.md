---
type: Invariant
title: Universal UTC Slot Grid & Monotonic Cache Alignment
description: Invariant rules for timezone-safe UTC slot grids, absolute timestamp keys, DST transitions, and monotonic cache TTLs.
tags: [architecture, invariant, time, dst, utc, monotonic]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_sanitizer", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: sanitizer
    resource: layer1_data_collection/sanitizer.py
    title: Telemetry Sanitizer & UTC Slot Grid Alignment
    author: agent:hermes
  - id: dispatch-guard
    resource: layer4_control/dispatch_guard.py
    title: Fail-Safe Dispatch Guard & Timestamp Matching
    author: agent:hermes
---

# Universal UTC Slot Grid & Monotonic Cache Alignment

## 1. Problem Context
Daylight Saving Time (DST) changes—specifically the autumn fall-back (03:00 to 02:00) and spring jump (02:00 to 03:00)—lead to duplicated or missing string keys if timelines rely on local wall-clock strings (`"%Y-%m-%d %H:%M"`). Furthermore, wall-clock NTP adjustments can cause `(datetime.now() - last_time)` checks to stall or trigger negative deltas.

## 2. Invariants

### Invariant 1: Universal UTC Slot Grid
All internal slot grids in `TelemetrySanitizer`, `CentralPlanner`, and `CanonicalDispatchPlan` are generated along an absolute UTC timeline:
* Each slot represents an exact 15-minute epoch: $[t_{\text{utc}}, t_{\text{utc}} + 900\text{ s})$.
* During the autumn DST change, exactly 196 (or 100) physical quarters exist; no slot is stretched to 75 minutes or skipped.

### Invariant 2: Slot Lookup by Exact Timestamp
Dispatch controllers in Layer 4 must **never** index slots by list position (`slots[0]`), nor assume `slots[0]` matches wall-clock "now":
* `layer4_control/dispatch_guard.py` matches the current timestamp against slot boundaries using epoch timestamps: `slot.dt_start <= now < slot.dt_end`.
* If no covering slot exists or the plan is stale (>15 minutes), the dispatcher immediately enters fail-safe SG2.

### Invariant 3: Monotonic Cache Age (`time.monotonic()`)
All internal cache invalidations, debounces, and TTL checks across daemon loops, planning locks, and feed pollers MUST use `time.monotonic()` instead of `time.time()` or `datetime.now()`. Wall-clock NTP jumps must never freeze planning or cause premature cache expirations.
