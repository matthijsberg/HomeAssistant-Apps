---
type: Invariant
title: Plan Concurrency, Single-Writer Lock & PlanStore Immutability
description: Architectural invariants ensuring serialized, single-writer plan generation, immutable PlanStore publications, and zero Layer 3 side-effects.
tags: [architecture, invariant, concurrency, plan_store, layer3]
status: stable
generated: { by: "agent:hermes", at: "2026-10-09T00:00:00Z" }
verified:
  - { by: "process:pytest_plan_store", at: "2026-10-09T00:00:00Z" }
  - { by: "process:pytest_review_2026_10_09_regressions", at: "2026-10-09T00:00:00Z" }
sources:
  - id: api-context
    resource: api/context.py
    title: Central Context Manager & Serialized Planning Lock
    author: agent:hermes
  - id: plan-store
    resource: layer3_scheduling/plan_store.py
    title: Canonical Plan Store & Deep-Copy Immutability
    author: agent:hermes
---

# Plan Concurrency, Single-Writer Lock & PlanStore Immutability

## 1. Problem Context
Multiple asynchronous HTTP endpoints (`/healthz`, `/api/schedule/chart-data`, `/api/model/dhw-status`, manual recalculation POSTs) and the background dispatch loop previously invoked `ensure_active_canonical_plan()` concurrently. Because the lock did not protect execution, multiple heavy planning runs overlapped, causing racing in-flight state mutations, high CPU spikes on the HA host, and out-of-order plan publication (older telemetry snapshots overwriting newer ones).

## 2. Invariants

### Invariant 1: Single-Writer Planning Lock
All plan computation and publication within `api/context.py` is governed by a serialized re-entrant lock:
* The lock wraps the entire planning lifecycle: telemetry snapshot ingestion, optimizer solvers, and final publication to `PlanStore`.
* Readers requesting plans via HTTP GET never wait for an in-flight planning run if a published plan already exists; they consume the current `PlanStore` state instantaneously.
* Cache freshness is checked using monotonic time (`time.monotonic()`).

### Invariant 2: Published Plan Immutability (Deep Copy)
When `CentralPlanner` completes a plan, it is published to `PlanStore`. `PlanStore.set_plan()` and `PlanStore.get_plan()` enforce complete immutability:
* `set_plan()` stores a deep copy of the `CanonicalDispatchPlan`.
* `get_plan()` returns an immutable view / deep copy to consumers.
* Downstream evaluation modules, web formatters, or analytics routes are physically unable to mutate plan slots in-place.

### Invariant 3: Layer 3 Zero Hardware Side-Effects
Layer 3 (Planning & Scheduling) and `plan_decision_evaluator.py` are strictly computational and observable:
* Layer 3 never communicates with Home Assistant services, never toggles switches, and never modifies actuator setpoints.
* Physical side-effects are strictly confined to Layer 4 (`layer4_control/`) and integration adapters (`integrations/`).
