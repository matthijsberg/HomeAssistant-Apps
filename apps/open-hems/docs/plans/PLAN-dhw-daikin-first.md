# Plan — DHW Daikin-first (ADR-006)

**Doelversie:** 0.107.0 (Tier 2 MINOR: gedragswijziging van de boilersturing)
**Aangemaakt:** 2026-10-10 door Claude (Code-sessie), in opdracht van Matthijs
**Besluit:** `docs/adr/ADR-006-daikin-first-dhw-policy.md`
**Meetlat:** `scripts/backtest_dhw_policies.py`. `RulesPolicy` met `RuleParams()` daarin is de referentie-implementatie van de regels.
**Speelregels:** `AGENTS.md` (12 invarianten)

---

## 0. Samenvatting voor de uitvoerder

Volgorde: **WP1 → WP2 → WP3 → WP4 → twee weken productie → WP5 → WP6**. WP0 is klaar.

| WP | Wat | Waarom | Grootte |
|---|---|---|---|
| WP0 | Backtest in de repo | Meetlat en bewijs voor ADR-006 | klaar |
| WP1 | Pure policy-module `layer3_scheduling/dhw_policy.py` + tests | De regels als één pure functie, overgenomen uit het prototype | klaar (2026-10-10) |
| WP2 | `CentralPlanner` gebruikt de policy, achter `dhw_policy.engine` | Het plan is de uitrol van de regels; de DP blijft terugvaloptie | klaar (2026-10-10) |
| WP3 | Layer 4: supervisor vereenvoudigen + SG4-effectiviteitscheck | Geen doelkruip meer; geen uren SG4 met CV uit zonder tapwater | klaar (2026-10-11) |
| WP4 | Uitleg, instellingen-API (OpenAPI + MCP), UI | Regelgebaseerde uitleg; `dhw_optimizer` → `dhw_policy` | klaar (2026-10-11), browsercontrole met screenshots nog open |
| WP5 | DP-keten opruimen (na twee weken stabiel) | ~2.400 regels plus tests weg | L |
| WP6 | Kennis (OKF), ADR-status, docs, release | Invariant 9; ADR-004 wordt *Superseded*; CHANGELOG 0.107.0 | S |

**Incident 2026-10-10:** het vat zat urenlang onder 40 °C terwijl SG4 met de CV-master uit stond. Oorzaak: een voedingsstoring op de warmtepomp (Matthijs, 2026-10-11). De effectiviteitscheck uit WP3 had SG4 na 10 minuten losgelaten en de centrale verwarming hersteld.

---

## 1. WP0 — Backtest als meetlat (klaar)

```bash
PYTHONPATH=. python3 scripts/backtest_dhw_policies.py extract --start 2026-09-09 --days 30 --out /config/open_hems_backtest/2026-09.json
PYTHONPATH=. python3 scripts/backtest_dhw_policies.py extract --start 2026-01-01 --days 31 --out /config/open_hems_backtest/2026-01.json
PYTHONPATH=. python3 scripts/backtest_dhw_policies.py run --data /config/open_hems_backtest/2026-09.json
```

- **Wat het script doet:** zeven varianten (`auto`, `literal`, `daikin_first`, `daikin_first_noadvance`, `daikin_first_nocop`, `dp`, `dp_coupled`) × twee tapscenario's (P50 en 1,5 × P50), closed loop, met de productiefysica en kostenfuncties. De resultaten staan in ADR-006.
- **Data:** de uitvoerbestanden bevatten telemetrie van de woning. Zet ze buiten de repository.
- **Prijzen:** EnergyZero levert kwartierdata vanaf 2025-10-01, dus elke periode vanaf die datum is te draaien.

---

## 2. WP1 — Pure policy-module

**Nieuw:** `layer3_scheduling/dhw_policy.py`, `tests/unit/test_dhw_policy.py`.

### 2.1 Inhoud
1. `DhwPolicyParams` (dataclass) met `from_config(cfg)`.
   - De velden staan in ADR-006 §7. Er zijn geen magische getallen.
   - Begrens de waarden zoals `DhwOptimizerParams.from_config` dat doet.
2. `forecast_autonomous(...)` geeft het verloop zonder ingreep terug: traject, stookkwartieren, **X** en de start van de **spitsdip**.
   - Basis is `simulate_autonomous` uit `dhw_baseline.py`, met `models.physics.dhw_step`.
   - Het kWh-verbruik volgt uit `dhw_electric_power_kw`.
3. `plan_dhw(slots, t0_c, latch, in_flight, hard_slots, spec, dhw_model, tariff_provider, model_parameters, params) -> DhwPolicyResult`.
   - Rolt de regels uit ADR-006 §4 per kwartier uit over de horizon, met de P50-prognose.
   - Per slot levert het: `slot_modes` (`normal` | `forced_on` | `max_on` | `forced_off`), `slot_targets` (`None` | 50 | 60) en `slot_reasons`.
   - Daarnaast: het P50-traject, en een P05/P95-band met dezelfde relaisvolgorde maar P05/P95-tap.
   - Verder: `runs` (start, eind, doel, kWh_el, €), het `autonomous_trajectory` en een korte `explanation` per run.
   - `in_flight` is de commitment uit `PlanStore`, alleen gelezen. Die zet de begintoestand van de uitrol (soort en doel).
4. Overnemen uit het prototype (`scripts/backtest_dhw_policies.py`, `RulesPolicy.decide`):
   - de warmteprijs: `p_eff / COP(55 °C, T_buiten)` voor doorstoken naar 60 °C en `p_eff / COP(45 °C, T_buiten)` voor een run naar 50 °C;
   - de regels uit ADR-006 §4 in dezelfde volgorde: spitsblok, lopende run afmaken, voorverwarmen, gratis stroom, doorstoken, vervroegen;
   - het voorverwarmvenster en de n goedkoopste kwartieren vóór X;
   - het stopcriterium van een boost.
5. Daarna verwijst de backtestvariant `daikin_first` naar `dhw_policy` in plaats van naar het prototype. Implementatie en bewijs kunnen dan niet meer uit elkaar lopen. `literal`, `daikin_first_noadvance` en `daikin_first_nocop` blijven via parameters bestaan.

### 2.2 Tests (minimaal)
1. Harde lockout → `forced_off`, ook als er een commitment loopt.
2. Spitsdip voorspeld → voorverwarmen naar 50 °C, gestart in het goedkoopste haalbare kwartier binnen 4 uur vóór de spits en klaar vóór de spits.
3. Spitsdip met negatieve prijs op dat startkwartier → doel 60 °C.
4. Negatieve effectieve prijs, vat op 50 °C → meteen `max_on` naar 60 °C.
5. Netstroom zonder zon, 20 % goedkoper dan de run bij X → geen boost (COP-grens). 40 % goedkoper → wel een boost.
6. Zonnevenster → de boost valt in de n goedkoopste kwartieren vóór X, niet in het eerste goedkope kwartier.
7. X buiten de horizon en geen gratis stroom → geen boost.
8. Vat ≥ 57 °C → geen boost.
9. Het goedkope venster sluit vóór 60 °C → de boost stopt.
10. Vervroegen: vat 45 °C, warmte nu 20 % goedkoper dan bij X (betere COP overdag, geen boost-voordeel) → SG4 naar 50 °C. Bij 5 % goedkoper → niets.
11. Vervroegen bij vat > 47 °C → niets (geen korte runs).
12. Alleen doelen 50 en 60 °C in de uitvoer, nooit een tussenwaarde.

`test_core_entity_isolation` dekt al dat het bestand geen HA-entiteiten bevat. Draai daarnaast de backtest: `daikin_first` moet dezelfde cijfers geven als in ADR-006, binnen afrondingsverschillen.

---

## 3. WP2 — Integratie in `CentralPlanner`

**Bestanden:**
- `layer3_scheduling/central_planner.py` en `api/context.py` (parameters doorgeven);
- een nieuwe dunne adapter `dhw_policy_result → DHWPlanSummary` (bijvoorbeeld in `dhw_policy.py` of een nieuwe `dhw_policy_adapter.py`);
- de tests.

1. **Flag in `plan()`.** Bij `dhw_policy.engine == "daikin_first"` roept de planner `plan_dhw(...)` aan.
   - Dit vervangt het blok van `solve(...)` tot en met consolidatie, baseline-adoptie en schaduwvergelijking (nu ~r. 329–447).
   - De takken voor `is_dhw_enabled` en `current_dhw_temp is None` blijven zoals ze zijn.
2. **Dispatch-slots:**
   - `mode_code` komt uit de policy, en `target_temp_c` is 50 of 60 °C voor SG4-slots.
   - `dhw_kw` volgt uit het uitroltraject, voor SG4-slots én voor verwachte autonome Daikin-runs (zoals `autonomous_dhw_slots` nu).
   - `BOOST_RUN_THRESHOLD_C` verdwijnt: de modus volgt de regel, niet een drempel van 52 °C.
3. **`DHWPlanSummary`:**
   - De velden komen uit de eerste run binnen 24 uur.
   - `unheated_trajectory` is de prognose zonder ingreep.
   - **Houd** in `decision_details` de sleutels die UI en API lezen: `trajectory`, `unheated_trajectory`, `comfort_boundary_c` (= 40 + `preheat_margin_c`), `morning_dip_c`/`morning_dip_time`, `explanation`, `badge_html`, `status`, `planned_mode`, `dynamic_peaks`. Zet `planner` op `"daikin_first"`.
   - **Laat vallen:** de DP-sleutels `j_objective_eur`, `net_objective_eur`, `salvage_value_eur`, `start_cost_eur`, `comfort_margin_mode`, `shadow_comparison` en de besparingen uit de tegenfeiten.
   - Controleer per sleutel: `web/js/app.js`, `web/js/modules/charts_thermal.js`, `api/routes_forecast.py`, `api/routes_schedule.py`, `integrations/homeassistant/sensor_pusher.py`.
4. **Ruimteverwarming:** `active_dhw_slots` = SG4-slots ∪ verwachte autonome runs, net als nu.
5. **Terugvaloptie:** `dhw_policy.engine` staat standaard op `daikin_first`. Met `dp` draait het oude pad tot WP5.
6. **Golden replay:** draai `tests/unit/test_replay_harness.py`. Verklaar het verschil per golden (welke run, welk doel, welke kosten) en maak de snapshots pas daarna opnieuw.

**Tests:**
- Nieuw: `tests/unit/test_central_planner_dhw_policy.py`. Test beide flagstanden, alleen doelen 50/60 °C, en geen SG4 in een harde lockout.
- Bijwerken: `test_central_planner_explanations.py`, `test_device_slot_dispatch.py`, `test_architecture_consistency.py`.

---

## 4. WP3 — Layer 4

**Bestanden:** `layer4_control/dhw_run_supervisor.py`, `daemon.py` (`execute_live_dispatch`), `layer3_scheduling/central_planner.py` (lezen van de lopende run), tests.

1. **Doelen:** alleen 50 en 60 °C, en de modus bepaalt het doel: `forced_on` = 50 °C, `max_on` = 60 °C. Een afwijkend `target_temp_c` in een slot is een planfout: loggen en negeren.
2. **Her-armen:** de tak `rearmed` vervalt. Eén uitzondering: een voorverwarmrun naar 50 °C schaalt op naar 60 °C als het huidige slot `max_on` is. Dit sluit de doelkruip af (59,3 → 59,9 °C op 2026-10-10).
3. **SG4-effectiviteitscheck:**
   - **Invoer:** `dhw_heating_observed`, uit `read_dhw_activity`: `valve_on` en `power_w > 600`.
   - **Bij armen:** sla `armed_at` op.
   - **Loslaten:** geen tapwaterverwarming binnen `sg4_no_effect_timeout_min` (10) → vrijgeven en `normal` teruggeven, met als reden "SG4 zonder tapwaterverwarming".
   - **Gevolgen:** de CV-master komt terug via het bestaande eigenaarschap. De actuator rapporteert `effective_mode = normal` met een `downgrade_reason`.
   - **Afkoeltijd:** daarna wordt `sg4_no_effect_cooldown_min` (60) minuten niet opnieuw gearmd. Pas de waarde aan als het incidentonderzoek daar aanleiding toe geeft.
4. **Planner:** bij `daikin_first` geen `ON_MANDATORY` en geen `in_flight_slots` meer; dat is alleen DP-invoer. De lopende run gaat als begintoestand naar `plan_dhw`, zodat het plan hem toont.
5. **`daemon.py`:** sla bij `daikin_first` de observe-only aanroepen van `evaluate_and_apply_dhw_run_merger` en `evaluate_and_log_night_boiler_decision` over (nu ~r. 520–530). Ze verdwijnen in WP5.

**Tests:** uitbreiden in `tests/unit/test_goldfish_elephant_dhw.py` en de supervisortests in `tests/unit/test_review_2026_10_09_regressions.py`:
1. Gearmd op 59,3 → het doel blijft 60 °C; geen her-arm naar 59,9.
2. Opschalen van 50 naar 60 °C bij `max_on`.
3. Geen effect na 10 minuten → vrijgeven en de CV terug.
4. Afkoeltijd.
5. De lockout wint nog steeds.
6. Een onbekende tanktemperatuur geeft nog steeds geen SG4.

---

## 5. WP4 — Uitleg, instellingen-API, UI

1. **Uitleg:** `dhw_policy` maakt één zin per beslissing, met de getallen uit de regel. Voorbeelden:
   - "Boost naar 60 °C (12:45–14:00): zonne-overschot, warmte €0,02/kWh tegen €0,14 voor de run om 21:15."
   - "Voorverwarmen naar 50 °C (15:30–16:15): zonder ingreep zakt het vat om 18:30 onder 41 °C, tijdens de spits van 17:30–20:00."
   - "Geen ingreep: de Daikin warmt zelf op om 21:15 (€0,26/kWh); geen kwartier levert minstens 30 % goedkopere warmte."
2. **Instellingen-API** (`api/routes_system.py`, GET/POST `/api/settings`):
   - `dhw_optimizer` (met `comfort_margin` en `min_run_slots`) wordt vervangen door `dhw_policy`, met grenzen per veld.
   - Bij opslaan verdwijnen de oude `dhw_optimizer`-sleutels uit de config.
   - Werk `docs/openapi.json` en `docs/openapi.yaml` (schema en beschrijving) en `mcp_server.py` tegelijk bij (invariant 5).
   - Herschrijf `tests/unit/test_settings_api.py`; `tests/architecture/test_api_mcp_lockstep.py` moet groen blijven.
3. **UI** (instellingen in UI én config, besluit 2026-10-10):
   - Vervang het comfortmargeblok in `web/index.html` (rond r. 1850, `btn-save-dhw-margin`) door een compact `dhw_policy`-blok:
     - voorverwarmmarge en -venster;
     - vervroegmarge en de maximale starttemperatuur voor vervroegen;
     - de maximale starttemperatuur voor doorstoken;
     - de drempel voor gratis stroom.
     De overige parameters blijven config-only.
   - Vervang `loadDhwSettingsFromApi` en `saveDhwMarginFromTab` in `web/js/app.js` (rond r. 4120–4190) door laad- en opslagfuncties voor `dhw_policy`. Na opslaan volgt direct een herberekening, zoals nu.
   - `charts_thermal.js` (r. ~618, ~667) blijft `unheated_trajectory` en `comfort_boundary_c` krijgen.
4. **QA:** headless browser met screenshots op 15m én 1h (invarianten 6 en 8) en geen consolefouten. Controleer dat de runs op dezelfde kalenderuren staan bij beide resoluties.

---

## 6. WP5 — Opruimen (na twee weken stabiel in productie)

**Poort:** de acceptatiecriteria van ADR-006 zijn gehaald. De backtest is ook gedraaid op een zomerperiode (juni–augustus 2026) en met 48 uur horizon (`extract --horizon-days 2`, `run --horizon-hours 48`).

**Weg:**
- `layer3_scheduling/dhw_optimizer.py`, volledig (besluit 2026-10-10). Verwijder tegelijk de backtestvarianten `dp` en `dp_coupled`. Hun cijfers staan vastgelegd in ADR-006 en `docs/DHW_WAT_NIET_WERKTE.md`, de code blijft in de git-geschiedenis (commit `87b91ad`).
- `layer3_scheduling/dhw_optimizer_explain.py`, `dhw_shadow_logger.py`, `opportunistic_merger.py`, en `dhw_plan_adapter.py` (vervangen in WP2).
- In `layer3_scheduling/plan_decision_evaluator.py`: `evaluate_and_apply_dhw_run_merger` en `evaluate_and_log_night_boiler_decision`, met hun aanroepen in `daemon.py`, `api/routes_forecast.py` en `api/routes_schedule.py`.
- `DhwThermalModel.evaluate_night_heating_decision`, als er geen aanroepers meer zijn.
- In `CentralPlanner`: `_consolidate_dhw_runs`, `_baseline_is_preferable`, `IN_FLIGHT_DEG_PER_SLOT`, `BOOST_RUN_THRESHOLD_C`, het DP-pad en de flag.
- `DhwOptimizerParams` in `api/context.py`.

**Tests:**
- **Verwijderen:** `test_dhw_optimizer.py`, `test_dhw_optimizer_adapter.py`, `test_dhw_optimizer_behaviors.py`, `test_dhw_optimizer_feasibility.py`, `test_dhw_trajectory_demand.py`, `test_opportunistic_merger.py`, `test_in_flight_run_continuity.py`.
- **Inkorten:**
  - `test_dhw_spec_config.py`: de AST-guard op `dhw_optimizer.py`;
  - `test_dhw_power_params_integration.py`: het adapterdeel;
  - `test_dhw_baseline.py`: de DP-vergelijkingen;
  - `test_review_2026_10_09_regressions.py`: de DP-delen;
  - `test_replay_harness.py`: `DhwOptimizerParams`.
- **Nieuwe architectuurguard:** geen runtimemodule importeert de DP.

---

## 7. WP6 — Kennis, ADR, docs, release

- **OKF:**
  - Werk `knowledge/architecture/dhw-goldfish-elephant-control.md` bij: doelen 50/60 °C, geen DP-doel per slot, SG4-effectiviteitscheck.
  - Nieuw: `knowledge/architecture/dhw-daikin-first-policy.md` (de regels als invariant) en `knowledge/metrics/heat-price-per-kwh-th.md`.
  - Werk de indexbestanden bij en draai `scripts/validate.sh knowledge` en `tests/architecture/test_okf_conformance.py`.
- **ADR's:** ADR-006 wordt *Accepted*. ADR-004 krijgt de status "Superseded by ADR-006".
- **Docs:**
  - `ARCHITECTURE.md`: de DHW-bullet in Layer 3 en de supervisor-bullet in Layer 4.
  - `PRD.md`: §3.2 en de mappenboom.
  - De vermeldingen in `README.md`.
- **Release:** `CHANGELOG.md` en `VERSION` naar 0.107.0.

---

## 8. Beslissingen (Matthijs, 2026-10-10)

1. **Daikin-gedrag:** SG2 stookt tot het setpoint (50 °C) zodra het vat 10 K daaronder komt. Alleen SG4 stookt door tot het ingestelde maximum (60 °C). De Daikin heeft geen verdere tapwatertimers.
2. **Overdag stoken in de winter:** wordt opgevangen met één getal per kwartier, de warmteprijs (stroomprijs ÷ COP bij de buitentemperatuur van dat kwartier). De regel *vervroegen* stookt naar 50 °C als die warmte ≥ 10 % goedkoper is dan wanneer de Daikin het zelf zou doen. In de backtest scheelt dat in januari €0,54 per maand. *Gratis stroom* (effectieve prijs ≤ €0) kwam in sep–okt op 4 van de 30 dagen voor en in januari nooit.
3. **De DP:** gaat in WP5 helemaal weg. Wat niet werkte, staat in `docs/DHW_WAT_NIET_WERKTE.md`.
4. **Instellingen:** `dhw_policy` komt in de UI én in de config.

---

## 9. Definition of done

- De acceptatiecriteria van ADR-006 zijn gehaald.
- De checklist in `AGENTS.md` is groen: tests, de vijf pre-commit-traps, API/MCP-lockstep en OKF.
- Headless browser-QA op 15m en 1h zonder consolefouten.
- `CHANGELOG.md` en `VERSION` zijn bijgewerkt en de golden snapshots zijn verklaard opnieuw gemaakt.

## 10. Verificatie

```bash
PYTHONPATH=. pytest tests/
PYTHONPATH=. pytest tests/unit/test_dhw_policy.py tests/unit/test_replay_harness.py tests/architecture/
PYTHONPATH=. python3 scripts/backtest_dhw_policies.py run --data /config/open_hems_backtest/2026-09.json
PYTHONPATH=. python3 scripts/backtest_dhw_policies.py run --data /config/open_hems_backtest/2026-01.json
scripts/validate.sh knowledge
```
