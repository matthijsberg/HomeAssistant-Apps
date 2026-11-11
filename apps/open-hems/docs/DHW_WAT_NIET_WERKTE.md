# DHW-sturing: wat niet werkte

**Doel:** naslag voor later. Welke aanpakken we voor de boilersturing probeerden, wat er misging en wat we ervan leerden.
**Opvolger:** `docs/adr/ADR-006-daikin-first-dhw-policy.md` (Daikin-first).
**Bewijs:** `scripts/backtest_dhw_policies.py` (closed-loop backtest, sep–okt 2026 en januari 2026).
**Vastgelegd:** 2026-10-10.

---

## Lessen in het kort

1. **Stuur niet preciezer dan je meet en dan de hardware kan.** De Daikin kent 40/50 °C (SG2) en 60 °C (SG4). Alles daartussen was software die een relais afkapte.
2. **Eén eigenaar per beslissing.** Elke laag die een plan "bijstuurt" (commitment, merger, consolidatie, baseline-adoptie) kostte meer dan hij opleverde.
3. **Vergelijk warmteprijzen, geen stroomprijzen.** Doorstoken naar 60 °C kost ~30 % meer stroom per kWh warmte.
4. **Robuust gaat voor optimaal.** Krap plannen op het P50-tapprofiel faalt zodra er meer getapt wordt dan verwacht.
5. **Meet het effect van een actuatie.** SG4 aanzetten is geen garantie dat er gestookt wordt.
6. **Controleer wat je data betekent** voordat je erop rekent.

---

## 1. Heuristische paden (vóór ADR-004)

**Wat:** `dhw_daytime_arbiter.py` koos tussen vaste paden: A1 naar 50 °C, A2 naar 60 °C, B1 standby, B2 bufferen. Daarbij kwamen een afstandsanker (`hours_to_anchor`) en een getrapte COP.

**Wat misging:**
- Het anker dwong willekeurige doeltemperaturen af.
- Runs raakten versnipperd: twee runs van 4 °C waar één run goedkoper was (ADR-004, context).

**Les:** regels moeten volgen uit de standen die de hardware heeft, niet uit bedachte paden.

## 2. Exacte DP met continue doeltemperaturen (ADR-004, 2026-09-18 t/m 2026-10)

**Wat:** achterwaartse dynamische programmering in `layer3_scheduling/dhw_optimizer.py`.
- **Toestand:** tanktemperatuur op een rooster van 0,25 °C, plus compressortoestand met min-run 45 min en rust 60 min.
- **Doelfunctie:** stroom + startkosten − restwaarde.
- **Comfort:** grens 40 °C + dynamische marge.

**Waarom het goed leek:** wiskundig optimaal binnen het model. Replays claimden 30–46 % lagere kosten dan de heuristiek.

**Wat misging:**
- **Geen hardwarestanden.** Tussendoelen als 52,3 en 56 °C bestaan niet in de Daikin. Ze ontstonden alleen doordat de supervisor SG4 loslaat bij doel − 0,2 °C.
- **Precisie zonder basis.** Eén thermische massa met één sensor (R5T) in een gelaagd vat, en een tapprofiel dat per weekdag schommelt van 2,9 tot 5,3 kWh_th.
- **Weinig opbrengst, fragiel comfort.** In de backtest won de DP met perfecte voorspelling hooguit €1,81 per maand (sep–okt). In januari was hij even duur als Daikin-first. Bij 1,5 × tapverbruik was hij €3,89 en €1,53 per maand duurder en zakte hij tot 38,1–38,6 °C, omdat hij krap boven de comfortgrens plant.

**Referentiecijfers** (kosten per maand, gecorrigeerd voor de eindvoorraad in het vat):

| Variant | sep–okt | sep–okt, zwaar | jan | jan, zwaar |
|---|---:|---:|---:|---:|
| `auto` (alleen spitsblok) | €18,61 | €25,13 | €21,95 | €30,06 |
| `dp` (losse DP, elk kwartier opgelost) | €4,78 | €13,92 | €19,89 | €29,49 |
| `dp_coupled` (DP zoals in productie gekoppeld) | €7,13 | €13,48 | €24,66 | €34,51 |
| `daikin_first` (ADR-006) | €6,59 | €10,03 | €19,83 | €27,96 |

**Les:** precisie loont alleen als meting en actuatie net zo precies zijn. Twee vaste doelen geven vanzelf buffer en zijn uitlegbaar.

## 3. Comfortmarges P95 / P60 / P50 / vast

**Wat:** een dynamische marge boven 40 °C, m_k = f × Σ(P95 − P50) / C over 8 uur. Instelbaar in de UI als p95, p60, p50 of vast.

**Wat misging:**
- **P95 maakte de grens strenger.** Op zaterdag 2026-09-19 lag de grens daardoor op ~42,5 °C in plaats van 40 °C. De DP stookte daardoor om 03:15 in plaats van later en goedkoper, wat die dag ~€0,10 kostte (`PLAN-dhw-comfortmarge-en-uitlegfixes.md`).
- **De grens kroop op.** Interpolatie over oneindige waarden liet de grens 0,25 °C per geblokkeerd kwartier oplopen.
- **P60 en P50 waren fragiel** bij zwaar tappen.

**Les:** de marge was een draaiknop voor een probleem dat ontstond door krap plannen. Met doelen van 50/60 °C en de eigen thermostaat van de Daikin eronder is alleen een vaste 1 K nodig, voor de beslissing om voor te verwarmen.

## 4. Lopende run vasthouden: commitment, ON_MANDATORY en her-armen

**Wat:**
- Een gestarte run was "toegezegd": de planner kreeg `ON_MANDATORY` en `in_flight_slots` mee.
- De supervisor armde met het DP-doel en armde opnieuw als het plan een hoger doel toonde.

**Wat misging:**
- **Review A2 (2026-10-09):**
  - vier schrijvers en drie wissers, zonder verloop;
  - de relaisstand ging als invoer terug de planner in, waardoor runs naar 52–58 °C bij 60 °C eindigden;
  - SG4 met de CV-master uit kon onbeperkt blijven staan.
- **Na de fix in v0.106.0 (één eigenaar) kroop het doel nog steeds op.**
  - Elke herplanning dwong 2 extra kwartieren af, waardoor het slotdoel steeg en de supervisor opnieuw armde.
  - Gezien op 2026-10-10: om 12:15 gearmd op 59,3 °C, om 13:26 her-armd op 59,9 °C.
  - In de backtest kost dit €2,35 (sep–okt) en €4,77 (januari) per maand extra. In januari is het daardoor duurder dan niets doen.

**Les:** voer nooit je eigen uitvoer terug als planningsinvoer. De uitvoerende laag mag geen doelen overnemen van een planner die steeds opnieuw optimaliseert.

## 5. Tweede actuatorpad en de opportunistische merger

**Wat:** `plan_decision_evaluator.py` en `OpportunisticDHWMerger` herkenden een autonome Daikin-run en besloten die door te zetten naar 60 °C. Eerst schreven ze rechtstreeks naar HA en pasten ze het gedeelde plan aan. Later deden ze alleen nog observeren.

**Wat misging:**
- **Review A3:** de interlocks en idempotentie werden omzeild, het P1P2-schrijfbudget werd verbruikt en het plan werd ter plekke aangepast.
- **Ook observe-only bleef het een tweede waarheid.** Op 2026-10-10 om 18:07 en 21:17 meldde hij "Geplande 60°C zonnebuffer is actief", terwijl het plan op 52,3 en 47,4 °C mikte en het donker was.

**Les:** één beslispad. Een component die alleen teksten schrijft, is nog steeds een tweede bron van waarheid.

## 6. Pleisters op de DP-uitvoer: consolidatie en baseline-adoptie

**Wat:**
- `_consolidate_dhw_runs` voegde runs met minder dan 1,5 uur ertussen samen.
- `_baseline_is_preferable` nam het autonome plan over als dat goedkoper was.

**Wat misging:**
- **Consolidatie (review B5)** voegde ongeplande verwarming toe zonder opnieuw te simuleren.
- **Baseline-adoptie (review B3)** nam ook plannen over die het comfort schonden: in 3 van 4 gevallen zakte het vat tot 39,7 °C. Bovendien werden voorspelde autonome runs geforceerde slots.
- **Samenvatting en dispatch liepen uiteen.**

**Les:** als je de uitvoer van een optimizer achteraf moet corrigeren, modelleert hij het verkeerde probleem.

## 7. Uitleg via tegenfeiten

**Wat:** `dhw_optimizer_explain.py` loste per run drie extra tegenfeiten op (geen ingreep, maximaal 50 °C, uitstel) om de beslissing uit te leggen.

**Wat misging:**
- **Valse alarmen (review B4).** "Solver suboptimaal" verscheen omdat de vergelijking liep tegen tegenfeiten die zelf onhaalbaar waren.
- **Ongeloofwaardige teksten.** "Bespaart €0,50" op een totaal van €0,50 (plan 2026-09-19).
- **Veel code.** 519 regels om één beslissing uit te leggen.

**Les:** als de beslissing een regel is, is de uitleg die regel met zijn getallen.

## 8. Het DHW-setpoint schrijven via P1P2 (tot v0.105.0)

**Wat:** boosten via `climate.set_temperature` op het boilersetpoint, bijvoorbeeld naar 54 of 60 °C, en dat daarna terugzetten.

**Wat misging:**
- Het P1P2-schrijfbudget raakte op en het EEPROM sleet.
- Een verhoogd setpoint kon blijven hangen (een "60 °C-residu"), zodat watchdogs nodig waren.
- Vervangen door relais-only (SG4) in v0.105.0, met een guardtest.

**Les:** stuur hardware via de vluchtige, native interface (de relais), nooit via persistente instellingen.

## 9. Prijsvergelijking in € per kWh stroom (eerste versie van het Daikin-first-voorstel)

**Wat:** "Boost naar 60 °C als stroom fors goedkoper is dan bij de volgende run, minus het stilstandsverlies."

**Wat misging:**
- **De COP-straf ontbrak.** 50→60 °C heeft bij 10 °C buiten een COP van 1,66, tegen 2,35 voor 40→50 °C. Dat is ~0,7 kWh extra stroom per boost.
- **Het stilstandsverlies is het kleine deel:** ~0,24 kWh_th per 10 uur.
- **Backtest januari:** €26,13 tegen €21,95 voor niets doen (+19 %). Met warmteprijzen: €19,83.

**Les:** vergelijk warmteprijzen (stroomprijs ÷ COP), nooit stroomprijzen.

## 10. Kleinere experimenten zonder winst (2026-10-10)

- **COP bij de gemiddelde vattemperatuur van elke run** in plaats van vast 45/55 °C. Niet beter, in sep–okt bij zwaar tappen zelfs €0,65 per maand duurder. Vast 45/55 °C is eenvoudiger en net zo goed.
- **Boost alleen in het ene goedkoopste kwartier vóór X.** Mist de rest van het goedkope venster. Vervangen door "de n goedkoopste kwartieren", met n het aantal kwartieren dat de run nodig heeft.
- **'Goedkoop' = de goedkoopste 20 % van de horizon** (variant `literal`). Te grof: dan boost je ook in kwartieren die goedkoop zijn, maar niet goedkoop genoeg.
- **Spitsblok zonder voorverwarmen.** 5,8 tot 11,5 uur per maand onder 39,5 °C, met als laagste waarde 36,2 °C.

## 11. Datavalkuilen

- **`market_tariffs` in InfluxDB** is een log van de HA-sensor `sensor.energyzero_today_energy_current_hour_price`, niet de prijs van de planner.
  - Rond 21–25 september 2026 veranderde de betekenis: eerst all-in, daarna ongeveer spot × 1,21 zonder energiebelasting.
  - De eerste backtest gebruikte deze reeks en mengde zo twee prijsdefinities. Gebruik de prijs van de planner: EnergyZero `all_in_with_vat` + leveranciersopslag.
- **`TariffProvider`** behandelt belasting en opslag als exclusief btw, terwijl de config-waarden inclusief btw zijn. Daardoor is de exportwaarde ~€0,021/kWh te laag. Hiervoor staat een vervolgtaak.
- **Standaardwaarden in plaats van ontbrekende data** (review B6). Met 50 of 48 °C als tanktemperatuur bij een ontbrekende sensor plant je op verzonnen temperaturen.
- **Het tapprofiel onderschat tappen tijdens een run** (review B7).

## 12. Het incident van 2026-10-10 's avonds

- **Wat er gebeurde:** vanaf 18:05 stonden SG4 en de CV-master uit. Er werd ~40 minuten tapwater verwarmd, daarna stookte de warmtepomp niet meer. Het vat zat vanaf ~19:45 tot in de nacht onder 40 °C, en de ruimteverwarming lag stil.
- **Oorzaak:** een voedingsstoring op de warmtepomp (vastgesteld door Matthijs op 2026-10-11). Daikin-timers waren al uitgesloten: de Daikin heeft er geen.
- **Wat niet werkte in de software:** de oude supervisor bleef SG4 met de CV-master uit vasthouden en opnieuw schrijven, ook al gebeurde er niets.
- **Les, verwerkt in ADR-006:** controleer het effect van SG4 met telemetrie, laat SG4 los na 10 minuten zonder tapwaterverwarming, en herstel dan de centrale verwarming.

---

## De oude code terugvinden

De volledige DP-keten staat in de git-geschiedenis, in commit `87b91ad` (v0.106.0):

```bash
git show 87b91ad:layer3_scheduling/dhw_optimizer.py
git show 87b91ad:layer3_scheduling/dhw_optimizer_explain.py
git show 87b91ad:layer3_scheduling/dhw_plan_adapter.py
git show 87b91ad:layer3_scheduling/opportunistic_merger.py
git show 87b91ad:layer4_control/dhw_run_supervisor.py
```

De wiskunde staat in `docs/adr/ADR-004-dhw-dispatch-optimization-problem.md`. De bevindingen staan in `docs/reviews/2026-10-09-control-logic-review.md`.
