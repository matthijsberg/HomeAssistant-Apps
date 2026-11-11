You are taking over a finished code fix in Open HEMS (/addons/open-hems) and need to finish it: verify, document (OKF v0.2), release and deploy to Home Assistant. Follow AGENTS.md throughout.

## Context
- Review: docs/reviews/2026-10-09-control-logic-review.md. Read §2 (findings) and §6 (fix status + behaviour changes) first.
- The code fixes are applied in the working tree on top of Matthijs' own uncommitted work-in-progress.
  - Only the fixes: docs/reviews/2026-10-09-fixes.patch (45 files).
  - Pre-fix state of tracked files: git ref refs/review/pre-fix-2026-10-09.
  - Do NOT revert or rework the fixes without asking. If you think something is wrong, report it.
- Main changes:
  - Single-writer planning lock + monotonic cache (api/context.py).
  - Immutable published plans (PlanStore deep copy).
  - New Layer 4 modules:
    - layer4_control/dhw_run_supervisor.py: the only owner of the in-flight DHW run; DP target per slot, expiry, release at target.
    - layer4_control/dispatch_guard.py: slot lookup by timestamp, stale-plan fail-safe to SG2.
    - layer4_control/dispatch_state.py: persisted ownership for the CV master switch and the room thermostat.
  - plan_decision_evaluator is observe-only.
  - Peak lockouts are passed per slot to the DP, baseline and space heating.
  - UTC slot grid (DST-safe).
  - Battery planned once as Priority 3 in CentralPlanner (live SoC only; labelled simulation when not installed).
  - Calibration: rank-checked regression, locked parameter store (layer2_calibration/params_store.py).
  - Ownership-aware room thermostat and CV master.
  - MQTT client fixes.
  - TLS verified except for internal HA hosts.
  - Heartbeat sensor plus HA dead-man automation (ha/automations/openhems_dispatch_deadman.yaml).

## 1. Verify (on the HA host)
- `PYTHONPATH=. pytest tests/` must be fully green, including:
  - tests/unit/test_frontend_tooltips.py (needs node)
  - tests/unit/test_data_integrity_gate.py (needs the /homeassistant paths)
  - tests/unit/test_review_2026_10_09_regressions.py (23 new tests)
  - In Claude's environment it was 243 passed; those 2 host tests weren't run.
- Run all 5 pre-commit traps from AGENTS.md rule 11 (secrets, bandit, ruff, mypy, node syntax).
  - Note: .git/hooks/pre-commit currently only runs the secret scanner. Make it run all 5.
- Run the OKF validator against knowledge/.
  - tests/architecture/test_okf_conformance.py passes vacuously when the validator script is missing. Make it fail with a clear message instead, and add the scripts/validate.sh that AGENTS.md rule 9 references.

## 2. OKF knowledge bundle (knowledge/, OKF v0.2; must pass the validator)
- Update architecture/dhw-goldfish-elephant-control.md:
  - Goldfish rule 3 is now implemented by DhwRunSupervisor; list it, dispatch_guard.py and the regression tests in sources/verified.
  - Document: single owner, the in-flight expiry, release at target even when the plan still shows forced slots, run detection from telemetry only (valve + power, never relay state), CV master ownership, and the stale-plan fail-safe plus HA dead-man.
- Update metrics/passive-solar-gain.md:
  - `building.c_solar_passive` = glazing aperture × GHI (OKF definition).
  - `building.c_solar_pv_ratio` = kWh_th per kWh_pv, used by SpaceHeatingPolicy and calibrated by the learned forecaster.
- Add Invariant docs under architecture/:
  - peak-lockout-semantics: cluster vs ≤150 min crest; `hard_start_idx/hard_end_idx` and `slot_lockout_map` are the per-slot truth.
  - time-and-slot-alignment: UTC grid, absolute-time keys, DST, slot by timestamp, monotonic cache ages.
  - plan-concurrency: one planning run at a time; immutable plans; Layer 3 never writes HA.
  - actuator-ownership: CV master, room thermostat, in-flight run.
  - battery-soc-provenance: live SoC or inactive; simulation clearly labelled.
- Add a schema doc for /config/heatpump_model_parameters.json: every key with unit, owner (writer), consumers and bounds.
  - Forecaster-owned keys are listed in FORECASTER_OWNED_KEYS in layer2_calibration/learned_forecaster.py.
- Update the index.md files and add a 2026-10-09 entry to log.md.
  - Correct the 2026-10-05 entry: the "3D OLS" regression was degenerate and has been replaced.

## 3. Repo docs & API contract
- AGENTS.md:
  - Fix the heading ("5 Invariant Rules" lists 11).
  - Reference the real validate.sh.
  - Add a rule: HA writes only from Layer 4/integrations; plans are immutable; one owner per actuator state.
- ARCHITECTURE.md: add the new Layer 4 modules and the battery as Priority 3 in the canonical plan.
- docs/openapi.json (keep tests/architecture/test_api_mcp_lockstep.py green). Document the new response fields:
  - plan slots: `target_temp_c`, `price_quality`
  - plan: `battery_summary` (with `is_simulation`)
  - /api/model/battery-status `decision`: `is_active`, `is_simulation`, `inactive_reason`
  - battery what-if analytics: `initial_soc_source`
- requirements.txt: add the test dependencies the suite imports (`mcp`, `pytz`), or a requirements-dev.txt.

## 4. Frontend QA (AGENTS.md rules 6 and 8)
- In the headless browser, at BOTH 15m and 1h, take screenshots and check console errors for:
  - the schedule chart
  - the DHW page: MAX_ON is now really emitted, labels read "tot X°C"
  - the space-heating chart
  - the battery page: simulation label, inactive reason
- Check that peaks, lockout bands and DHW runs sit on the same clock hours at both resolutions.

## 5. Release & deploy
- Bump the version with scripts/version_manager.py and add a CHANGELOG entry that links the review.
- Commit on a branch. Ask Matthijs how to split his own WIP from these fixes; the patch shows the fix-only diff.
- Deploy to HA with the usual flow (scripts/deploy_update.sh).
- Install ha/automations/openhems_dispatch_deadman.yaml in HA and reload automations.

## 6. Post-deploy checks (read-only first)
- Add-on logs:
  - planning about every 60 s
  - expect one warning `building.c_wind_w_per_k_ms=0.208 outside [1, 60]`
  - no tracebacks
- `sensor.openhems_dispatch_heartbeat` updates about every 60 s; its attributes include `cv_forced_off_by_hems`.
- `/config/open_hems_dispatch_state.json` exists.
- During the next DHW run:
  - log line `DHW run armed` with the DP target
  - `cleared` at target − 0.2 °C
  - the CV master switch is restored only if Open HEMS switched it off
  - no repeated writes every minute (the P1P2 write budget should stop draining)
- A manual thermostat change is NOT reverted.
- Testing the dead-man (stop the add-on for more than 10 minutes) needs Matthijs' explicit OK and a safe time window.
- Schedule a check for 2026-10-25 02:00–03:00 (DST fall-back): the plan keeps updating every minute and no slot is 75 minutes long.

## 7. Open decisions — ask Matthijs, do not decide yourself
1. Tariff model: 2026 still has the salderingsregeling (net metering), but self-consumed solar is valued at spot price minus a fee. Should export be valued closer to the all-in price?
2. Run consolidation costs about €0.04/day versus the raw DP on the golden day. Keep it, or raise `dhw_optimizer.c_start` instead?
3. A realistic `building.c_wind_w_per_k_ms`: the current 0.208 is rejected and the default of 15 W/(K·m/s) is used. There is no wind series in the calibration query.
4. B7: the tap-demand profile ignores draws while the compressor runs. Switch to a full energy balance?
5. D3: should forecast-price slots be discounted in the terminal valuations (DHW salvage price, battery λ)?
6. Deferred items:
   - wire the Layer 4 SafetyGuard dwell timer
   - the 49.2 °C display default in /api/model/dhw-status
   - InfluxDB password in query strings
   - the fabricated history prices in the battery-status chart
