---
id: architecture/watchdog_supervision
title: "Autonomous Watchdog Supervision & Circuit Breaker"
type: "Architecture Invariant"
description: "Specification of multi-tier health detection, generation hang recovery, and rolling restart circuit breaking."
status: active
trust: authoritative
generated:
  by: "human:matthijs"
  at: "2026-11-01T00:00:00Z"
sources:
  - id: ha-supervisor-watchdog
    resource: "https://developers.home-assistant.io/docs/add-ons/configuration#watchdog"
    title: "Home Assistant Add-on Watchdog Documentation"
  - id: ollama-api-ps
    resource: "https://github.com/ollama/ollama/blob/main/docs/api.md#list-running-models"
    title: "Ollama Running Models API"
---

# Autonomous Watchdog Supervision & Circuit Breaker

## Context & Purpose
Ollama can experience silent inference hangs where the TCP port (11434) remains open and responds to shallow HTTP pings, but the Vulkan compute pipeline or GPU driver becomes deadlocked, causing subsequent inference requests to hang indefinitely. The standard Home Assistant supervisor watchdog (`tcp://[HOST]:11434`) cannot detect this failure mode.

## Architectural Invariants

### 1. Multi-Tier Health Probing
The add-on implements a two-tier supervision architecture:
1. **Tier 1 (Liveness):** Home Assistant Supervisor monitors TCP connectivity on port 11434.
2. **Tier 2 (Generation / Semantic Health):** A dedicated background watchdog loop runs inside the container:
   - Probes the internal `/api/ps` endpoint every 300 seconds.
   - If the active model is not loaded (e.g. `keep_alive` expired and unloaded cleanly), probing is skipped to prevent waking the model unnecessarily.
   - If the model is loaded, it executes a minimal non-streaming prompt test (`{"prompt": "hi", "options": {"num_predict": 1}}`) with a 60-second timeout.
   - Verifies the response contains a valid JSON `"response"` field.

### 2. Rolling Window Circuit Breaker
Uncontrolled restarts during persistent hardware or driver faults cause cascading CPU/disk thrashing.
- **Window:** 1800 seconds (30 minutes).
- **Threshold:** Maximum 3 restart triggers allowed within the rolling window.
- **Persistence:** State is tracked in `/tmp/ollama_watchdog_triggers`. This file persists across container process restarts but is cleanly cleared on full system boot or manual add-on stop.
- **Trip Condition:** If `RECENT_COUNT > 3`, the watchdog logs a `FATAL` error and halts automated restarts, leaving the container up for diagnostic review rather than thrashing.
