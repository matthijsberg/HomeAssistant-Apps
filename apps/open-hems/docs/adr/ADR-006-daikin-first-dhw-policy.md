# ADR-006: Daikin-first tapwatersturing (vervangt ADR-004)

* **Status:** Proposed
* **Date:** 2026-10-10
* **Author:** Matthijs van den Berg / Claude
* **Deciders:** Open HEMS Architecture Working Group
* **Supersedes:** ADR-004 (DHW-dispatch als formeel optimalisatieprobleem), zodra deze ADR *Accepted* is
* **Implementation Plan:** `docs/plans/PLAN-dhw-daikin-first.md`
* **Evidence:** `scripts/backtest_dhw_policies.py`
* **Zie ook:** `docs/DHW_WAT_NIET_WERKTE.md` (wat we probeerden en waarom het niet werkte)

---

## Context & Problem Statement

### Hardware: drie relaisstanden, twee temperaturen
Sinds v0.105.0 stuurt Open HEMS het boilervat uitsluitend via de Smart Grid-relais. Het DHW-setpoint blijft 50 °C en wordt nooit geschreven (invariant 10, `test_never_write_dhw_climate_setpoint`).

| Stand | S10S / S11S | Gedrag Daikin |
|---|---|---|
| SG1 | uit / aan | Blokkade: de compressor staat stil |
| SG2 | uit / uit | Eigen thermostaat: start zodra het vat 10 K onder het setpoint komt (≤ 40 °C) en stopt bij het setpoint (50 °C) |
| SG4 | aan / aan | Geforceerd doorstoken tot het ingestelde maximum (60 °C). Open HEMS zet de CV-master uit (BUH-interlock) |

Matthijs bevestigde op 2026-10-10 dat de Daikin verder geen tapwatertimers heeft (geen maximale looptijd, geen minimale tijd tussen twee runs).

Een eindtemperatuur tussen 50 en 60 °C bestaat alleen doordat software SG4 halverwege loslaat. `DhwRunSupervisor` doet dat bij T ≥ doel − 0,2 °C.

### De huidige keten (ADR-004)
ADR-004 plant het vat met een exacte DP over een continu temperatuurrooster van 0,25 °C. Rond die solver is een keten gegroeid:

| Onderdeel | Regels | Rol |
|---|---:|---|
| `layer3_scheduling/dhw_optimizer.py` | 1.121 | DP, P60-comfortmarge, min-run- en rusttoestanden, restwaarde |
| `layer3_scheduling/dhw_optimizer_explain.py` | 519 | Drie tegenfeiten voor de uitlegteksten |
| `layer3_scheduling/opportunistic_merger.py` | 325 | Observe-only: autonome run doorzetten naar 60 °C |
| `layer3_scheduling/dhw_plan_adapter.py` | 238 | DP-resultaat → `DHWPlanSummary` en dispatch-slots |
| `layer3_scheduling/dhw_shadow_logger.py` | 235 | Schaduwvergelijking arbiter ↔ optimizer |
| `layer3_scheduling/central_planner.py` (deel) | ~120 | Run-consolidatie, baseline-guard, schatting lopende run |
| `layer4_control/dhw_run_supervisor.py` | 137 | In-flight commitment: armen, her-armen naar het slotdoel, vrijgeven |

Dit levert drie problemen op.

1. **Precisie zonder basis.** De DP rekent op 0,25 °C nauwkeurig. Het model is echter één thermische massa met één sensor (R5T) in een gelaagd vat, en het geleerde tapprofiel schommelt per weekdag van 2,9 tot 5,3 kWh_th.
2. **Koppeling in plaats van optimalisatie.** Elk onderdeel heeft een eigen idee van het doel.
   - De review van 2026-10-09 vond vier schrijvers op de lopende run (A2), een tweede actuatorpad (A3) en DP-invoer die nooit aankwam (B1).
   - Na de fixes in v0.106.0 is de koppeling nog steeds zichtbaar. Op 2026-10-10 werd een run her-armd van 59,3 naar 59,9 °C. Een run "max_on" naar 52,3 °C om 18:05 haalde maximaal 46,2 °C. Om 21:17 meldde de merger "Geplande 60°C zonnebuffer is actief".
3. **Onderhoud.** Ongeveer 2.400 regels planningscode plus tests voor beslissingen die fysiek uit drie relaisstanden bestaan.

### Bewijs: closed-loop backtest
`scripts/backtest_dhw_policies.py` simuleert elke variant op dezelfde plant met de productiebouwstenen:

- **Fysica:** de tankbalans van `models.physics.dhw_step`, `dhw_cop` en `dhw_electric_power_kw` met de gekalibreerde parameters, en UA 2,38 W/K.
- **Tapprofiel:** het geleerde 7×96-profiel (P50).
- **Spitsblokken:** de harde lockouts uit `detect_dynamic_price_peaks`, per kalenderdag.
- **Kosten:** `calculate_slot_financials`, met zonne-eigenverbruik tegen exportwaarde.
- **Prijzen:** de prijs die de planner krijgt, dus EnergyZero all-in incl. btw plus leveranciersopslag.
- **Telemetrie:** zon, basislast, buitentemperatuur en starttemperatuur van het vat, uit InfluxDB.

Elke planner kent prijzen, zon en buitentemperatuur 24 uur vooruit en plant op het P50-tapprofiel. In het scenario *zwaar* tapt het vat 1,5 × P50.

Kosten per maand voor tapwater, gecorrigeerd voor de warmte die aan het eind van de periode in het vat zit:

| Variant | sep–okt 2026 | sep–okt, zwaar | jan 2026 | jan, zwaar |
|---|---:|---:|---:|---:|
| `auto`: alleen spitsblok (SG1), verder de Daikin | €18,61 | €25,13 | €21,95 | €30,06 |
| `literal`: voorstel zoals geformuleerd (€/kWh stroom) | €9,41 | €15,40 | **€26,13** | **€32,63** |
| `daikin_first`: **dit besluit** | €6,59 | €10,03 | €19,83 | €27,96 |
| `daikin_first_noadvance`: dit besluit, zonder vervroegen | €6,90 | €10,17 | €20,37 | €28,55 |
| `daikin_first_nocop`: dit besluit, zonder COP | €7,39 | €10,20 | €23,76 | €31,26 |
| `dp`: huidige DP, elk kwartier opnieuw opgelost | €4,78 | €13,92 | €19,89 | €29,49 |
| `dp_coupled`: DP gekoppeld zoals in productie | €7,13 | €13,48 | €24,66 | €34,51 |

Comfort, als uren onder 39,5 °C / laagste temperatuur. De thermostaat start zelf bij 40 °C.

| Variant | sep–okt | sep–okt, zwaar | jan | jan, zwaar |
|---|---|---|---|---|
| `auto` | 5,8 u / 37,8 °C | 11,5 u / 37,6 °C | 6,5 u / 37,8 °C | 6,5 u / 36,2 °C |
| `daikin_first` | 0 / 39,7 °C | 0 / 39,6 °C | 0 / 39,6 °C | 0,8 u / 39,2 °C |
| `dp` | 0 / 40,6 °C | 3,8 u / 38,1 °C | 2,0 u / 38,5 °C | 1,0 u / 38,6 °C |

**Conclusies:**

1. **Met perfecte voorspelling** haalt `daikin_first` 87 % van de DP-besparing ten opzichte van `auto` in sep–okt (€1,81 per maand minder). In januari is hij €0,06 goedkoper dan de DP.
2. **Bij zwaarder tappen dan voorspeld** is `daikin_first` goedkoper dan de DP: €3,89 (sep–okt) en €1,53 (januari) per maand. Van de plannende varianten zakt alleen de DP dan onder 39 °C (38,1–38,6 °C). De DP plant krap boven de comfortgrens; vaste doelen van 50 en 60 °C geven vanzelf buffer.
3. **Vervroegen loont vooral in de winter.** De Daikin-run naar 50 °C eerder doen, als de warmte dan duidelijk goedkoper is, scheelt in januari €0,54 per maand. Het voorbeeld van 4 januari:
   - **Om 12:45** kost warmte €0,117/kWh_th (stroom €0,229, buiten 2,1 °C, COP 1,96).
   - **Om 19:00**, als de Daikin het zelf zou doen, kost warmte €0,146/kWh_th (stroom €0,272, buiten 0,3 °C, COP 1,86).
   - Vervroegen naar 50 °C is dus 20 % goedkoper. Doorstoken naar 60 °C niet: dat kost €0,163/kWh_th.
   - In januari komt het voordeel vooral van de prijs (−16 %); de betere COP overdag levert ~5 % op.
4. **Rekenen in € per kWh stroom kost in de winter geld.** De letterlijke variant is in januari €4,18 per maand (19 %) duurder dan niets doen. Alleen de COP-correctie scheelt in januari €3,93 en in sep–okt €0,80 per maand.
5. **Gratis stroom is zeldzaam.** Gratis betekent een effectieve prijs ≤ €0: eigen zonne-overschot terwijl terugleveren geld kost (negatieve exportwaarde).
   - In sep–okt kwam dat voor in 41 kwartieren op 4 van de 30 dagen, tussen 12 en 17 uur. In januari nooit.
   - Een all-in importprijs ≤ €0 kwam in geen van beide periodes voor.
6. **De productiekoppeling kost meer dan de DP oplevert.** `dp_coupled` (ON_MANDATORY zolang een run onder zijn doel zit) is €2,35 (sep–okt) en €4,77 (januari) per maand duurder dan de losse DP, en in januari duurder dan niets doen. Bij elke herplanning loopt het doel op. De kwartierstappen van de backtest overdrijven dit ten opzichte van de minuut-ticks in productie, maar het mechanisme is echt (59,3 → 59,9 °C op 2026-10-10).
7. **Een spitsblok zonder voorverwarmen kost comfort.** `auto` zit 5,8 tot 11,5 uur per maand onder 39,5 °C, met als laagste waarde 36,2 °C.

De COP-straf van doorstoken volgt uit het gekalibreerde model (`dhw_cop`: COP_50 = 2,0, k_T = 0,07, k_out = 0,05, ondergrens 1,4):

| Buiten | COP 40→50 °C | COP 50→60 °C | Boost moet goedkoper zijn met | Extra stroom per boost |
|---:|---:|---:|---:|---:|
| 10 °C | 2,35 | 1,66 | 29 % | 0,72 kWh |
| 5 °C | 2,10 | 1,49 | 29 % | 0,80 kWh |
| 0 °C | 1,85 | 1,41 | 24 % | 0,69 kWh |

Het extra stilstandsverlies van 60 °C ten opzichte van 50 °C is 24 W, ofwel ~0,24 kWh_th per 10 uur. Dat is het kleine deel van de rekening.

**Grenzen van de backtest:**
- Twee maanden.
- Perfecte 24-uursvoorspelling.
- Geen concurrentie met ruimteverwarming om de warmtepomp.
- Niet-getunede drempels.

Door de perfecte voorspelling en het ideale software-afkappunt zijn de DP-cijfers een bovengrens.

---

## Decision

### 1. Principe
Open HEMS grijpt alleen in als dat moet. De normale toestand is SG2: de Daikin regelt zelf. Er zijn precies twee doeltemperaturen, 50 °C en 60 °C. Berekende tussendoelen bestaan niet meer.

### 2. Eén getal per kwartier: de warmteprijs
**Warmteprijs = effectieve stroomprijs ÷ COP**, in € per kWh warmte.
- **Effectieve stroomprijs (p_eff):** `calculate_slot_financials` met P_el bij 50 °C. Zonne-overschot telt tegen exportwaarde, de rest tegen de all-in prijs.
- **COP:** uit het gekalibreerde model, met de buitentemperatuur van dat kwartier. De vattemperatuur ligt vast: 45 °C voor een run tot 50 °C, 55 °C voor doorstoken tot 60 °C.

Zo zitten zowel de goedkopere stroom als de betere COP overdag in één getal. Dat geldt ook voor de straf van doorstoken: 60 °C is per kWh warmte ~30 % duurder.

### 3. Prognose
Elke planrun simuleert één keer "Daikin autonoom" vanaf de gemeten tanktemperatuur, met de canonieke tankbalans, het P50-tapprofiel en SG1 in de harde spitsslots. Daaruit volgen:
- **X**: het eerste kwartier waarin de Daikin zelf zou gaan stoken (vat ≤ 40 °C), met de warmteprijs van die run (**c_X**);
- **spitsdip**: het eerste harde spitsblok waarin de prognose onder 40 °C + 1 K komt.

### 4. Regels
Open HEMS loopt per kwartier de regels af; de eerste die past, wint. Het gepubliceerde plan is de uitrol van dezelfde regels over de horizon, zodat plan en uitvoering niet uit elkaar lopen.

| # | Regel | Voorwaarde | Actie |
|---|---|---|---|
| 1 | Spitsblok | Kwartier in harde lockout (`hard_lockout_slot_indices`) | SG1. Een lopende run eindigt. |
| 2 | Lopende run afmaken | Er loopt een run van Open HEMS | SG4 tot T ≥ doel − 0,2 °C. Een boost stopt eerder zodra de warmte niet meer goedkoper is dan c_X en de stroom niet meer gratis is. |
| 3 | Voorverwarmen (comfort) | Spitsdip voorspeld | Start binnen 4 uur vóór de spits, op het moment met de laagste warmteprijs waarbij de run vóór de spits klaar is. Doel 50 °C, of 60 °C bij gratis stroom. Lukt dat niet meer: nu starten. |
| 4 | Gratis stroom | p_eff ≤ €0 en vat < 57 °C | SG4 → 60 °C |
| 5 | Doorstoken (60 °C) | Vat < 57 °C, en warmteprijs tot 60 °C × 1,05 + €0,005 < c_X | SG4 → 60 °C |
| 6 | Vervroegen (50 °C) | Vat ≤ 47 °C, en warmteprijs tot 50 °C × 1,10 < c_X | SG4 → 50 °C |
| 7 | Anders | — | SG2: de Daikin regelt zelf |

- **Moment kiezen:** regels 5 en 6 vuren alleen als 'nu' bij de goedkoopste kwartieren vóór X hoort (zoveel kwartieren als de run nodig heeft). Zo wordt het hele goedkope venster benut, niet het eerste kwartier dat toevallig goedkoop is.
- **Bij een spitsdip** speelt de voorverwarmrun de rol van X: c_X is dan de warmteprijs van die run en het venster loopt tot de spits.
- **Marges:** de factor 1,05 dekt het extra stilstandsverlies van 60 °C, en de €0,005 voorkomt pendelen. De 10 % van vervroegen dekt het extra stilstandsverlies van eerder stoken. De grens van 47 °C voorkomt korte runs (minimaal ~3 K).
- **Comfort, geen prijs:** regel 3 is een comfortregel. Tijdens SG1 kan de Daikin niet stoken, dus de afweging "vóór of in de spits" bestaat niet.

### 5. Vangnet in Layer 4
Wat blijft:
- maximale SG4-duur, max(45, min(180, 2 × geplande duur)) minuten;
- geen SG4 bij een onbekende tanktemperatuur;
- CV-master-interlock met eigenaarschap (`cv_forced_off_by_hems`);
- terugval naar SG2 bij een verouderd plan (dispatch guard), en de HA-dead-man;
- de cap van 150 minuten op SG1;
- de Elephant-watchdogs: boiler op `heat`, setpoint nooit schrijven.

Nieuw:
- **SG4 zonder effect.** Meet de telemetrie binnen 10 minuten na inschakelen geen tapwaterverwarming (driewegklep op tapwater én compressorvermogen > 600 W)? Dan laat de supervisor SG4 los en herstelt de CV-master. Layer 4 rapporteert dan `effective_mode = normal` met een `downgrade_reason`. Daarna wordt 60 minuten niet opnieuw gearmd.

### 6. Eigenaarschap
- **Beleid:** de policy is een pure functie in Layer 3 (`layer3_scheduling/dhw_policy.py`), zonder HA-entiteiten of I/O. Per slot levert hij een DHW-intentie: `normal`, `forced_on` (50 °C), `max_on` (60 °C) of `forced_off`, met doel en reden.
- **Afstemming:** `CentralPlanner` stemt die intenties af met de ruimteverwarming (SG3) binnen de 6-statustaxonomie. SG1 en SG4 werken ook op de CV, dus het DHW-beleid stuurt nooit zelf relais.
- **Supervisor:** `DhwRunSupervisor` blijft de enige eigenaar van de lopende run en kent alleen nog de doelen 50 en 60 °C.
  - Een run wordt niet meer her-armd naar een willekeurig hoger plandoel. Wel mag een run naar 50 °C opschalen naar 60 °C als het plan `max_on` zegt.
  - De planner gebruikt de lopende run alleen als begintoestand van de uitrol, niet meer als ON_MANDATORY-invoer.

### 7. Parameters
Instelbaar via de config onder `dhw_policy` (vervangt `dhw_optimizer`) én via de instellingen in de UI (`/api/settings`).

```json
"dhw_policy": {
  "engine": "daikin_first",
  "preheat_margin_c": 1.0,
  "preheat_window_hours": 4.0,
  "boost_max_start_temp_c": 57.0,
  "boost_standby_factor": 0.05,
  "boost_margin_eur_per_kwh_th": 0.005,
  "advance_margin": 0.10,
  "advance_max_start_temp_c": 47.0,
  "free_price_eur_per_kwh": 0.0,
  "sg4_release_hysteresis_c": 0.2,
  "sg4_no_effect_timeout_min": 10,
  "sg4_no_effect_cooldown_min": 60
}
```

`engine` (`daikin_first` | `dp`) bestaat alleen tijdens de overgang, als terugvaloptie. Het veld verdwijnt samen met de DP.

---

## Alternatives Considered

1. **De DP houden en alleen de koppeling repareren** (supervisor, ON_MANDATORY, merger). Afgewezen:
   - de complexiteit blijft;
   - de winst van de precisie is in het beste geval ~€2 per maand;
   - bij afwijkend tapgedrag is die winst negatief.
2. **Het voorstel letterlijk**, met prijsvergelijking in € per kWh stroom. Afgewezen: in de winter duurder dan niets doen.
3. **Elke ingreep altijd naar 60 °C**, zonder software-stop op 50 °C. Afgewezen: het deel van 50 naar 60 °C kost bij netstroom ~30 % meer per kWh warmte. Bij gratis stroom gaat ook voorverwarmen wél naar 60 °C.
4. **COP bij de gemiddelde vattemperatuur van elke run** in plaats van vast 45/55 °C. Getest en afgewezen: niet beter, in sep–okt bij zwaar tappen zelfs €0,65 per maand duurder, en lastiger uit te leggen.

---

## Consequences

### Verdwijnt
- `dhw_optimizer.py` verdwijnt volledig, ook uit de backtest. Wat de DP deed, wat hij opleverde en waarom hij niet werkte, staat in `docs/DHW_WAT_NIET_WERKTE.md`. De code blijft in de git-geschiedenis (commit `87b91ad`).
- `dhw_optimizer_explain.py`, `opportunistic_merger.py` en `dhw_shadow_logger.py`.
- Het grootste deel van `dhw_plan_adapter.py`.
- De observe-only merger en de nachtbeslissing in `plan_decision_evaluator.py`.
- In `CentralPlanner`: run-consolidatie, baseline-guard, `IN_FLIGHT_DEG_PER_SLOT` en `BOOST_RUN_THRESHOLD_C`.
- De comfortmarge-instelling (P50/P60/P95/vast) in API en UI.

### Blijft
- `detect_dynamic_price_peaks`, `models/physics.py` en het tapprofiel en UA in `DhwThermalModel`.
- `DhwTankSpec` en `calculate_slot_financials`.
- `simulate_autonomous`, dat de kern van de prognose wordt.
- `DaikinInterlock`, de dispatch guard en de dead-man.

### Afwegingen en risico's
- **Besparing:** met perfecte voorspelling tot ~€2 per maand minder dan een ideaal uitgevoerde DP in een zonnige maand, en gelijk in de winter. We kiezen bewust voor eenvoud en robuustheid; bij afwijkend tapgedrag wint deze aanpak.
- **Stroomverbruik:** hoger door boosts bij lagere COP, maar per kWh goedkoper (sep–okt +21 % kWh, januari +7 %). Kosten-KPI's moeten kWh_el en € daarom apart tonen.
- **Compressorstarts:** vervroegen geeft in januari meer starts (51 tegen 42 bij `auto`). De ondergrens van 3 K per run houdt dat beperkt.
- **Incident 2026-10-10:** SG4 stond met de CV-master uit, maar de warmtepomp stookte urenlang niet. De oorzaak was een voedingsstoring op de warmtepomp (vastgesteld door Matthijs op 2026-10-11). De oude supervisor hield SG4 met de CV-master uit vast; de effectiviteitscheck in Layer 4 had dat na 10 minuten losgelaten en de centrale verwarming hersteld.
- **Uitleg:** de uitleg wordt regelgebaseerd: één zin per beslissing, met de warmteprijzen uit de regel. Er is geen engine voor tegenfeiten meer.

### Invarianten
- **1 (Dumb Views):** `DHWPlanSummary` met traject en uitleg blijft de enige bron voor de UI.
- **5 (API & MCP Lockstep):** `/api/settings` gaat van `dhw_optimizer` naar `dhw_policy`. `docs/openapi.json` (+ yaml) en `mcp_server.py` gaan tegelijk mee.
- **8 (15m/1h-pariteit):** de DHW-grafieken worden op beide resoluties gecontroleerd.
- **9 (OKF):**
  - `knowledge/architecture/dhw-goldfish-elephant-control.md` bijwerken: doelen 50/60 °C, geen DP-doel per slot.
  - Nieuw concept voor dit beleid.
  - Nieuwe metric voor de warmteprijs (€/kWh_th).
- **10 (Elephant & Goldfish):** versterkt. Alleen 50 of 60 °C, en er blijft niets hangen.
- **12 (Actuator Isolation):** ongewijzigd. Eén eigenaar per actuator; de policy schrijft niets naar HA.

---

## Acceptance Criteria

1. De geïmplementeerde policy reproduceert de prototyperesultaten van `daikin_first` in `scripts/backtest_dhw_policies.py` op beide periodes:
   - P50: niet meer dan €2,50 per maand duurder dan de DP-cijfers in deze ADR.
   - Zwaar: niet duurder dan de DP-cijfers in deze ADR.
   - P50: 0 uur onder 39,5 °C.
   - Zwaar: hooguit 2 uur onder 39,5 °C en nooit onder 39,0 °C.
2. Twee weken productie met de policy:
   - geen comfortschending door de policy (vat < 40 °C buiten een onvoorspelde tappiek);
   - geen SG4 met CV-master uit langer dan 10 minuten zonder tapwaterverwarming.
3. `PYTHONPATH=. pytest tests/` is groen. De golden snapshots zijn bewust opnieuw gemaakt en elk verschil is verklaard.
