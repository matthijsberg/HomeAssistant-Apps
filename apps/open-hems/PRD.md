# Open HEMS — Product Requirements Document (PRD)
# Generic Residential Home Energy Management System

**Document Version:** 3.0.0  
**Status:** Approved Master Architecture  
**Scope:** Core Engine, Optimization Solvers, Hardware Invariants, OKF Knowledge Contracts & Presentation Architecture  
**Target License:** Open Source (MIT)  

---

## 1. Vision & Core Invariants

Open HEMS is a modular, device-agnostic, open-source Home Energy Management System (HEMS). It mathematically coordinates electrochemical battery storage, domestic hot water (DHW) thermal storage, underfloor space heating, rooftop solar photovoltaics (PV), dynamic electricity tariffs (EPEX Spot / day-ahead), and residential baseline loads to minimize net operational energy cost and carbon footprint while strictly guaranteeing occupant comfort and equipment longevity.

### 1.1 The Core Invariant Principles
1. **Core Autonomy (Host & Ecosystem Independent):**  
   Open HEMS is a standalone daemon. It runs natively on Linux, in Docker, or as a Home Assistant Add-on. Home Assistant is **strictly an adapter plugin** (one of many possible telemetry providers and actuation targets). If Home Assistant is restarted, upgraded, or absent, Open HEMS continues unhindered via native Modbus TCP, P1/DSMR, or MQTT connections.
2. **Device-Agnostic Dispatch Contract (Single Source of Truth):**  
   The planning engine computes a single, canonical, versioned dispatch plan (`CanonicalDispatchPlan`). Every dashboard, Lovelace card, actuator, sensor pusher, and notification consumer reads from this central plan. View layers are **strictly presentation-only** (dumb views): they never calculate power, aggregate wattages, or invent state colors.
3. **Strict Data Integrity (Zero Mock Data in Production):**  
   Production decisions, analytics, and commands are backed by real, verified telemetry. If data is stale, missing, or corrupt, the system flags it explicitly (`Quality.STALE`, `Quality.INTERPOLATED`) and falls back to deterministic safety profiles. Fabricated or simulated data is forbidden in production runtime. Development and CI rely strictly on a **Replay Harness with Golden Plan Snapshots**.
4. **Separation of Core Logic from Site Profile:**  
   The core engine contains **zero hardware-specific entity IDs, geographic coordinates, brand names, or tariff constants**. All site-specific parameters are loaded declaratively from a validated `site_config.yaml` / `site_config.json` and JSONSchema-governed device profiles.
5. **Open Knowledge Format (OKF v0.2) as Executable Domain Contract:**  
   Domain formulas, mathematical invariants, and architectural guidelines are formalized in machine-verifiable Markdown files under `knowledge/`, validated in CI via `validate.sh` and architectural guard tests (`test_okf_conformance.py`).
6. **Elephant & Goldfish Control Discipline:**  
   Hardware control adheres to strict Elephant baseline persistence (permanent recovery to normal 50.0°C setpoint, `heat` mode, and SG2 relays) coupled with Goldfish stateless per-tick evaluation (zero leaking dirty states or sticky boost temperatures between runs).
7. **Presentation Parity Invariant:**  
   All summary cards and detailed breakdown popups must exhibit 1:1 mathematical and textual parity across metrics, temporal windows, units, and signs.

---

## 2. System Architecture & Execution Loops

Open HEMS operates on a **Dual-Loop Architecture** with explicit telemetry feedback:

```
┌────────────────────────────────────────────────────────────────────────┐
│ EXTERNAL HARDWARE & PROTOCOL INTEGRATIONS (integrations/<protocol>/)   │
│ Modbus TCP │ P1 DSMR Serial/MQTT │ EnergyZero API │ Open-Meteo │ HA WS │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: UNIFIED INGESTION (integrations/<protocol>/reader.py)         │
│ Protocol-specific collectors emit raw, unvalidated telemetry streams.  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 1B: TELEMETRY SANITIZER & QUALITY ASSURANCE (sanitizer.py)       │
│ - Freshness watchdog (< 15 min TTL)                                    │
│ - Universal 15-minute grid alignment from 'Now'                        │
│ - Physical boundary clamping (rejection of impossible readings)        │
│ - Observation Nowcasting: Blends local pyranometer (Wittboy) irradiance│
│ - Emits a validated, contractual CleanTelemetryFrame                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: SELF-LEARNING & BEHAVIORAL CALIBRATION (layer2_calibration)   │
│ - 7×96 baseline quarterly load profiles (unallocated household demand) │
│ - EWMA residual tracking for adaptive drift correction                 │
│ - Thermal building parameters calibration (2R1C & Tank UA decay)       │
│ - Learns from REALIZED EFFECTIVE MODES (not unverified plan requests)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: POLICY-BASED OPTIMIZATION & SOLVERS (layer3_scheduling)       │
│ - HiGHS LP Solver: Optimal battery storage charge/discharge scheduling │
│ - Exact 2D Dynamic Programming (DP): Optimal DHW boiler buffering     │
│ - 2R1C Deficit MPC: Concrete floor space heating preheat & peak coast  │
│ - Storage Valuation Engine: Buying vs live EPEX market replacement val │
│ - Dynamic Spits Detector: Winter-capped peak lockout & soft advice     │
│ - Produces a frozen, immutable CanonicalDispatchPlan                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 3B: PLAN STORE (plan_store.py)                                   │
│ - Injected dependency (thread-safe, testable, non-singleton)           │
│ - In-memory plan cache + atomic disk snapshot + InfluxDB audit log     │
│ - In-flight run continuity guard tracking active thermal cycles        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
┌────────────────────────────────┐   ┌───────────────────────────────────┐
│ LAYER 4: ACTUATION & FEEDBACK  │   │ LAYER 5: PRESENTATION COCKPIT     │
│ (integrations/<protocol>/)     │   │ (HTTP API, Web Cockpit, Lovelace) │
│ - Goldfish / Elephant control  │   │ - 3-Tier Forecast: Finance, Energy│
│ - Physical Smart Grid relays   │   │   and Energy Storage              │
│ - Hydraulic safety interlocks  │   │ - Presentation Parity Invariant   │
│ - Reports back effective_mode  │   │ - Glassmorphic custom tooltips    │
│   and downgrade reasons        │   │ - OpenAPI & MCP Tool lockstep     │
└────────────────────────────────┘   └───────────────────────────────────┘
```

### 2.1 Macro Planning vs Micro Real-Time Control
1. **Macro Loop (15-minute resolution):**  
   Computes the global economic and thermal schedule across a rolling 24- to 48-hour horizon ($N = 96 \dots 192$ slots). Solves linear and dynamic programs, establishes authorized operational mode windows (e.g., `CHARGE_GRID`, `SPITSBLOK`, `MAX_ON`), and updates the published `CanonicalDispatchPlan`.
2. **Micro Loop (1-minute dispatch execution):**  
   Executes dispatch decisions every 60 seconds (`daemon.py`). Enforces in-flight continuity, checks real-time tank and room temperatures against shutoff thresholds, manages relay states (SG1..SG4), and asserts the Elephant baseline when idle.

### 2.2 Explicit Actuation Feedback (`effective_mode`)
Hardware actuation is physically constrained:
* Daikin Smart Grid contacts provide 4 discrete relay states: SG1 (Spitsblok / Forced Off), SG2 (Normal), SG3 (Advised On / Pre-heat), SG4 (Forced On / Boost).
* Continuous modulating commands or soft advice (`ADVISED_OFF`) must map gracefully to hardware capabilities with reported downgrade reasons.
* Actuators in Layer 4 report back `effective_mode`, `realized_power_kw`, and `downgrade_reason`. Layer 2 calibrates strictly against realized telemetry.

---

## 3. Mathematical Optimization & Physical Solvers

### 3.1 Electrochemical Battery Storage Dispatch (SciPy HiGHS LP Solver)
Battery scheduling is formulated as a Linear Program (LP) solved via `scipy.optimize.linprog(method='highs')`:

$$\min \sum_{k=0}^{N-1} \left( p_{\text{buy},k} \cdot P_{\text{ch\_grid},k} - p_{\text{sell},k} \cdot P_{\text{dis},k} + c_{\text{deg}} \cdot (P_{\text{ch},k} + P_{\text{dis},k}) \right) \Delta t$$

**Subject to physical constraints:**
1. **SoC Dynamics:**
   $$\text{SoC}_{k+1} = \text{SoC}_k + \frac{(\eta_{\text{ch}} P_{\text{ch},k} - P_{\text{dis},k} / \eta_{\text{dis}}) \Delta t}{E_{\text{nom}}}$$
2. **SoC Bounds:**
   $$\text{SoC}_{\min} \le \text{SoC}_k \le \text{SoC}_{\max} \quad (\text{default } 10\% \le \text{SoC} \le 100\%)$$
3. **Power Inverter Limits:**
   $$0 \le P_{\text{ch},k} \le P_{\text{ch\_max}}, \quad 0 \le P_{\text{dis},k} \le P_{\text{dis\_max}}$$
4. **Waterfall Residual Priority:**
   The battery operates strictly on residual household power:
   $$P_{\text{residual},k} = P_{\text{baseload},k} + P_{\text{dhw},k} + P_{\text{heating},k} - P_{\text{solar},k}$$
   The battery is forbidden from competing with or stealing solar power allocated to DHW or space heating.
5. **Economic Discharge Threshold & Trickle Protection:**
   - **Minimum Discharge Threshold (`min_discharge_threshold_w`, default 400 W):** The battery will not discharge if residual load is below 400 W to protect inverter round-trip efficiency from baseload trickling.
   - **Dynamic Economic Boost:** Direct grid arbitrage charging is triggered only when the forward price spread exceeds $€0.30/\text{kWh}$.

### 3.2 Domestic Hot Water (DHW / SWW) Exact Dynamic Programming (DP)
Detailed in ADR-004 & `layer3_scheduling/dhw_optimizer.py`:
* **State Space:** Tank temperature $T_k \in [40.0^\circ\text{C}, 60.0^\circ\text{C}]$ discretized at $\Delta T = 0.25^\circ\text{C}$, compressor status $r \in \{\text{OFF\_FREE}, \text{OFF\_DWELL}(d), \text{ON\_MANDATORY}(l), \text{ON\_FREE}\}$.
* **Objective Function:**
  $$J = \min_{u} \sum_{k=0}^{N-1} \left[ u_k P_{\text{el}}(T_k) \Delta t \cdot p_{\text{eff},k} + c_{\text{start}} \max(0, u_k - u_{k-1}) \right] - C \cdot (T_N - T_{\text{comf}}) \cdot \frac{\hat{p}}{\widehat{\text{COP}}}$$
  where $c_{\text{start}} = €0.05$, $C = 0.407\text{ kWh/K}$ (for 350L), and $T_{\text{comf}} = 40.0^\circ\text{C}$.
* **Comfort Boundary:** $T_k \ge 40.0^\circ\text{C} + m_k$, where $m_k$ is a stochastic P95 tap water deficit buffer across an 8-hour lookahead window.
* **Minimum Dwell & Run Times:** $L_{\min} = 3\text{ slots}$ (45 min), $D_{\min} = 4\text{ slots}$ (60 min).
* **Terminal Salvage Valuation:** Restwärme at horizon end is valued against the cheapest 20% future tariff window to eliminate artificial end-of-horizon depletion.

### 3.3 Space Heating & Floor Thermal Buffer Optimization (2R1C Model)
* **Thermal Model:** Second-order thermal network modeling indoor air temperature ($T_{\text{in}}$) and concrete floor mass temperature ($T_{\text{floor}}$) with floor thermal capacity $C_{\text{floor}} \approx 14.5\text{ kWh/K}$ and 3–4 hour thermal lag.
* **Deficit MPC Conditioning:** Pre-heating (`advised_on` / SG3 / +1.0°C boost) is scheduled **only if** passive building coasting without heating through the upcoming peak would drop $T_{\text{in}} < 19.9^\circ\text{C}$.
* **Microclimate GHI & Nowcasting Assimilation:** Passive solar gain ($Q_{\text{solar}} = A_{\text{effective\_glass}} \cdot \text{GHI}$) uses Global Horizontal Irradiance directly from local Ecowitt Wittboy WS90 pyranometer observations, blended into Open-Meteo NWP forecasts via continuous cosine-eased nowcasting (`ObservationNowcaster`).
* **Spits Peaking Elimination:** Space heating is locked out (SG1) during high-cost morning (07:00–09:30) and evening (17:30–21:00) spikes, coasting on concrete inertia with $< 0.5^\circ\text{C}$ temperature drop.

### 3.4 Storage Energy Valuation Engine
Computes real-time economic worth of energy stored in household buffers (`layer3_scheduling/storage_valuation.py`):
1. **DHW Boilervat (350L SWW):**
   - Minimum usable boundary: $T_{\text{min}} = \text{setpoint} - 10.0^\circ\text{C} = 40.0^\circ\text{C}$.
   - Stored thermal energy: $E_{\text{th}} = \frac{350 \cdot 1.163 \cdot \max(0, T_{\text{tank}} - 40.0)}{1000}\text{ kWh}_{\text{th}}$.
   - Electrical equivalent: $E_{\text{el}} = E_{\text{th}} / \text{COP}_{\text{dhw}} \quad (\text{COP} \approx 3.1)$.
   - Buying value: $E_{\text{el}} \cdot p_{\text{charge, dhw}}$.
   - Actual replacement value: $E_{\text{el}} \cdot p_{\text{epex, live}}$.
   - Arbitrage benefit: $\text{Value}_{\text{actual}} - \text{Value}_{\text{buy}}$.
2. **Home Battery (15 kWh LFP):**
   - Minimum usable boundary: $\text{SoC}_{\min} = 10\%$ ($1.5\text{ kWh}$).
   - Usable stored energy: $E_{\text{usable}} = 15.0 \cdot \max(0, \text{SoC} - 0.10)\text{ kWh}$.
   - Buying value: $E_{\text{usable}} \cdot p_{\text{charge, bat}}$.
   - Actual replacement value: $E_{\text{usable}} \cdot 0.90 \cdot p_{\text{epex, live}}$ (accounting for 90% discharge efficiency).
   - Arbitrage benefit: $\text{Value}_{\text{actual}} - \text{Value}_{\text{buy}}$.

---

## 4. Hardware Control & Hydraulic Invariants (Layer 4)

### 4.1 Elephant & Goldfish Control Discipline
Hardware control of the heat pump and hot water tank adheres strictly to:
* **🐘 Elephant Invariants (Immutable Baseline State):**
  - **Relay Baseline:** SG2 (Normal / Automatic: S10S = `off`, S11S = `off`).
  - **DHW Setpoint Baseline:** Exactly **`50.0 °C`**.
  - **DHW HVAC Mode Baseline:** Strictly **`heat` (AAN)**. Software is **strictly prohibited from turning the boiler `off`**.
  - **Peak Lockouts (Spits):** Enforced **strictly via hardware relays** (SG1: S10S = `off`, S11S = `on`). Thermostat entities remain in `heat` (50°C); relays break the contact at hardware level.
  - **Post-Run Restoration:** The moment a boost run ends or tank reaches target ($T_{\text{tank}} \ge T_{\text{target}} - 0.2^\circ\text{C}$), the system unconditionally returns to the Elephant baseline (SG2, 50.0°C, `heat`).
* **🐠 Goldfish Execution (Stateless Dispatch per 60s Tick):**
  - Every dispatch cycle evaluates the operational state from scratch without leaking previous dirty states.
  - If no active boost is scheduled: enforce 50.0°C setpoint and SG2 relays.
  - Inactive slots never inherit future boost temperatures (eliminates accidental autonomous night runs).

### 4.2 Hydraulic Interlocks
* **CV Master Isolation During DHW:** Whenever the heat pump runs domestic hot water heating (SG4), the central heating master switch (`switch.hc_mode_altherma_on`) is forced `off`. This prevents the 9 kW backup electric heater (BUH) from engaging simultaneously on the space heating circuit.
* **Opportunistic Run Merger:** If autonomous showering triggers heating within 2 hours of a scheduled solar boost, Open HEMS dynamically promotes the cycle to SG4 (60°C), enforces hydraulic isolation, and cancels the future planned run to save 1 compressor start cycle.

---

## 5. Generic Data Model & Schema Contracts

### 5.1 Device Modeling via Capability Sets
Devices declare orthogonal capabilities in `site_config.json`:
* `can_delay`: Appliance run can be shifted in time (e.g. Dishwasher, EV).
* `can_modulate`: Power can be continuously adjusted (e.g. Inverter, Heat Pump CV).
* `can_store`: Buffers energy (thermal kWh or electrochemical battery kWh).
* `can_export`: Can feed energy back into the house/grid (e.g. Battery).
* `has_deadline`: Must complete energy delivery before time $T$ (e.g. EV).
* `is_thermal`: Stores heat or cold; non-reversible to electricity.

### 5.2 Decoupling Presentation from Planning (`mode_catalog.json`)
The central dispatch plan (`CanonicalDispatchPlan`) carries **strictly language-neutral programmatic mode codes**:
* Thermal / Heat Pump: `forced_off`, `advised_off`, `normal`, `advised_on`, `forced_on`, `max_on`.
* Battery Inverter: `idle`, `charge_solar`, `charge_grid`, `discharge_self_consumption`, `discharge_arbitrage`, `lockout_hold`.
* EV Charger: `disconnected`, `paused`, `solar_only`, `scheduled_charge`.
Presentation text, badges, and colors are defined in `config/mode_catalog.json` and joined client-side.

### 5.3 Open Knowledge Format (OKF v0.2) Specification
All domain metrics, architectural invariants, and attested computations are stored in `knowledge/` following Google Cloud Open Knowledge Format v0.2:
* `knowledge/metrics/`: `net-costs.md`, `solar-allocation.md`, `heatpump-cop.md`, `storage-valuation.md`.
* `knowledge/architecture/`: `presentation-parity.md`, `resolution-alignment.md`, `forecast-segmentation.md`, `dhw-goldfish-elephant-control.md`, `solar-microclimate-nowcasting.md`.
* `knowledge/computations/`: `kpi-digest.md`.
* CI Enforced: `scripts/validate.sh` and `tests/architecture/test_okf_conformance.py` validate every file in build and pre-commit pipelines.

---

## 6. Frontend Presentation Architecture (Layer 5)

Detailed in `docs/PRD_CHARTING_AND_VISUALIZATION.md`:

### 6.1 Three-Tier Forecast Page Segmentation (`view-prediction`)
1. **💶 Financiën & Markttarieven (Finance):**
   - 24h/48h Cost forecast chart (`costForecastChart`).
   - Dynamic EPEX wholesale import and export tariffs (`electricityPricesChart`).
   - 4 Tariff KPIs: Lowest import, highest import, solar peak, highest export.
2. **⚡ Energie & Vermogensbalans (Energy):**
   - Optimizer dispatch advice banners (solar surplus, battery mode).
   - 24h/48h Dual-polarity stacked power waterfall (`hemsChartAnalytics`): Baseload, Solar PV, DHW, CV space heating, Battery, Net grid line.
   - 6-Box Energy metric summary (Solar, Export, Import, Produced, Consumed, Net).
3. **🔋 Energie-opslag & Thermische Buffers (Storage):**
   - Storage Valuation Top Cards (Boilervat 350L & Thuisbatterij 15 kWh): Buying value, actual EPEX replacement value, and arbitrage delta.
   - Heat pump & boiler 24h operating envelope timeline.
   - DHW boiler temperature trajectory (P05, P50, P95 bounds) and heat demand.
   - Underfloor heating 2R1C room trajectory and concrete floor buffer.
   - Home battery state-of-charge trajectory and power envelope.

### 6.2 Presentation Parity Invariant
Summary overview cards and modal detail popups must be 1:1 identical:
* Every KPI card has an associated detail modal backed by the exact same JSON payload.
* Near-zero values ($|v| < 0.05$) are sanitized to `0.0 kWh` / `€0.00` to prevent negative zero rendering (`-0.0`).

### 6.3 Universal Glassmorphic Tooltips
All charts render tooltips through `window.renderCustomTooltip`, providing rich HTML tooltips with category pills, live values, and context badges.

---

## 7. Security, Tooling & CI Governance

### 7.1 5-Stage Pre-Commit Pipeline
Every commit must pass `.git/hooks/pre-commit`:
1. **[1/5] Secret & Credential Scanner (`scripts/secret_scanner.py`):** High-entropy regex checks for API keys, bearer tokens, private keys, and passwords.
2. **[2/5] Bandit AST Security Scanner:** Static AST vulnerability analysis (`bandit -r api layer3_scheduling models -s B104,B310,B608 -ll`).
3. **[3/5] Ruff Linter & Syntax Guard:** Python code formatting and syntax verification.
4. **[4/5] Mypy Static Type Checker:** Strict type checking across API and scheduling packages.
5. **[5/5] Node.js JavaScript Syntax Guard:** AST syntax compilation of frontend modules.

### 7.2 Security Hardening & Network Hygeine
* **Safe HTTP Client (`api/http_client.py`):** Scheme whitelisting (`http`/`https` only, blocks `file://`, `gopher://`, `ftp://`). Enforces strict TLS certificate validation on WAN endpoints, while permitting LAN bridge connections for local Home Assistant instances.
* **Frontend Prototype Pollution Guards (`web/js/i18n.js`):** Recursive object mergers strictly filter out `__proto__`, `constructor`, and `prototype` keys using `Object.prototype.hasOwnProperty.call`.
* **CDN Subresource Security:** External script tags in `web/index.html` include `crossorigin="anonymous"`.
* **Container Isolation:** Explicit architectural documentation of HAOS root container privilege requirements (`Dockerfile`) to access `/data/options.json` (0600 root:root).

### 7.3 REST & MCP Lockstep Parity
Every operational capability is exposed identically across:
1. **REST API (`api/`):** `/api/model/plan`, `/api/model/storage-valuation`, `/api/schedule/chart-data`, `/api/system/status`.
2. **OpenAPI Specification (`docs/openapi.json`):** Formally typed schemas for all requests and responses.
3. **Model Context Protocol (`mcp_server.py`):** Dedicated tools (`openhems_get_plan`, `openhems_get_storage_valuation`, etc.).
4. **Architectural Guard (`tests/architecture/test_api_mcp_lockstep.py`):** Enforces 100% lockstep parity in CI.

---

## 8. Directory & File Governance

```
open-hems/
├── PRD.md                                 # Master Product Requirements Document (This document)
├── AGENTS.md                              # AI Agent & Developer Execution Rules
├── config.yaml                            # Home Assistant Add-on Metadata & Configuration
├── Dockerfile                             # Hardened Alpine/Python Container Image
├── run.sh                                 # Container entrypoint & daemon runner
├── mcp_server.py                          # Model Context Protocol Tool Server
├── api/
│   ├── context.py                         # Telemetry ingestion context builder
│   ├── energy_feed.py                     # EPEX & weather forecast client
│   ├── http_client.py                     # Hardened safe_urlopen with TLS enforcement
│   ├── routes_analytics.py                # History & KPI breakdown endpoints
│   ├── routes_forecast.py                 # Valuation & model endpoints
│   ├── routes_schedule.py                 # Live chart-data & dispatch endpoints
│   └── routes_system.py                   # Healthz, config & diagnostics endpoints
├── config/
│   ├── device_library/                    # JSONSchema-validated hardware profiles
│   ├── mode_catalog.json                  # Programmatic tokens, labels & HEX colors
│   └── site_config.json                   # Site device declarations & bounds
├── integrations/
│   ├── daikin_altherma/                   # Daikin Altherma P1P2 reader, actuator & interlocks
│   ├── deye_inverter/                     # Modbus TCP battery inverter integration
│   ├── homeassistant/                     # Sensor pusher & client bridge
│   └── p1_dsmr/                           # P1 telegram reader
├── knowledge/                             # Open Knowledge Format (OKF v0.2) Bundle
│   ├── index.md & log.md                  # Master index and revision history
│   ├── architecture/                      # Architectural invariants
│   ├── computations/                      # Attested computations
│   └── metrics/                           # Physical and financial metrics
├── layer1_data_collection/
│   ├── collector.py                       # Ingestion aggregator
│   ├── nowcasting.py                      # Local pyranometer microclimate assimilation
│   └── sanitizer.py                       # TelemetrySanitizer (freshness, bounds)
├── layer2_calibration/
│   ├── learned_forecaster.py              # 7x96 EWMA baseline profile engine
│   └── dhw_thermal_model.py               # Thermal tank UA decay model
├── layer3_scheduling/
│   ├── battery_policy.py                  # SciPy HiGHS LP Battery Optimizer
│   ├── central_planner.py                 # Master multi-device coordinator
│   ├── dhw_optimizer.py                   # Exact 2D Dynamic Programming DHW Solver
│   ├── plan_store.py                      # Thread-safe PlanStore with in-flight tracking
│   ├── space_heating_policy.py            # 2R1C Deficit MPC Space Heating Solver
│   ├── storage_valuation.py               # Buying vs live EPEX replacement value engine
│   └── tariff_provider.py                 # Dynamic tariff & net-metering formulas
├── models/
│   ├── canonical.py                       # Canonical dispatch dataclasses
│   └── physics.py                         # Physical thermodynamic equations
├── schema/
│   └── device_profile.schema.json         # JSON Schema for hardware library validation
├── scripts/
│   ├── secret_scanner.py                  # Pre-commit secret detector
│   └── validate.sh                        # OKF v0.2 conformance validator
├── tests/
│   ├── architecture/                      # AST purity, lockstep, OKF & contract tests
│   ├── fixtures/golden/                   # Golden replay datasets & plan snapshots
│   └── unit/                              # Solvers, interlocks, security & physical tests
└── web/                                   # Frontend Cockpit (HTML5, Tailwind, Chart.js)
    ├── index.html                         # 3-Tier dashboard layout
    └── js/
        ├── app.js                         # State coordinator & chart manager
        ├── i18n.js                        # Hardened locale manager (prototype pollution safe)
        └── modules/                       # Detail modals & visualizers
```
