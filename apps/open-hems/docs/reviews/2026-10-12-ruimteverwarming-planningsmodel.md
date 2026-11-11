# Open HEMS — Evaluatie & Analyse Ruimteverwarming Planningsmodel (2R1C)

**Datum:** 12 oktober 2026  
**Auteur:** Hermes Agent (voor Matthijs van den Berg)  
**Status:** Review / Voorstel voor Second Opinion  
**Betrokken modules:** `layer3_scheduling/space_heating_policy.py`, `models/canonical.py`, `layer2_calibration/`

---

## 1. Samenvatting & Aanleiding

In de huidige grafieken van Open HEMS (`chart-heating-forecast` en `hemsChartAnalytics`) plant de ruimteverwarming voornamelijk **relatief korte, geconcentreerde blokken met hoog stroomverbruik** (2,0 tot 3,2 kW gedurende 1,5 à 2,5 uur).

In de fysieke werkelijkheid zien we echter het tegenovergestelde:
* **Gisteravond/nacht (11–12 oktober):** De Daikin Altherma 3 H HT 18kW heeft **9,5 uur onafgebroken gemoduleerd** (van 21:00 tot 06:45 uur).
* **Rustig vermogen:** De compressor liep gestaag tussen **950 W en 1.600 W** elektrisch (gemiddeld ~1.340 W).
* **Uitstekende seizoens-COP:** Er werd **59,0 kWh thermische warmte** geleverd met slechts **12,76 kWh stroom** ($\text{COP} = 4{,}62$).
* **Grote thermische traagheid:** De vloertemperatuur steeg binnen 3 uur van 24,5 °C naar 27,2 °C, maar de luchttemperatuur in de woonkamer reageerde pas na **3,5 uur** en steeg over de hele nacht slechts met **+0,42 °C** (van 19,49 °C naar 19,91 °C).

**De centrale vraag:**  
*Hoe verhoudt de huidige wiskundige modelering zich tot de werkelijkheid, waarom plant het model korte vermogenspieken, en hoe moet het model worden gekalibreerd zodat de voorspelling representatief is voor het werkelijke gedrag?*

---

## 2. De Huidige Planningslogica (`SpaceHeatingPolicy`)

Het huidige model in `layer3_scheduling/space_heating_policy.py` is een **2R1C (Two-Resistance, One-Capacitance) thermisch netwerk**:

```
 [ Buitenlucht T_out ]
          |
     ( R_building = 1 / UA_eff )
          |
          v
  [ Binnenlucht T_room ] <-------+ ( Passieve zonne-instraling Q_solar )
          ^                      |
          |                      |
     ( R_floor_air )             |
          |                      |
  [ Betondekvloer T_floor ] -----+
          ^
          |
  [ Warmtepomp Q_th = P_el * COP ]
```

### 2.1 De Huidige Differentiële Vergelijkingen (per tijdstap $\Delta t$ = 15 min):

1. **Warmteverlies van de woning:**
   $$Q_{\text{loss}} = (\text{UA}_{\text{base}} + c_{\text{wind}} \cdot \max(0, v_{\text{wind}} - 2{,}0)) \cdot (T_{\text{room}} - T_{\text{out}})$$
   * Met $\text{UA}_{\text{base}} = 0{,}321\text{ kW/K}$ (321 W/K), $c_{\text{wind}} = 0{,}015\text{ kW/(K}\cdot\text{m/s)}$.

2. **Warmte-overdracht van vloer naar lucht:**
   $$Q_{\text{floor}\rightarrow\text{air}} = \frac{T_{\text{floor}} - T_{\text{room}}}{R_{\text{floor\_air}}}$$

3. **Temperatuurontwikkeling van de vloer:**
   $$\Delta T_{\text{floor}} = \frac{Q_{\text{th\_pomp}} - Q_{\text{floor}\rightarrow\text{air}}}{C_{\text{floor}}} \cdot \Delta t$$
   * Met $C_{\text{floor}} = 14{,}5\text{ kWh/K}$ (de betondekvloer als thermische batterij).

4. **Temperatuurontwikkeling van de kamerlucht:**
   $$\Delta T_{\text{room}} = \frac{Q_{\text{floor}\rightarrow\text{air}} + Q_{\text{solar}} - Q_{\text{loss}}}{C_{\text{air}}} \cdot \Delta t$$
   * Met $C_{\text{air}} = 3{,}2\text{ kWh/K}$.

---

## 3. Waarom het model nu korte, hoge pieken plant (De 3 Fysische Knelpunten)

Bij analyse van de code vallen drie doorslaggevende oorzaken op:

### Knelpunt A: De warmteoverdrachtsweerstand $R_{\text{floor\_air}}$ is een factor 15 te laag
* **In de code:**  
  `R_FLOOR_AIR_K_PER_KW = 0.08` K/kW (regel 36).
* **De fysische werkelijkheid:**  
  Natuurlijke convectie en straling van een verwarmde vloer naar binnenlucht bedraagt volgens de norm (NEN-EN 1264 / ISO 11855):  
  $$\alpha \approx 8{,}5\text{ tot }10{,}5\text{ W/(m}^2\cdot\text{K)}$$  
  Voor de begane grond van Matthijs ($\approx 85\text{ m}^2$) is de totale geleiding:  
  $$U_{\text{vloer}} = 85\text{ m}^2 \times 9\text{ W/(m}^2\cdot\text{K)} \approx 765\text{ W/K} = 0{,}765\text{ kW/K}$$  
  De werkelijke thermische weerstand is dus:  
  $$R_{\text{floor\_air, reëel}} = \frac{1}{0{,}765} \approx 1{,}30\text{ K/kW}$$
* **Het effect van deze fout:**  
  Met $R = 0{,}08$ veronderstelt de formule dat een temperatuurverschil van 2 °C tussen vloer en lucht leidt tot een directe warmtestroom van:  
  $$Q = \frac{2\text{ K}}{0{,}08\text{ K/kW}} = 25{,}0\text{ kW}$$  
  De model-lucht warmt hierdoor binnen **één à twee kwartieren** op naar de doeltemperatuur. De optimizer ziet dat de kamer "klaar" is en stopt de run na de minimale runlengte van 2 uur. In werkelijkheid stroomt er bij $\Delta T = 2\text{ K}$ slechts $2 / 1{,}30 \approx 1{,}5\text{ kW}$ de kamer in!

### Knelpunt B: Het opstart-boost algoritme dwingt te hoog elektrisch vermogen af
* **In de code (`calculate_modulating_power`, regels 130–133):**  
  ```python
  if run_slot_idx <= cls.STARTUP_BOOST_SLOTS:
      p_kw = min(3.2, p_steady_kw * 1.25)
  elif is_preheat:
      p_kw = min(2.8, max(p_steady_kw, 2.0))
  ```
* **De werkelijkheid:**  
  De Daikin start bij ruimteverwarming op zijn **laagste modulatiebodem (~950–1.000 W)** om rustig hydraulische flow op te bouwen. Pas als de retourtemperatuur na 1–2 uur achterblijft bij de stooklijn schaalt hij geleidelijk op naar 1.400–1.600 W.  
  Het model dwingt echter kunstmatig 2.800 W tot 3.200 W af in de eerste uren, waardoor het geplande verbruik veel te piekerig oogt.

### Knelpunt C: Uitschakeling op ruimtetemperatuur in plaats van continu stooklijngedrag
* **In de code (regels 438–440):**  
  ```python
  elif t_room >= target_room:
      is_running = False
      run_duration_slots = 0
  ```
* **De werkelijkheid:**  
  Een warmtepomp op vloerverwarming schakelt niet direct uit zodra de thermostaat 20,0 °C aantikt. Omdat de vloer traag is, moduleert de Daikin terug naar zijn ondergrens (850–950 W) en blijft hij pruttelen om het basisverlies ($Q_{\text{loss}} \approx 321\text{ W/K} \times 15\text{ K} \approx 4{,}8\text{ kW}_{\text{th}} \approx 1{,}0\text{ kW}_{\text{el}}$) continu aan te vullen.

---

## 4. Wat leert de nacht van 11 op 12 oktober ons? (Empirische Kalibratie)

De meetreeks van afgelopen nacht levert de exacte getallen op voor de second opinion:

1. **Gebouwverlies ($Q_{\text{loss}}$):**
   * Gemiddeld buitentemperatuur: $6{,}2\text{ }^\circ\text{C}$.
   * Binnentemperatuur: $19{,}5\text{ }^\circ\text{C}$ ($\Delta T = 13{,}3\text{ K}$).
   * Geleverde warmte: $59{,}0\text{ kWh}_{\text{th}}$ over 9,5 uur = **$6{,}21\text{ kW}$ gemiddeld thermisch vermogen**.
   * Dit komt overeen met een reële effectieve schilverliescoëfficiënt van:
     $$\text{UA}_{\text{eff}} = \frac{6{,}21\text{ kW}}{13{,}3\text{ K}} = 0{,}467\text{ kW/K} \quad (\approx 467\text{ W/K inclusief ventilatie/koudebruggen})$$
     *(De huidige aanname van 321 W/K onderschat het verlies bij kouder weer licht).*

2. **Thermostaat- en vloervertraging ($\tau$):**
   * Vloertemperatuur stijgt met $0{,}5\text{ tot }0{,}8\text{ }^\circ\text{C/uur}$ bij 6 kW thermische injectie.
   * Kamerluchttemperatuur reageert pas na **$3{,}5\text{ uur}$** met een stijgsnelheid van slechts **$0{,}08\text{ }^\circ\text{C/uur}$**.

3. **Modulatiebereik van de 18kW Daikin:**
   * Minimum: **$950\text{ W}$** elektrisch (bij $T_{\text{out}} \ge 8\text{ }^\circ\text{C}$).
   * Midden: **$1.200\text{ W}$** elektrisch (bij $T_{\text{out}} \approx 6\text{ }^\circ\text{C}$).
   * Hoog: **$1.600\text{ W}$** elektrisch (bij $T_{\text{out}} \le 4\text{ }^\circ\text{C}$).
   * De machine draait in CV-bedrijf vrijwel **nooit** boven de 2.000 W, tenzij er een extreme koudegolf (< -5 °C) is of legionellaboost actief is.

---

## 5. Voorstel tot Verbetering (Voor de Second Opinion)

Om het planningsmodel exact te laten aansluiten op het gedrag van de woning en de Daikin Altherma:

1. **Herstel de fysische weerstand $R_{\text{floor\_air}}$:**  
   Verhoog `R_FLOOR_AIR_K_PER_KW` van `0.08` naar **`1.25` tot `1.35` K/kW** conform de fysische vloeroppervlakte ($85\text{ m}^2$) en natuurlijke warmteoverdracht.
2. **Schrap de kunstmatige vermogenspieken:**  
   Vervang de starre boost-vermenigvuldigers door een zuiver modulerende vermogenscurve:
   $$P_{\text{el}}(T_{\text{out}}) = \max(0{,}95, \min(2{,}2, 1{,}85 - 0{,}10 \cdot T_{\text{out}}))\text{ kW}$$
3. **Continue stooklijn-vloer:**  
   Laat het model in het stookseizoen niet pendelen (aan/uit in korte blokken), maar plannen op **continue lage modulatie (950–1.400 W)**, waarbij het model alleen ingrijpt om:
   * Volledig uit te schakelen tijdens de spitsblokkade (**uit (uit, aan)**).
   * Vóór de spitsblokkade lichte pre-heat toe te passen (**soft aan (aan, uit)** of via de stooklijn).

---

## 6. Documentatie & Toegankelijkheid

Dit document is permanent vastgelegd in de repository en de draaiende add-on:
* **Bestandslocatie in repo:** `/addons/open-hems/docs/reviews/2026-10-12-ruimteverwarming-planningsmodel.md`
* **Directe URL in de draaiende container:** `http://172.30.33.6:8099/docs/reviews/2026-10-12-ruimteverwarming-planningsmodel.md`
* **GitHub commit:** Wordt gesynchroniseerd naar `main`.
