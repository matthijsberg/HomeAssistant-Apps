# Open HEMS — Control-Logic Review (2026-10-09)

**Scope:** DHW buffering (boiler), floor-heating buffer (space heating), home battery, self-correcting calibration, and the surrounding runtime (daemon, plan lifecycle, Home Assistant I/O), checked against `AGENTS.md` invariants and the OKF bundle in `knowledge/`.
**Baseline:** working tree at v0.105.0 (incl. 88 uncommitted files), Python 3.14.
**Method:** full read of the control path; test suite run in an isolated venv; six in-process experiments, consolidated in [`2026-10-09-repro.py`](2026-10-09-repro.py) (`PYTHONPATH=. python3 docs/reviews/2026-10-09-repro.py`).

Evidence labels: **Repro** = reproduced by the script · **Code** = verified by reading the exact lines · **Plausible** = mechanism is in the code, but the real-world trigger depends on hardware or timing I couldn't observe.

---

## 1. Executive summary

1. **The DHW DP optimizer's core is sound.** In 36 synthetic scenarios, no feasible alternative ever beat it (B4). The bugs are in the wiring around it: the inputs it gets (lockouts, sensor defaults), and above all the execution layer, where four components compete over the same DHW run.
2. **The race conditions come from three structural causes:**
   - The planning lock doesn't lock (A1).
   - The "in-flight run" commitment has 4 independent writers and 3 clearers. They use different targets and thresholds, and nothing ever expires a commitment (A2).
   - A second actuator path (`plan_decision_evaluator`) writes to Home Assistant directly and mutates the shared plan object in place (A3).
3. **Two time bombs:**
   - **DST fall-back on 2026-10-25 (16 days away):** the plan freezes for about 59 minutes (A4).
   - **Heating season (starting now):** the in-flight arming rule fires on space-heating power, which forces DHW runs and switches the CV master off (A2d). The room-thermostat watchdog resets any manual setpoint above 20.7 °C (C1).
4. **The self-correcting loop is mostly open:**
   - The 3-D building regression always returns its hard-coded fallback (E1).
   - The calibrator writes keys that no planner reads (E2).
   - The same parameter key means three different things in three places (E3).
5. **The battery is not part of the plan.** Three GET handlers each solve their own LP, starting from a made-up 50 % state of charge (D1, D2).

**Fix first (in order):** A1 + A3 (single-writer planning, immutable plans) → A2 (one Layer 4 run-state machine with a timeout) → B1 (pass lockouts to the DP) → A4/A5 (UTC slots, pick the slot by timestamp, stale-plan fail-safe, HA dead-man switch) **before 2026-10-25** → C1/C2 (thermostat baseline) **before cold weather**.

---

## 2. Findings

### A. Concurrency and the control loop

#### A1 — `ensure_active_canonical_plan` lock is a no-op · **High** · Code
- **Where:** `api/context.py:88-92`. The lock is released after the double-check, so the whole planning run (lines 94–397: network fetches, DP, publish) executes unlocked. `_LAST_CANONICAL_PLAN_TIME` is only set at line 398, after planning finishes.
- **Who triggers planning:** every caller older than 60 s.
  - the dispatch thread
  - every GET that needs the plan, including `/healthz` (`daemon.py:102`)
  - `force_refresh` POSTs (`routes_system.py:848,922,1014`, `routes_schedule.py:813`, `routes_calibration.py:272`)
  - a background thread (`routes_system.py:634`)
- **Effect:** these runs overlap. Each one publishes (last writer wins), and a run that started earlier with an older HA snapshot can publish *after* a newer one. Each run also executes the in-flight arming logic (A2), so arming races too. CPU load multiplies on the HA host (each run is a 192-slot DP plus a 2R1C simulation).
- **Fix:** make the collector/dispatch thread the only writer that plans. HTTP handlers only read `PlanStore`, and `force_refresh` sets an `Event` that the planning thread consumes. Use `time.monotonic()` for cache age (see A4).

#### A2 — In-flight DHW commitment: many writers, conflicting targets, no expiry · **Critical** · Code (+Plausible for the latch trigger)

| Site | Action | Target | Condition |
|---|---|---|---|
| `api/context.py:373-377` | arm | 60 if S10S∧S11S∧T≥48, else 50 | relays SG4 **or** P>600 W ∧ DHW valve **or P>1200 W ∧ T<58** |
| `central_planner.py:241-272` | arm | 60/50 from the previous plan's slot mode | previous plan had `dhw_kw>0` at "now" |
| `plan_decision_evaluator.py:117` | arm | 60 | merger CASE 0 / CASE A |
| `plan_decision_evaluator.py:220` | arm | 50 | Daikin heating DHW ∧ T<49.8 |
| `daemon.py:423` | clear | — | T ≥ target − 0.2 |
| `central_planner.py:278` | clear | — | T ≥ target − 0.3 |
| `plan_decision_evaluator.py:169` | clear | — | heating ∧ T ≥ 49.8 (absolute) |

None of these sites knows the DP's chosen target (e.g. 55.8 °C). Consequences:

- **a) Output fed back as input:** `context.py` arms a 60 °C target from S10S∧S11S, which is the SG4 state Open HEMS itself commanded. The planner then forces up to 6 extra `u=1` slots (`central_planner.py:283`, `dhw_optimizer.py:633-637`). In effect, DP runs heading for 52–58 °C end at 60 °C. That is exactly the "60 °C residue" the Goldfish rule forbids.
- **b) No timeout:** `daemon.py:415-421` overrides every `normal` slot to SG4 while T < target − 0.2. If the tank never reads that high, SG4 **and CV master OFF** persist indefinitely, and floor heating is blocked. Two ways that can happen:
  - The R5T sensor goes `unavailable`. `daemon.py:388-390` then substitutes 50.0 °C, so T < 59.8 forever.
  - The Daikin's SG4 storage limit is below the in-flight target.
  - The `forced_off` peak lockout is not overridden, so the latch resumes after each peak.
- **c) Space heating arms DHW:** `context.py:373` arms on `wp_pwr > 1200 and cur_dhw < 58` **without a valve check**. The evaluator's own comment says this must never be done (`plan_decision_evaluator.py:58-59`). The tank normally sits between 40 and 50 °C. So in cold weather, every replan while the floor heating draws more than 1.2 kW forces a 50 °C DHW run and switches CV off. Committed in `a007887` (v0.103.69, late September); it starts firing with the heating season.
- **d) Inconsistent hysteresis:** the clear thresholds are 0.2 vs 0.3 vs absolute 49.8. Modes are stored as `"StandardizedState.FORCED_ON"` strings, which only work because three separate normalisers strip the prefix.
- **Fix:** move this into **one Layer 4 run-state machine** (`integrations/daikin_altherma/`):
  - `run_id`, target taken from the plan slot, `started_at`, `max_duration` (e.g. 2× the planned duration, hard cap 3 h)
  - explicit end conditions: target reached, timeout, sensor stale, or a peak lockout
  - a "compressor is heating DHW" signal derived **only** from valve + power telemetry, never from relay state
  - the planner reads this state but never writes it.

#### A3 — Second actuator path and in-place mutation of the shared plan · **High** · Code (+Plausible for short-cycling)
- **Where:** `plan_decision_evaluator.py:91-221`, called on every dispatch tick (`daemon.py:402`).
- **Writes HA directly every tick** (`input_select`, `switch.hc_mode_altherma_on`):
  - This bypasses the idempotency guards in `make_daikin_ha_actuator` (`client.py:165-194`) and the interlocks.
  - Every DHW run produces a redundant CV switch write every minute. That burns the P1P2 write budget the daemon itself monitors (`daemon.py:481-496`).
- **Mutates `plan.slots[...]` on the object `PlanStore.get_plan()` returns:**
  - It's a shared reference, not a copy, so HTTP threads iterating the plan see half-updated slots.
  - It then calls `publish_plan(plan)`, which can overwrite a newer plan published by another thread in the meantime.
- **Branch 2 (`:149`) has a hard-coded 49.8 °C release:**
  - It releases to "Automatisch" and rewrites slot 0 to NORMAL for every run targeting 50–58 °C. CASE 0 only recognises targets ≥ 58 °C as boost runs.
  - The next replan starts from `run_state0=OFF_FREE`, so the DP doesn't know the compressor just stopped and can re-plan the run straight away.
  - Plausible result: SG4↔SG2 short-cycling, plus CV master toggling.
- **Other branches:**
  - **Branch 1 (`:91-118`)** forces SG4 even when the merger returns `promoted_mode="normal"` (target reached).
  - **Branch 3 (`:198`)** ignores the hard lockout.
- **Fix:**
  - The evaluator should only *observe*. It emits an "autonomous DHW run detected" fact into the next planning input and never actuates.
  - Make plans immutable: frozen dataclasses, or `deepcopy` in `publish_plan`/`get_plan`.

#### A4 — DST fall-back freezes planning for ~59 min on 2026-10-25 · **High** · Repro
- **Plan cache:** `context.py:84-91` subtracts two Europe/Amsterdam datetimes that share the same `ZoneInfo` object. Python ignores `fold` in intra-zone arithmetic, so at 02:00:30 CET minus 02:59:30 CEST the age is −3540 s. That is "< 60", so the cached plan is returned until about 03:00 CET.
- **Stale execution:** meanwhile `daemon.py:406` keeps executing that plan's `slots[0]`, i.e. the 02:45–03:00 CEST slot, which is a typical cheap DHW slot.
- **Slot grid:** `sanitizer.py:217` builds the grid by wall-clock `timedelta` addition, so one slot spans 75 real minutes.
- **Price keys:** the `"%Y-%m-%d %H:%M"` keys (`sanitizer.py:152`) collide for the repeated hour.
- **Fix:**
  - `time.monotonic()` for cache age.
  - Build slots in UTC and convert to local time only for labels and tap-profile lookup.
  - Key price/solar/weather maps by UTC epoch.

#### A5 — No freshness or slot-time check before actuation; no fail-safe · **High** · Code
- **No checks:** `daemon.py:406` takes `plan.slots[0]` without checking that it covers *now*, and never checks `plan.is_fresh`.
- **No fallback:** any exception in `execute_live_dispatch` is swallowed (`:688-690`) and relays stay where they were (e.g. SG4 + CV off). `ARCHITECTURE.md` §2.4 promises a "fail-safe fallback to normal mode upon connection loss".
- **Dead safety code:** `layer4_control/controller.py:14-55` (`SafetyGuard`: dwell time, emergency comfort) is never called by the live path. Nothing at Layer 4 prevents short-cycling.
- **Fix:**
  - Pick the slot by timestamp.
  - If the plan is older than about 5 min or slot 0 doesn't cover now, fall back to SG2 + CV on.
  - Wire `SafetyGuard` dwell time into the actuator.
  - Add an **HA-side dead-man automation:** heartbeat sensor stale for more than 10 min → "Automatisch" + CV on. If the add-on dies, nothing in-process can release the relays.

#### A6 — One tick decides on 4–6 different HA snapshots · **Medium** · Code
- `get_ha_states_map()` downloads all states each time it's called: `daemon.py:385,607`, `plan_decision_evaluator.py:46`, `client.py:163`, `context.py:163,346`, each with a timeout of up to 5 s.
- **Fix:** take one snapshot per tick and pass it down.

#### A7 — Lost updates on `heatpump_model_parameters.json` · **High** · Code
- **Forecaster:** `HybridForecastingModel` loads params at import (`context.py:20`). Its `_ensure_defaults` rewrites the file on every instantiation (`learned_forecaster.py:128`; `routes_analytics.py:1137` instantiates it per request). `retrain_from_openhems` saves its stale in-memory copy (`:572`).
- **Calibrator:** does the same with its `__init__` snapshot (`calibrator.py:33, 396-399`).
- **Effect:** the API "accept" actions (`routes_calibration.py:194,267`) and `scripts/calibrate_dhw.py` are silently reverted. Writes are atomic (`os.replace`), so files are never torn, but updates are lost.
- **Fix:** one writer with a file lock that does reload → merge owned keys → write. Or split into per-owner files (`building.json`, `dhw.json`, …).

#### A8 — Hand-rolled MQTT client · **Medium** · Code
- **Problems** (`daemon.py:240-309`):
  - It never sends PINGREQ, so the broker drops the connection after about 90 s; the reconnect loop never closes the socket.
  - Remaining length is read as one byte (`:290`), so payloads of 128 bytes or more (P1P2 JSON) desynchronise the stream.
  - The resync skips one byte at a time and treats ASCII digits (0x30–0x39) as PUBLISH headers.
  - Cache values never expire, and the cache is preferred over HA (`:752-754, 773-775, 829-837`). If `mbmd` stops, the last solar/heat-pump power is used forever.
- **Fix:** use paho-mqtt. Store a timestamp per topic and mark values `Quality.STALE` after a TTL.

### B. DHW buffering (boiler)

#### B1 — The DP never sees peak lockouts · **High** · Repro
- **The mismatch:** `dhw_optimizer.py:288-297` expects `{"slot_idx", "is_hard_lockout"}` per slot. `detect_dynamic_price_peaks` returns *block* objects (`start_idx/end_idx/hard_start_time…`, `peak_detection.py:181-197`), and frame slots have no `is_hard_lockout`. The lockout set is always empty.
- **Why tests pass:** the explain module uses the correct per-slot format (`dhw_optimizer_explain.py:350-351`).
- **The workaround breaks the plan:** `CentralPlanner` strips lockout slots after the solve (`central_planner.py:365-370`). This breaks the DP trajectory and min-run constraint, and leaves `dhw_summary` describing runs that won't happen.
- **Repro:** starting at 17:00 with the tank at 41.5 °C, the DP plans 18:45–19:15 *inside* the 17:00–19:30 lockout. After stripping, the next dispatched run is 04:15. A start at 18:00 leaves a one-slot run at 20:00, below L_min.
- The baseline simulator has the same blind spot (`dhw_baseline.py:108`).
- **Fix:** pass `[{"slot_idx": k, "is_hard_lockout": True} for k in hard_slots]` built from `slot_lockout_map`, delete the post-strip, and add a planner-level test.

#### B2 — The target temperature is never enforced, and MAX_ON is never produced · **High** · Code
- **Relay-only control:** SG4 heats to the Daikin's own limit. The DP target (`dhw_plan_adapter.py:81`) is only approximated by how long the slots last.
- **Doc contradiction:** on reaching the target, `daemon.py:415-424` clears the in-flight run but does **not** revert a planned `forced_on` to `normal`. This contradicts `knowledge/architecture/dhw-goldfish-elephant-control.md` §1, Goldfish 3 ("immediately … enforces the Elephant baseline").
- **MAX_ON never emitted:** `central_planner.py:431` maps MAX_ON only when `planned_mode == "forced_solar_boost_60"`. The adapter only produces `max_on` / `forced_on` / `normal`, so every DHW slot is FORCED_ON. `daemon.py:551` patches this using the summary.
- **No per-slot target:** `DispatchPlanSlot` has no `target_temp_c`, so `daemon.py:541` and merger CASE 0 always fall back.
- **Fix:** put `target_temp_c` on the slot (or `DeviceSlotDispatch.payload`), and implement a single "T ≥ target − h ⇒ SG2" rule in the A2 state machine.

#### B3 — The baseline guard adopts comfort-violating plans · **Medium** · Repro
- **The guard:** `central_planner.py:316-326` compares J only.
  - In 4 of 48 scenarios the baseline was adopted, and **3 of those dip to 39.7 °C**.
  - Adoption turns the *predicted autonomous* runs into *forced* SG4 slots, which contradicts its own comment.
  - It leaves `res_opt.runs`/`slot_modes` untouched, so the summary and the dispatch disagree.
- **Fix:** require the baseline to be feasible (`min T ≥ t_comf + m_k`). If it's adopted, emit NORMAL slots instead of forcing.

#### B4 — "Solver suboptimal" is a false alarm · **Low** · Repro
- **Where:** `dhw_optimizer_explain.py:294,366-370`.
- **Why:** the warning compares the DP against counterfactual solves that fell into the infeasible emergency fallback. Of 36 scenarios, a comfort-violating fallback "beat" the DP in 20, and a feasible alternative in **0**.
- **Fix:** skip the comparison when `validation_issue` is set.

#### B5 — Run consolidation adds unplanned heating · **Medium** · Code
- **Where:** `central_planner.py:363`.
- **Effect:** gaps of up to 6 slots (1.5 h) are filled without re-simulating. That means extra heating beyond the DP target, possibly in soft-peak slots, and the trajectory, costs and summary aren't updated.
- **Fix:** model the start cost and dwell in the DP (already there) and drop this step, or re-simulate after consolidating.

#### B6 — Made-up tank temperatures, and "fresh" without a reading · **High** · Code
- **Defaults instead of missing data:** `daemon.py:388` uses 50.0 and `context.py:158` uses 48.0 when the sensor is missing.
- **Missing counts as fresh:** `sanitizer.py:122-124` treats "no hardware reading" as fresh (age 0).
- **One bad sensor blinds the rest:** a single `unavailable` value raises at `context.py:166` and skips the room, floor and setpoint reads in the same `try` block.
- **Quality flags are write-only:** no planner or dispatch code reads `slot.quality`.
- **Fix:** use `None` plus `Quality.STALE`. While the tank reading is stale, hold the Elephant baseline and plan nothing, and set `is_fresh=False` when there's no reading. Parse each sensor in its own guard.

#### B7 — The learned tap profile underestimates draws while heating · **Medium** · Code
- **Where:** `dhw_thermal_model.py:181-194` sets tap demand to 0 while the compressor runs, unless T drops more than 1.5 °C.
- **Effect:** the Daikin reheats right after showers, so those slots systematically lose demand, and the comfort margins are too thin exactly there.
- **Fix:** always use the energy balance `q_tap = q_in − C·ΔT − q_standby`, clipped at 0.

#### B8 — The baseline simulates with the wrong UA · **Low** · Code
- **Where:** `physics.py:219-236`. When `spec` is a `DhwTankSpec`, UA stays at the 2.5 default; the `params` branch is skipped. The baseline's start/stop pattern is generated under different physics than it is scored with.

### C. Floor-heating buffer

#### C1 — The room-thermostat watchdog overrides the user · **High** · Repro
- **Where:** `room_thermostat_buffer.py:115-130` with `daemon.py:57,469`.
- **Override:** the baseline defaults to 20.5 °C and is only learned in `request_preheat`. When not buffering, any setpoint above 20.7 °C is reset to 20.5 within a minute.
- **Restart ratchet:** after a restart mid-preheat, the baseline is captured as the elevated value. The next preheat goes to 22.5 °C, and release "restores" the elevated value.
- **Fix:**
  - Persist the baseline.
  - Remember the setpoint Open HEMS last wrote, and revert only if the current setpoint still equals it.
  - Never touch a setpoint someone else changed.

#### C2 — Release can be blocked for most of a day · **Medium-High** · Repro
- **Cause:** `request_release` obeys the 6-per-24 h budget (`:106-108`), and watchdog writes consume the same budget.
- **Repro:** two cycles plus one watchdog revert, then a preheat to 21.5 °C. Release stays refused at +1/+6/+12 h, until the oldest change ages out of the 24 h window.
- **Fix:** rate-limit only elevations; restoring the baseline must always be allowed.

#### C3 — Space heating treats the whole peak cluster as a hard lockout · **Medium** · Code
- **Where:** `space_heating_policy.py:232-237, 172-200` use the cluster range and the cluster-level `is_hard_lockout`. Dispatch only locks the ≤150 min crest (`peak_detection.py:200-205`).
- **Effect:** the plan simulates 4–5 h without heating, so it over-preheats, and its trajectory and `lockout_hours` disagree with what is dispatched.
- **Fix:** use the per-slot `slot_lockout_map` (same source as B1).

#### C4 — The winter golden replay fails · **Medium** · Repro (test suite)
- **Failure:** `test_replay_winter_sunny_peak` gives a minimum projected room temperature of 19.16 °C against a comfort floor of 19.4 °C.
- **Harness bug:** `tests/unit/test_replay_harness.py:37` hard-codes `+02:00` for every fixture. In January that runs winter replays an hour off against the `+01:00` fixtures.

#### C5 — The "night valley 02:00–05:30" window is relative to now · **Low-Medium** · Code
- **Where:** `space_heating_policy.py:266-271` uses `idx % 96` with `8 ≤ … ≤ 22` on slot indices that start at now, so it actually means "2–5.5 h from now".

#### C6 — The params file is re-parsed hundreds of times per plan · **Low** · Code
- **Where:** `get_active_parameters()` (`space_heating_policy.py:60-100`) is called per slot, per modulation step and per MPC step, every minute.
- **Fix:** load once per plan and pass the values in.

### D. Battery (early code)

#### D1 — The battery is not part of the canonical plan · **High** · Code
- **Where:** `BatteryPolicy.optimize` runs inside three GET handlers (`routes_schedule.py:472`, `routes_forecast.py:539`, `routes_analytics.py:1757`) with different inputs.
- **Effect:**
  - Three different battery plans appear across pages, which violates Invariant 1.
  - Nothing reaches `PlanStore`, the audit log or an actuator.
  - `net_import_kw` ignores the battery.
- **Fix:** run it as Priority 3 in `CentralPlanner` on the plan's residual and emit `DeviceSlotDispatch`; the views only read the result.

#### D2 — Made-up state of charge · **High** · Code
- **The documented rule:** `battery_policy.py:177-191` says the policy must never invent a SoC.
- **What the callers do:**
  - `routes_schedule.py:477` hard-codes 50.0.
  - `routes_forecast.py:515,530` falls back to 50.0 on any error or "unavailable".
  - `routes_analytics.py:1735` starts at 50.0 and also queries a virtual test entity.
- **Fix:** pass `None` so the policy returns its inactive plan.

#### D3 — Firm and forecast prices are indistinguishable · **Medium** · Code
- **What happens:** beyond the day-ahead horizon, prices come from the Stroomvoorspeller forecast, or are forward-filled if both feeds fail (`sanitizer.py:229`). The forecast prices are labelled GOOD. The battery terminal value λ (`battery_policy.py:232-237`), the DHW salvage price and the peak percentiles all mix firm and forecast prices.
- **Fix:** carry `source`/`quality` into the slots, and discount or exclude forecast slots in the terminal valuations.

#### D4 — Tariff and LP details · **Low** · Code
- **Configured tariffs ignored:** `CentralPlanner` always uses a default `TariffProvider()` (`central_planner.py:117`) instead of the configured tariffs.
- **SoC clamped up:** an initial SoC below the minimum is clamped up (`battery_policy.py:219`), so the LP thinks there is energy that isn't there.
- **Verify against your contract:** 2026 still has the salderingsregeling (net metering ends 1 Jan 2027). Valuing self-consumed solar at spot minus fee (`tariff_provider.py:56-64`) undervalues it by roughly energy tax plus VAT if you are a net importer over the year. That biases both DHW and battery planning towards solar hours.

### E. Self-correcting logic (calibration)

#### E1 — The 3-D building regression is degenerate · **High** · Repro
- **Where:** `learned_forecaster.py:399` builds `x = [dt, dt*0.1, pv/10]`. Column 2 is exactly 0.1 × column 1, so the normal matrix is singular.
- **Effect:** `solve_ols_3x3` returns its hard-coded fallback `[7.02137, 0.03634, 0.08885]`, i.e. "calibrated UA = 292.6 W/K", whatever the data. The repro feeds it a true UA of 208 W/K and of 375 W/K and gets 292.6 W/K both times. Because 292.6 falls inside the 180–450 acceptance band, it is accepted.
- **Doc impact:** `knowledge/log.md` (2026-10-05) documents this regression as a capability.
- **Fix:** use wind (or ΔT·wind) as the second regressor, solve with `numpy.linalg.lstsq` plus a rank check, and treat a fallback as "no update", not as a result.

#### E2 — Calibrator output is an open loop · **High** · Code
- **Key mismatch:** `calibrator.py:384-394` writes top-level `ua_base`, `c_wind`, `c_solar`, `dhw_standby_loss_kwh`. The planners read `building.ua_base_w_per_k` (`space_heating_policy.py:72`) and `dhw_tank.standby_loss_w_per_k` (`dhw_thermal_model.py:57`). Nothing reads `dhw_standby_loss_kwh`, and `ua_base` is only read once, as a legacy migration.
- **Fixed values presented as calibration:** it writes constant `dhw_average_cop: 2.02` and `heating_average_cop: 4.8`.
- **Unit errors:**
  - Beaufort × 3.6 is treated as km/h (`:316`).
  - `c_solar` is clamped positive (`:234`), so sunshine *increases* modelled heat demand.

#### E3 — The same key has three meanings · **Medium** · Code
- **`c_solar_passive` is used three ways:**
  - × PV kW in `SpaceHeatingPolicy` (default 1.15)
  - × GHI × 25 m² in `learned_forecaster.py:241` (default 0.12)
  - the OKF metric `passive-solar-gain` defines `Q = A_eff·GHI/1000` with A_eff in m².
- **`c_wind_w_per_k_ms` spans two orders of magnitude:** 15 (code default), 1.5 (migration), 0.05–0.35 (calibration clamp), 0.208 (`data/` file). The wind term depends on whichever path wrote last.
- **Fix:** a typed parameter schema with units in `knowledge/`, validated on load (see F4).

### F. Guardrails, docs and OKF conformance

- **F1 · Medium — The entity-isolation guard is too narrow.**
  - `tests/architecture/test_anti_drift_guards.py:22-34` scans 5 hand-picked files for 4 literal strings.
  - `layer3_scheduling/plan_decision_evaluator.py` and `layer2_calibration/calibrator.py` contain HA entity ids and pass.
  - Fix: `rglob` the core dirs and use `\b(sensor|switch|climate|binary_sensor|input_select)\.[a-z0-9_]+`.
- **F2 · Medium — OKF validation never actually runs.**
  - `test_okf_conformance.py:14-21` passes vacuously when `/config/.hermes/…/validate.sh` is absent, and it is absent on this host.
  - `AGENTS.md` rule 9 references `scripts/validate.sh`, which doesn't exist.
  - The pre-commit hook runs only the secret scanner, not the 5 traps rule 11 promises.
  - `AGENTS.md` is headed "5 Invariant Rules" but lists 11.
- **F3 · Medium — "Stable/verified" OKF docs that the code contradicts:**
  - `dhw-goldfish-elephant-control.md` Goldfish 3 (B2)
  - `passive-solar-gain.md` formula (E3)
  - `log.md` 2026-10-05 3-D OLS claim (E1)
  - `integrations/daikin_altherma/interlocks.py:11-14`: the docstring SG table (SG1 = S10S on/S11S off, SG4 = S10S off/S11S on) contradicts both the code and the OKF doc, which agree with each other. Verify against your wiring and fix the docstring.
- **F4 · Medium — Missing OKF entries for the concepts that cause the races.** Proposed `type: Invariant` docs under `knowledge/architecture/`:
  - `dhw-run-commitment.md`: single owner, target source, timeout, end conditions, telemetry-only run detection.
  - `peak-lockout-semantics.md`: cluster vs crest, `slot_lockout_map` as the canonical per-slot truth, and the format every consumer gets.
  - `time-and-slot-alignment.md`: UTC slot grid, DST, slot lookup by timestamp, monotonic cache ages.
  - `model-parameter-schema.md` (`type: Metric` or a schema doc): every key in `heatpump_model_parameters.json` with unit, owner, consumer and bounds.
  - `battery-soc-provenance.md`: live SoC only, Quality handling, inactive plan.
- **F5 · Low — Non-hermetic test.** `test_data_integrity_gate` fetches a live 7-day price forecast and looks for `/homeassistant/addons/...`. Rule 3 says CI must run on the replay harness only.
- **F6 · Low — Security.**
  - The HA long-lived token is sent with `CERT_NONE` to every candidate, including a public hostname (`client.py:52-79`; also `routes_forecast.py`, `routes_analytics.py`). Verify TLS for anything off-host.
  - The InfluxDB password travels in query strings (`daemon.py:959`, `context.py:251`).

---

## 3. What is solid

- **DHW DP:** exact backward induction with run and dwell states; no feasible counterexample in 36 scenarios.
- **File writes:** atomic (`os.replace`) everywhere.
- **HA actuator:** idempotency guards (`client.py:165-194`), and the CV-master-off interlock during SG4.
- **Battery LP:** sensible structure (knee and ramp penalties, terminal λ, explicit inactive plan). Import > export at every spot price, so there is no simultaneous import/export arbitrage.
- **Peak detector:** the winter cap, dwell rules and micro-peak filter are reasonable. Only the way its output is *consumed* is wrong (B1, C3).

## 4. Remediation plan

| # | Change | Fixes | Deadline |
|---|---|---|---|
| 1 | Single planning thread; HTTP is read-only; immutable plans (copy on publish/get) | A1, A3 (mutation), A6 | — |
| 2 | Layer 4 `DhwRunStateMachine` (single owner, DP target, timeout, telemetry-only detection); evaluator becomes observe-only; remove arming from context/planner | A2, A3, B2 | before cold weather |
| 3 | Per-slot lockouts into the DP and space heating; delete the post-strip | B1, C3 | — |
| 4 | UTC slot grid, monotonic cache, slot lookup by timestamp, stale-plan → SG2, HA dead-man automation | A4, A5 | **before 2026-10-25** |
| 5 | Persisted thermostat baseline; ownership-aware watchdog; release always allowed | C1, C2 | before cold weather |
| 6 | `None` + `Quality.STALE` for sensors; planners honour quality | B6, D3 | — |
| 7 | Fix the regression; parameter schema; single-writer params | E1, E2, E3, A7 | — |
| 8 | Battery into `CentralPlanner` with live SoC | D1, D2 | before real hardware |
| 9 | Widen guards; bundle the OKF validator; add the F4 docs; fix the harness timezone | F1–F5, C4 | — |

Each repro in `2026-10-09-repro.py` can become a regression test under `tests/` once its finding is fixed; invert the printed condition into an assertion.

## 5. Test baseline (this review)

`PYTHONPATH=. pytest tests/` in a clean venv (with `mcp`, `pytz` added): **215 passed, 3 failed.**
- `test_frontend_tooltips` needs `node` (environmental).
- `test_replay_winter_sunny_peak` (C4).
- `test_data_integrity_gate` needs `/homeassistant/addons/...` paths (F5).

Note: `requirements.txt` doesn't list `mcp` or `pytz`, which the test suite needs.

---

## 6. Fix status (applied 2026-10-09)

Changes are isolated in [`2026-10-09-fixes.patch`](2026-10-09-fixes.patch) (45 files) on top of the pre-fix working tree, which was snapshotted as git ref `refs/review/pre-fix-2026-10-09` (tracked files only). Verification: `pytest tests/` gives **243 passed** (23 new regression tests in `tests/unit/test_review_2026_10_09_regressions.py`); 3 tests need the HA host or Node and were not run here. Ruff is clean on the whole repo; mypy is clean on the project scope; bandit reports no new medium/high findings; the secret scanner passes. An end-to-end dispatcher walk-through against a stubbed HA showed the intended behaviour: arm → continue → release at target → CV restored only if Open HEMS owned it → fail-safe on missing sensor or stale plan.

| ID | Status | Where |
|---|---|---|
| A1 planning lock | **Fixed**: lock covers compute + publish; readers with a plan never wait; monotonic cache age | `api/context.py` |
| A2 in-flight run | **Fixed**: single owner `DhwRunSupervisor`, DP target per slot, expiry (2× planned run, 45–180 min), ends on target / lockout / unknown tank; run detection from valve + power only; arming removed from context, planner and evaluator | `layer4_control/dhw_run_supervisor.py`, `layer3_scheduling/plan_store.py` |
| A3 second actuator | **Fixed**: evaluator is observe-only; plans are immutable (deep copy on publish) | `layer3_scheduling/plan_decision_evaluator.py`, `plan_store.py` |
| A4 DST | **Fixed**: UTC slot grid, absolute-time keys, slot lookup by timestamp, monotonic cache | `sanitizer.py`, `dispatch_guard.py`, `api/context.py` |
| A5 fail-safe | **Fixed**: stale plan or no covering slot → SG2; heartbeat sensor + HA dead-man automation. *Deferred:* wiring the Layer 4 `SafetyGuard` dwell timer | `dispatch_guard.py`, `daemon.py`, `ha/automations/openhems_dispatch_deadman.yaml` |
| A6 snapshots | **Fixed**: one HA snapshot per dispatch tick and per planning run | `daemon.py`, `api/context.py` |
| A7 lost updates | **Fixed**: locked reload-merge-write (`params_store`); forecaster merges only the keys it owns; API and script use the store; no unconditional rewrite at import | `layer2_calibration/params_store.py` + callers |
| A8 MQTT | **Fixed**: varint length, QoS-aware parsing, PINGREQ, socket closed, per-topic TTL (`get_fresh`) | `daemon.py` |
| B1 lockouts | **Fixed**: peaks carry `hard_start_idx/hard_end_idx`; shared `hard_lockout_slot_indices`; DP and baseline honour them; in-flight never forced through a lockout | `peak_detection.py`, `dhw_optimizer.py`, `dhw_baseline.py` |
| B2 target / MAX_ON | **Fixed**: `DispatchPlanSlot.target_temp_c`; MAX_ON when the run target ≥ 52 °C; release at target even if the plan is still forced | `models/canonical.py`, `central_planner.py`, supervisor |
| B3 baseline guard | **Fixed**: requires comfort feasibility; adoption means *no forcing* (autonomous slots stay NORMAL) | `central_planner.py` (`_baseline_is_preferable`) |
| B4 false warning | **Fixed**: infeasible counterfactuals no longer flag "suboptimal" | `dhw_optimizer_explain.py` |
| B5 consolidation | **Fixed**: same pull-forward semantics, never into a peak, re-simulated so summary = dispatch (`result_from_u_plan`). Note: costs about €0.04/day vs the raw DP on the golden day | `central_planner.py`, `dhw_optimizer.py` |
| B6 invented temps | **Fixed in the control path**: tank `None` → no DHW planning or forcing; `is_fresh=False` without a reading; per-sensor parsing. *Deferred:* the 49.2 °C display default in `/api/model/dhw-status` | `api/context.py`, `sanitizer.py`, `daemon.py` |
| B7 tap-profile bias | **Deferred**: needs a data decision (phantom draws vs under-counting) | — |
| B8 baseline UA | **Fixed**: baseline simulates with the calibrated tank model (2.38 W/K on this host, not 2.5) | `dhw_baseline.py` |
| C1 watchdog | **Fixed**: ownership-aware (reverts only its own elevation), adopts user setpoints, persistent state | `layer4_control/room_thermostat_buffer.py`, `dispatch_state.py` |
| C2 release blocked | **Fixed**: release is never budget-limited | same |
| C3 cluster vs crest | **Fixed**: per-slot lockout map; MPC coasts only through the hard window | `space_heating_policy.py` |
| C4 winter replay | **Fixed**: harness uses Europe/Amsterdam; the winter golden test passes | `tests/unit/test_replay_harness.py` |
| C5 night window | **Fixed**: uses local slot clock times | `space_heating_policy.py` |
| C6 params I/O | **Fixed**: loaded once per plan | `space_heating_policy.py` |
| D1 battery in plan | **Fixed**: Priority 3 in `CentralPlanner` → `plan.battery_summary` + `device_dispatches`; views read the plan. The analytics what-if stays separate and is labelled | `central_planner.py`, `routes_forecast.py`, `routes_schedule.py` |
| D2 invented SoC | **Fixed**: live SoC only (`None` → inactive); without an installed battery a labelled simulation runs (`battery.plan_simulation`, default on) | `api/context.py`, routes |
| D3 forecast prices | **Partial**: `price_quality` per slot (good / forecast / interpolated); valuation unchanged (decision needed) | `sanitizer.py`, `canonical.py` |
| D4 tariffs / LP | **Partial**: configured tariffs used; SoC no longer rounded up. *Open:* salderingsregeling assumption | `central_planner.py`, `battery_policy.py` |
| E1 regression | **Fixed**: rank-checked `[ΔT, E_pv, 1]` fit; no constant fallbacks (292.6 / 318.5 removed); zip misalignment fixed; wind not "calibrated" without wind data | `learned_forecaster.py`, `calibrator.py` |
| E2 open loop | **Fixed**: dead `run_full_calibration` removed; PV ratio written to `building.c_solar_pv_ratio`, which the planner reads | `calibrator.py`, `learned_forecaster.py`, `routes_calibration.py` |
| E3 key semantics | **Partial**: `c_solar_pv_ratio` separated from `c_solar_passive` (GHI aperture); `c_wind` unit-band check (0.208 in the current params is rejected, default 15 W/(K·m/s) used). *Open:* parameter schema in OKF | `space_heating_policy.py` |
| F1 entity guard | **Fixed**: generic scan of all core files (negative-tested) | `tests/architecture/test_anti_drift_guards.py` |
| F2–F5 docs/OKF | **Open** (hand-off to Hermes) | — |
| F3 interlock docstring | **Fixed** (code docstring); OKF docs still to update | `interlocks.py` |
| F6 TLS | **Fixed**: verification relaxed only for internal HA hosts (`ha_ssl_context`). *Deferred:* InfluxDB password in query strings | `integrations/homeassistant/client.py` + callers |
| **New: CV master ownership** | **Fixed**: the actuator forced `switch.hc_mode_altherma_on` ON every tick, overriding a user's "heating off". It now only restores CV if Open HEMS switched it off (persisted flag) | `client.py`, `reader.py`, `api/context.py` |

### Behaviour changes to be aware of
- **Manual thermostat changes are respected.** A setpoint you set becomes the new baseline; pre-heat elevates relative to it.
- **The CV master switch stays off if *you* turned it off.** Open HEMS only switches it back on after its own DHW interlock.
- **DHW runs stop at the planned temperature.** If a 55.8 °C run reaches 55.6 °C, the relays return to SG2 even when the plan still shows forced slots. Runs no longer drift to 60 °C.
- **No tank reading, no DHW steering.** The Daikin runs autonomously and the plan says so (`SENSOR_UNAVAILABLE`).
- **Battery views show a labelled simulation** when no battery is installed (`battery.plan_simulation: false` turns it off); a real battery needs a live SoC.
- **First log line after deploy:** `building.c_wind_w_per_k_ms=0.208 outside [1, 60]`. Set a realistic value, or remove it to use the default.
- **New HA entity:** `sensor.openhems_dispatch_heartbeat`. **New file:** `/config/open_hems_dispatch_state.json` (CV and thermostat ownership).
