"""WebUI for HA System 1 / Laya Decision Engine Home Assistant Ingress.

Implements the official Stitch Vermilion Design System:
- View 1: Telemetry Trace & Evaluation Console (Vermilion Edition)
- View 2: System 1 Flow Pipeline & Engine Configuration
"""


def render_gui_html() -> str:
    """Generate self-contained, offline-first HTML/CSS/JS interface styled after the Stitch Vermilion Design System."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>System 1 // RouteTrace Console</title>
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin=""/>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
  <script id="tailwind-config">
    tailwind.config = {
      darkMode: "class",
      theme: {
        extend: {
          colors: {
            "primary": "#e34234",
            "primary-hover": "#cf372a",
            "primary-light": "#fdf2f1",
            "primary-border": "#f8c9c5",
            "primary-container": "#fdf2f1",
            "on-primary": "#ffffff",
            "on-primary-container": "#7a1a13",
            "surface-container-low": "#f6f6f5",
            "surface-container-high": "#e8e8e7",
            "surface-container-highest": "#e2e2e2",
            "surface-container": "#eeeeed",
            "surface-container-lowest": "#ffffff",
            "background": "#f9f9f8",
            "surface": "#f9f9f8",
            "on-surface": "#1a1c1c",
            "on-background": "#1a1c1c",
            "secondary": "#5f5e61",
            "tertiary": "#787679",
            "outline": "#8e706e",
            "outline-variant": "#f8c9c5",
            "error": "#ba1a1a",
            "error-container": "#ffdad6",
            "on-error-container": "#93000a",
            "inverse-surface": "#2f3130",
            "inverse-on-surface": "#f1f1f0"
          },
          borderRadius: {
            "DEFAULT": "0.125rem",
            "lg": "0.25rem",
            "xl": "0.5rem",
            "full": "0.75rem"
          },
          spacing: {
            "space-lg": "1.25rem",
            "margin-mobile": "1rem",
            "gutter": "1rem",
            "space-sm": "0.5rem",
            "margin": "1.5rem",
            "space-xs": "0.25rem",
            "space-xl": "2rem",
            "space-md": "0.75rem",
            "gutter-lg": "1.5rem"
          },
          fontFamily: {
            "body-lg": ["Geist", "sans-serif"],
            "label-code-sm": ["JetBrains Mono", "monospace"],
            "headline-sm": ["Geist", "sans-serif"],
            "caption": ["JetBrains Mono", "monospace"],
            "headline-xl": ["Geist", "sans-serif"],
            "label-code-md": ["JetBrains Mono", "monospace"],
            "headline-lg": ["Geist", "sans-serif"],
            "body-sm": ["Geist", "sans-serif"]
          },
          fontSize: {
            "body-lg": ["0.9375rem", { "lineHeight": "1.45rem", "letterSpacing": "-0.01em", "fontWeight": "400" }],
            "label-code-sm": ["0.6875rem", { "lineHeight": "1rem", "letterSpacing": "0.05em", "fontWeight": "500" }],
            "headline-sm": ["1.125rem", { "lineHeight": "1.5rem", "letterSpacing": "-0.015em", "fontWeight": "500" }],
            "caption": ["0.625rem", { "lineHeight": "0.875rem", "letterSpacing": "0.08em", "fontWeight": "500" }],
            "headline-xl": ["2rem", { "lineHeight": "2.5rem", "letterSpacing": "-0.025em", "fontWeight": "600" }],
            "label-code-md": ["0.8125rem", { "lineHeight": "1.25rem", "letterSpacing": "-0.01em", "fontWeight": "400" }],
            "headline-lg": ["1.5rem", { "lineHeight": "2rem", "letterSpacing": "-0.02em", "fontWeight": "600" }],
            "body-sm": ["0.8125rem", { "lineHeight": "1.25rem", "letterSpacing": "-0.005em", "fontWeight": "400" }]
          }
        }
      }
    };
  </script>
  <style>
    .material-symbols-outlined {
      font-size: 16px;
      line-height: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      vertical-align: middle;
    }
    .timeline-dotted-line {
      background-image: linear-gradient(to bottom, #d4d4d8 50%, rgba(255, 255, 255, 0) 0%);
      background-position: center;
      background-size: 1.5px 7px;
      background-repeat: repeat-y;
    }
    .chip-btn {
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      user-select: none;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .chip-btn:hover {
      transform: translateY(-1px);
    }
    /* Syntax styles for code box */
    .syn-key { color: #f43f5e; font-weight: 500; }
    .syn-str { color: #34d399; }
    .syn-num { color: #fbbf24; }
    .syn-bool { color: #60a5fa; }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #f1f1f0; }
    ::-webkit-scrollbar-thumb { background: #d4d4d8; border-radius: 3px; }
  </style>
</head>
<body class="bg-background text-on-surface antialiased font-body-sm min-h-screen flex flex-col selection:bg-primary-light selection:text-primary">

<!-- TopNavBar -->
<header class="flex justify-between items-center w-full px-space-md h-12 border-b border-surface-container-highest bg-surface-container-lowest z-40 shrink-0 sticky top-0">
  <div class="flex items-center gap-space-lg">
    <div class="flex items-center gap-2">
      <span class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse"></span>
      <span class="text-headline-sm font-headline-sm font-semibold tracking-tight text-on-surface">HA System 1 // RouteTrace Console</span>
      <span class="text-[10px] font-label-code-sm uppercase px-1.5 py-0.5 rounded border border-[#e5e5e4] bg-[#fafaf9] text-tertiary">v0.1.4 • Intel Arc XPU</span>
    </div>

    <!-- View Switcher Tabs -->
    <div class="hidden sm:inline-flex p-0.5 rounded bg-surface-container border border-surface-container-highest font-label-code-sm text-[11px]">
      <button id="tab-btn-eval" onclick="switchView('eval')" class="px-2.5 py-1 rounded bg-surface-container-lowest text-on-surface font-medium shadow-xs border border-surface-container-highest flex items-center gap-1.5 transition-all">
        <span class="w-1.5 h-1.5 rounded-full bg-primary"></span>
        <span>Trace &amp; Evaluation</span>
      </button>
      <button id="tab-btn-config" onclick="switchView('config')" class="px-2.5 py-1 rounded text-secondary hover:text-on-surface flex items-center gap-1.5 transition-all">
        <span class="w-1.5 h-1.5 rounded-full bg-tertiary"></span>
        <span>Flow Pipeline Config</span>
      </button>
    </div>
  </div>

  <div class="flex items-center gap-space-sm">
    <div class="flex items-center gap-1.5 bg-surface-container-low border border-surface-container-highest rounded px-2.5 py-1 text-label-code-sm text-secondary">
      <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
      <span class="text-secondary font-label-code-sm">Local XPU Online</span>
      <kbd class="ml-2 font-label-code-sm text-[10px] bg-surface-container-lowest px-1 rounded border border-surface-container-highest text-tertiary">Sub-50ms</kbd>
    </div>
    <button onclick="syncRegistry()" class="p-1.5 rounded hover:bg-surface-container-low transition-colors duration-150 text-secondary" title="Sync Home Assistant Registry Mirror">
      <span class="material-symbols-outlined text-[18px]">sync</span>
    </button>
  </div>
</header>

<!-- Breadcrumb & Trace Context Bar -->
<div class="w-full bg-surface-container-lowest border-b border-surface-container-highest px-space-md py-1.5 flex flex-wrap items-center justify-between text-label-code-sm gap-2">
  <div class="flex items-center gap-2">
    <span class="text-caption uppercase tracking-wider text-tertiary font-semibold">Active Topology:</span>
    <span class="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-semibold">LOCAL FIRST (HA REFLEX)</span>
    <span class="text-tertiary">/</span>
    <span id="active-trace-tag" class="text-on-surface font-label-code-sm">trace_live_eval</span>
  </div>
  <div class="flex items-center gap-3">
    <span class="inline-flex items-center gap-1.5 text-label-code-sm text-secondary">
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Hardware: <strong class="text-on-surface font-medium">Intel Arc iGPU (Level-Zero DRM)</strong>
    </span>
    <span class="text-tertiary">|</span>
    <span class="text-label-code-sm text-tertiary">Persistent Cache: <code class="text-on-surface font-label-code-sm">/data/neo_cache</code></span>
  </div>
</div>

<!-- ========================================================================= -->
<!-- VIEW 1: TRACE & EVALUATION CONSOLE (VERMILION EDITION)                    -->
<!-- ========================================================================= -->
<div id="view-eval" class="flex-1 flex overflow-hidden">

  <!-- LEFT/CENTER WORKSPACE: Main Trace & Evaluation Inspector -->
  <main class="flex-1 overflow-y-auto bg-surface p-space-md lg:p-space-lg space-y-space-md">

    <!-- Top Query & Prompt Input Box -->
    <section class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg shadow-sm overflow-hidden">
      <div class="px-space-md py-2.5 border-b border-[#e5e5e4] flex flex-wrap items-center justify-between gap-2 bg-[#fafaf9]">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-primary text-[18px]">prompt_suggestion</span>
          <span class="font-label-code-sm uppercase tracking-wider font-semibold text-on-surface text-[11px]">Evaluation Query &amp; Prompt Input (Playground)</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span id="badge-lang" class="px-2 py-0.5 rounded text-[10px] font-label-code-sm bg-surface-container-lowest border border-[#e5e5e4] text-secondary">
            Auto-detect
          </span>
          <span id="badge-tokens" class="px-2 py-0.5 rounded text-[10px] font-label-code-sm bg-surface-container-lowest border border-[#e5e5e4] text-secondary">
            0 tokens
          </span>
          <span class="px-2 py-0.5 rounded text-[10px] font-label-code-sm bg-surface-container-lowest border border-[#e5e5e4] text-secondary">
            Normalized UTF-8
          </span>
        </div>
      </div>

      <div class="p-space-md">
        <!-- Presets Ribbon -->
        <div class="mb-3 space-y-2">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[10px] font-label-code-sm uppercase tracking-wider text-emerald-700 font-semibold mr-1">🏠 HA Direct (0 Internet):</span>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('spots')">💡 Spots serre uit</button>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('house_lights')">💡 All lights in house off</button>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('living_lights')">💡 Alle lampen woonkamer aan</button>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('climate')">🌡️ Thermostaat 20.5°C</button>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('led_strip')">💡 Led strip serre uit</button>
            <button class="chip-btn bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100" onclick="loadPreset('keuken')">💡 Licht keuken aan</button>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[10px] font-label-code-sm uppercase tracking-wider text-primary font-semibold mr-1">🌐 Cloud LLM Router:</span>
            <button class="chip-btn bg-[#fdf2f1] text-primary border border-primary-border hover:bg-[#fae6e4]" onclick="loadPreset('quick')">❓ Hoofdstad van Australië (Quick)</button>
            <button class="chip-btn bg-[#fdf2f1] text-primary border border-primary-border hover:bg-[#fae6e4]" onclick="loadPreset('deep')">📊 Annuïtaire hypotheek 450k (Deep)</button>
            <button class="chip-btn bg-[#fdf2f1] text-primary border border-primary-border hover:bg-[#fae6e4]" onclick="loadPreset('code')">🐍 Python HA API script (Code)</button>
          </div>
        </div>

        <div class="relative">
          <textarea id="prompt-input" class="w-full font-label-code-md text-on-surface bg-[#fafaf9] p-3.5 rounded border border-[#e5e5e4] focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all resize-none block" rows="2" spellcheck="false" placeholder="Enter prompt or select a preset to evaluate..."></textarea>
        </div>

        <div class="mt-3 pt-3 border-t border-[#e5e5e4] flex flex-wrap items-center justify-between gap-2">
          <span id="timing-hint" class="text-caption font-label-code-sm text-secondary">Ready for live evaluation</span>
          <div class="flex items-center gap-2">
            <button id="route-btn" onclick="evaluateTurn()" class="px-4 py-1.5 text-label-code-sm font-label-code-sm rounded bg-primary hover:bg-primary-hover text-white transition-colors flex items-center gap-1.5 font-medium shadow-sm active:scale-[0.99] cursor-pointer">
              <span class="material-symbols-outlined text-[15px]">play_arrow</span>
              <span>Evaluate &amp; Trace Flow</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Active Step Focused Header & Hardware Telemetry (Span 3: System1 Processing) -->
    <section class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md space-y-space-md shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-3 pb-3 border-b border-[#e5e5e4]">
        <div>
          <div class="flex items-center gap-2">
            <span id="span-active-dot" class="inline-block w-2.5 h-2.5 rounded-full bg-primary"></span>
            <h2 id="span-title" class="text-headline-sm font-headline-sm font-semibold text-on-surface">Span 3 // System 1 Processing</h2>
            <span id="span-badge" class="px-2 py-0.5 rounded text-[11px] font-label-code-sm font-semibold bg-primary-light text-primary border border-primary-border">
              Active Step
            </span>
          </div>
          <p id="span-desc" class="text-body-sm font-body-sm text-secondary mt-1">
            High-throughput multi-intent classifier with constrained vector projection on Intel Arc XPU.
          </p>
        </div>
        <!-- Micro hardware pills -->
        <div class="flex flex-wrap items-center gap-2 text-label-code-sm">
          <div class="px-2 py-1 rounded bg-[#fafaf9] border border-[#e5e5e4]">
            <span class="text-tertiary">Device:</span> <span class="font-medium text-on-surface">Intel Arc iGPU (Level-Zero DRM)</span>
          </div>
          <div class="px-2 py-1 rounded bg-[#fafaf9] border border-[#e5e5e4]">
            <span class="text-tertiary">Latency:</span> <span id="telemetry-latency" class="font-semibold text-primary">-- ms</span>
          </div>
          <div class="px-2 py-1 rounded bg-[#fafaf9] border border-[#e5e5e4]">
            <span class="text-tertiary">Checkpoint:</span> <span id="telemetry-checkpoint" class="font-medium text-on-surface">multilingual</span>
          </div>
          <div class="px-2 py-1 rounded bg-[#fafaf9] border border-[#e5e5e4]">
            <span class="text-tertiary">Temp:</span> <span id="telemetry-temp" class="font-medium text-on-surface">0.20</span>
          </div>
        </div>
      </div>

      <!-- 3-Column Telemetry Cards -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-space-md">

        <!-- Card 1: Softmax Probability Distribution -->
        <div class="bg-[#fafaf9] border border-[#e5e5e4] rounded p-space-sm flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between pb-2 border-b border-[#e5e5e4]">
              <span class="text-caption font-caption uppercase tracking-wider text-tertiary font-medium">Softmax Matrix</span>
              <span id="matrix-top1-label" class="text-[10px] font-label-code-sm text-secondary font-semibold">TOP-1 TARGET</span>
            </div>
            <!-- Distribution Bars -->
            <div id="distribution-bars" class="space-y-2 mt-3 text-label-code-sm">
              <div>
                <div class="flex justify-between mb-1">
                  <span class="font-semibold text-primary">SMARTHOME</span>
                  <span class="font-bold text-primary">--%</span>
                </div>
                <div class="w-full bg-[#e8e8e7] h-1.5 rounded-full overflow-hidden">
                  <div class="bg-primary h-full rounded-full" style="width: 0%"></div>
                </div>
              </div>
            </div>
          </div>
          <!-- Extracted Semantic Slots -->
          <div class="mt-4 pt-2.5 border-t border-[#e5e5e4]">
            <span class="text-caption font-caption uppercase tracking-wider text-tertiary block mb-1.5">Extracted Semantic Slots</span>
            <div id="semantic-slots-container" class="flex flex-wrap gap-1">
              <span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-secondary">
                No slots extracted
              </span>
            </div>
          </div>
        </div>

        <!-- Card 2: Routing Decision & Model Parameters -->
        <div class="bg-[#fafaf9] border border-[#e5e5e4] rounded p-space-sm flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between pb-2 border-b border-[#e5e5e4]">
              <span class="text-caption font-caption uppercase tracking-wider text-tertiary font-medium">Routing Decision</span>
              <span id="badge-decision-status" class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-semibold">
                READY
              </span>
            </div>
            <div class="mt-3 space-y-2 text-label-code-sm">
              <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]/70">
                <span class="text-tertiary">Assigned Model</span>
                <span id="decision-model" class="font-semibold text-on-surface font-label-code-sm">Local HA Core</span>
              </div>
              <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]/70">
                <span class="text-tertiary">Reasoning Depth</span>
                <span id="decision-effort" class="text-on-surface font-label-code-sm">FAST REFLEX</span>
              </div>
              <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]/70">
                <span class="text-tertiary">Thinking Budget</span>
                <span id="decision-budget" class="text-on-surface font-label-code-sm">0 tokens (Direct Path)</span>
              </div>
              <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]/70">
                <span class="text-tertiary">Confidence Band</span>
                <span id="decision-confidence" class="text-on-surface font-label-code-sm">100% (Deterministic)</span>
              </div>
            </div>
          </div>
          <!-- Safety checks & Guards -->
          <div class="mt-4 pt-2.5 border-t border-[#e5e5e4]">
            <span class="text-caption font-caption uppercase tracking-wider text-tertiary block mb-1.5">Runtime Policy Guardrails</span>
            <div class="grid grid-cols-2 gap-1 text-[11px] font-label-code-sm text-secondary">
              <div class="flex items-center gap-1">
                <span id="icon-chk-imperative" class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
                <span>Imperative</span>
              </div>
              <div class="flex items-center gap-1">
                <span id="icon-chk-single" class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
                <span>Single Intent</span>
              </div>
              <div class="flex items-center gap-1">
                <span id="icon-chk-cond" class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
                <span>Non-conditional</span>
              </div>
              <div class="flex items-center gap-1">
                <span id="icon-chk-safe" class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
                <span>Safe Target</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Card 3: Action Target & Payload -->
        <div class="bg-[#fafaf9] border border-[#e5e5e4] rounded p-space-sm flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between pb-2 border-b border-[#e5e5e4]">
              <span class="text-caption font-caption uppercase tracking-wider text-tertiary font-medium">Tool / Dispatch Preview</span>
              <span id="dispatch-type-badge" class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest text-secondary border border-[#e5e5e4]">
                REST HTTP
              </span>
            </div>
            <div class="mt-3 space-y-2">
              <div class="text-label-code-sm">
                <span class="text-[10px] uppercase text-tertiary font-caption block">Endpoint / Target</span>
                <div id="dispatch-endpoint" class="font-label-code-sm font-semibold text-on-surface bg-surface-container-lowest px-2 py-1.5 rounded border border-[#e5e5e4] mt-1 truncate">
                  POST /api/services/light/turn_off
                </div>
              </div>
              <div class="text-label-code-sm mt-2">
                <span class="text-[10px] uppercase text-tertiary font-caption block">Spoken Confirmation</span>
                <div id="dispatch-speech" class="font-body-sm italic text-secondary bg-surface-container-lowest p-2 rounded border border-[#e5e5e4] mt-1">
                  "Oké, spots serre is uitgeschakeld."
                </div>
              </div>
            </div>
          </div>
          <!-- Execution status & Live Execute Button -->
          <div class="mt-4 pt-2.5 border-t border-[#e5e5e4] space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-caption font-caption uppercase tracking-wider text-tertiary">Dispatcher Result</span>
              <span id="dispatcher-status" class="inline-flex items-center gap-1 text-[11px] font-label-code-sm text-emerald-700 font-semibold">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>
                <span>Standby</span>
              </span>
            </div>
            <button id="btn-execute-live" onclick="executeCurrentTarget()" class="w-full py-1.5 px-3 rounded text-[11px] font-label-code-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white transition-colors flex items-center justify-center gap-1 shadow-xs cursor-pointer">
              <span class="material-symbols-outlined text-[14px]">bolt</span>
              <span id="btn-execute-label">Execute Live against Home Assistant Core</span>
            </button>
          </div>
        </div>

      </div>
    </section>

    <!-- Consolidated Raw JSON Telemetry Inspector -->
    <section class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg overflow-hidden shadow-sm">
      <div class="px-space-md py-2.5 border-b border-[#e5e5e4] flex items-center justify-between bg-[#fafaf9]">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-secondary text-[16px]">data_object</span>
          <span id="json-trace-filename" class="font-label-code-sm font-semibold text-on-surface">trace_payload_live.json</span>
          <span id="json-trace-size" class="text-caption text-tertiary font-caption">-- KB</span>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="copyJsonTrace()" class="px-2.5 py-1 text-label-code-sm font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-secondary hover:text-on-surface flex items-center gap-1 transition-colors cursor-pointer">
            <span class="material-symbols-outlined text-[13px]">content_copy</span>
            <span id="copy-btn-text">Copy JSON</span>
          </button>
        </div>
      </div>
      <!-- Monospace JSON display -->
      <div class="p-space-md font-label-code-sm text-[12px] leading-relaxed bg-[#18181b] text-zinc-100 overflow-x-auto selection:bg-primary/40 selection:text-white max-h-[350px]">
        <pre id="raw-json-block" class="m-0"><code class="block font-label-code-sm">{\\n  "status": "Awaiting evaluation"\\n}</code></pre>
      </div>
    </section>

  </main>

  <!-- RIGHT RAIL: Vertical Dotted Timeline Pipeline -->
  <aside class="w-72 lg:w-80 border-l border-surface-container-highest bg-surface-container-lowest flex flex-col shrink-0 overflow-y-auto">
    <div class="p-space-md border-b border-surface-container-highest flex items-center justify-between">
      <div>
        <span class="text-caption font-caption uppercase tracking-wider text-tertiary block font-medium">EXECUTION PIPELINE</span>
        <span id="pipeline-spans-count" class="text-label-code-md font-semibold text-on-surface mt-0.5 block">5 Spans Defined</span>
      </div>
      <span id="pipeline-status-badge" class="px-2 py-0.5 rounded text-[10px] font-label-code-sm bg-surface-container-low text-on-surface border border-surface-container-highest font-medium">
        STANDBY
      </span>
    </div>

    <div class="p-space-md flex-1">
      <nav aria-label="Pipeline Timeline" class="relative flex flex-col">
        <div class="absolute left-[11px] top-3 bottom-5 w-[2px] timeline-dotted-line pointer-events-none"></div>

        <!-- Overview & Consolidated Trace -->
        <div class="relative flex items-start gap-3 text-left py-2.5 group w-full">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span id="node-0" class="w-2.5 h-2.5 rounded-full bg-on-surface"></span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-medium text-on-surface truncate">Overview &amp; Trace</span>
              <span class="text-[10px] font-label-code-sm text-tertiary">All</span>
            </div>
            <p class="text-[11px] font-body-sm text-secondary truncate">Full pipeline digest &amp; latency</p>
          </div>
        </div>

        <!-- Span 1: Input Normalization -->
        <div class="relative flex items-start gap-3 text-left py-2.5 group w-full">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span id="node-1" class="w-2.5 h-2.5 rounded-full bg-on-surface"></span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-medium text-on-surface truncate">1. Input Normalization</span>
              <span id="time-span-1" class="text-[10px] font-label-code-sm text-tertiary">&lt;0.1ms</span>
            </div>
            <p class="text-[11px] font-body-sm text-secondary truncate">UTF-8 &amp; diacritic folding</p>
          </div>
        </div>

        <!-- Span 2: Code Processing (Fast Path) -->
        <div class="relative flex items-start gap-3 text-left py-2.5 group w-full">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span id="node-2" class="w-2.5 h-2.5 rounded-full bg-on-surface"></span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-medium text-on-surface truncate">2. Code Processing</span>
              <span id="time-span-2" class="text-[10px] font-label-code-sm text-tertiary">&lt;0.5ms</span>
            </div>
            <p id="desc-span-2" class="text-[11px] font-body-sm text-secondary truncate">Deterministic rules &amp; fast gate</p>
          </div>
        </div>

        <!-- Span 3: System 1 Processing (Active Step - Vermilion Concentric Ring) -->
        <div id="wrapper-span-3" class="relative flex items-start gap-3 text-left py-2.5 w-full bg-[#fdf2f1] -mx-1.5 px-1.5 rounded border border-[#f8c9c5]">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span class="relative flex h-4 w-4 items-center justify-center">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/30 opacity-75"></span>
              <span class="h-3.5 w-3.5 rounded-full border-2 border-primary bg-surface-container-lowest flex items-center justify-center shadow-sm">
                <span class="h-1.5 w-1.5 rounded-full bg-primary"></span>
              </span>
            </span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-semibold text-primary truncate">3. System1 Processing</span>
              <span id="time-span-3" class="text-[10px] font-label-code-sm font-semibold text-primary">--ms</span>
            </div>
            <p id="desc-span-3" class="text-[11px] font-body-sm text-on-surface font-medium truncate">Selected: Local HA</p>
          </div>
        </div>

        <!-- Span 4: Tool / LLM Dispatch -->
        <div class="relative flex items-start gap-3 text-left py-2.5 group w-full">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span id="node-4" class="w-3 h-3 rounded-full border-[1.5px] border-zinc-400 bg-surface-container-lowest"></span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-medium text-secondary truncate">4. Tool / LLM Dispatch</span>
              <span id="time-span-4" class="text-[10px] font-label-code-sm text-tertiary">--ms</span>
            </div>
            <p id="desc-span-4" class="text-[11px] font-body-sm text-secondary truncate">Pruned tools &amp; memory gating</p>
          </div>
        </div>

        <!-- Span 5: System Response -->
        <div class="relative flex items-start gap-3 text-left py-2.5 group w-full">
          <div class="relative z-10 w-6 flex items-center justify-center shrink-0 pt-0.5">
            <span id="node-5" class="w-3 h-3 rounded-full border-[1.5px] border-zinc-400 bg-surface-container-lowest"></span>
          </div>
          <div class="flex-1 min-w-0 pr-1">
            <div class="flex items-center justify-between">
              <span class="font-label-code-sm font-medium text-secondary truncate">5. System Response</span>
              <span id="time-span-5" class="text-[10px] font-label-code-sm text-tertiary">--ms</span>
            </div>
            <p id="desc-span-5" class="text-[11px] font-body-sm text-secondary truncate">Action execution or envelope</p>
          </div>
        </div>

      </nav>
    </div>

    <div class="p-space-sm border-t border-surface-container-highest bg-[#fafaf9] text-label-code-sm space-y-1">
      <div class="flex justify-between text-tertiary text-[11px]">
        <span>Engine Policy</span>
        <span class="text-on-surface font-label-code-sm">laya-hybrid-p95-strict</span>
      </div>
      <div class="flex justify-between text-tertiary text-[11px]">
        <span>Fast-Path Switch</span>
        <span id="telemetry-fp-switch" class="text-emerald-700 font-label-code-sm font-semibold">ENABLED</span>
      </div>
    </div>
  </aside>

</div>

<!-- ========================================================================= -->
<!-- VIEW 2: FLOW PIPELINE & ENGINE CONFIGURATION                              -->
<!-- ========================================================================= -->
<div id="view-config" class="flex-1 overflow-y-auto bg-surface p-space-md lg:p-space-lg space-y-space-md hidden">
  <div class="max-w-[1400px] mx-auto space-y-space-md">

    <!-- Title & Segmented Navigation -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-container-highest pb-4">
      <div>
        <h1 class="text-headline-lg font-headline-lg font-semibold tracking-tight text-on-surface flex items-center gap-2">
          <span>System 1 Flow Configuration</span>
          <span class="text-label-code-sm font-label-code-sm text-tertiary font-normal px-2 py-0.5 rounded border border-surface-container-highest bg-surface-container-lowest">v0.1.4</span>
        </h1>
        <p class="text-body-sm font-body-sm text-secondary mt-0.5">
          Declarative execution graph, threshold sliders, and hardware execution topology for Intel Arc iGPU.
        </p>
      </div>
    </div>

    <!-- 5 Spans Grid Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">

      <!-- Span 1 Config -->
      <div class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md shadow-sm space-y-3">
        <div class="flex items-center justify-between border-b border-[#e5e5e4] pb-2">
          <span class="font-label-code-sm font-semibold text-on-surface">Span 1 // Normalization</span>
          <span class="text-[10px] font-label-code-sm bg-emerald-50 text-emerald-800 border border-emerald-200 px-1.5 py-0.5 rounded">ACTIVE</span>
        </div>
        <p class="text-body-sm text-secondary text-xs">Diacritic folding, lowercasing, and follow-up turn context windowing.</p>
        <div class="space-y-2 text-label-code-sm text-xs">
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Diacritic Folding</span>
            <span class="font-medium text-emerald-700">Enabled (RG-04)</span>
          </div>
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Follow-up Window</span>
            <span class="font-medium">Max 2 turns (RT-04)</span>
          </div>
          <div class="flex justify-between items-center py-1">
            <span class="text-tertiary">Languages</span>
            <span class="font-medium">NL, EN (Dynamic YAML)</span>
          </div>
        </div>
      </div>

      <!-- Span 2 Config (Fast Path Switch) -->
      <div class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md shadow-sm space-y-3">
        <div class="flex items-center justify-between border-b border-[#e5e5e4] pb-2">
          <span class="font-label-code-sm font-semibold text-on-surface">Span 2 // Fast-Path Gate</span>
          <span class="text-[10px] font-label-code-sm bg-emerald-50 text-emerald-800 border border-emerald-200 px-1.5 py-0.5 rounded">CONFIGURABLE</span>
        </div>
        <p class="text-body-sm text-secondary text-xs">Sub-0.5ms deterministic rule qualification before neural execution.</p>
        <div class="space-y-2 text-label-code-sm text-xs">
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Fast-Path Gate Switch</span>
            <span class="font-semibold text-emerald-700">fast_path_enabled: true</span>
          </div>
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Domotica Threshold</span>
            <span class="font-medium">domotica_min_confidence: 0.70</span>
          </div>
          <div class="flex justify-between items-center py-1">
            <span class="text-tertiary">Safety Filters</span>
            <span class="font-medium">Lock, Alarm, Valve rejected</span>
          </div>
        </div>
      </div>

      <!-- Span 3 Config (Laya System 1) -->
      <div class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md shadow-sm space-y-3">
        <div class="flex items-center justify-between border-b border-[#e5e5e4] pb-2">
          <span class="font-label-code-sm font-semibold text-on-surface">Span 3 // Laya System 1 Router</span>
          <span class="text-[10px] font-label-code-sm bg-primary-light text-primary border border-primary-border px-1.5 py-0.5 rounded">XPU ACCELERATED</span>
        </div>
        <p class="text-body-sm text-secondary text-xs">ModernBERT &amp; mmBERT cross-encoder matrix running on Intel Arc DRM.</p>
        <div class="space-y-2 text-label-code-sm text-xs">
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Inference Device</span>
            <span class="font-semibold text-primary">Intel Arc iGPU (xpu)</span>
          </div>
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Smarthome Min Conf</span>
            <span class="font-medium">smarthome_min_confidence: 0.50</span>
          </div>
          <div class="flex justify-between items-center py-1">
            <span class="text-tertiary">Model Routing Floor</span>
            <span class="font-medium">min_confidence: 0.60</span>
          </div>
        </div>
      </div>

      <!-- Span 4 Config (Optimization) -->
      <div class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md shadow-sm space-y-3">
        <div class="flex items-center justify-between border-b border-[#e5e5e4] pb-2">
          <span class="font-label-code-sm font-semibold text-on-surface">Span 4 // Token Optimization</span>
          <span class="text-[10px] font-label-code-sm bg-blue-50 text-blue-800 border border-blue-200 px-1.5 py-0.5 rounded">ACTIVE</span>
        </div>
        <p class="text-body-sm text-secondary text-xs">Dynamic personal context memory stripping and tool list pruning.</p>
        <div class="space-y-2 text-label-code-sm text-xs">
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Memory Gating</span>
            <span class="font-medium text-emerald-700">Active (-2k chars on quick/smart)</span>
          </div>
          <div class="flex justify-between items-center py-1 border-b border-[#e5e5e4]">
            <span class="text-tertiary">Tool Pruning</span>
            <span class="font-medium">Developer tools stripped</span>
          </div>
          <div class="flex justify-between items-center py-1">
            <span class="text-tertiary">Thinking Budget</span>
            <span class="font-medium">0 on quick, high on deep</span>
          </div>
        </div>
      </div>

      <!-- Span 5 Config (Execution Targets) -->
      <div class="bg-surface-container-lowest border border-[#e5e5e4] rounded-lg p-space-md shadow-sm space-y-3 md:col-span-2">
        <div class="flex items-center justify-between border-b border-[#e5e5e4] pb-2">
          <span class="font-label-code-sm font-semibold text-on-surface">Span 5 // Dispatched Execution Topologies</span>
          <span class="text-[10px] font-label-code-sm bg-surface-container-low text-secondary border border-[#e5e5e4] px-1.5 py-0.5 rounded">MULTI-TARGET</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <div class="p-2.5 rounded border border-emerald-200 bg-emerald-50/50">
            <span class="font-semibold text-emerald-800 block">🏠 Local Target: Home Assistant Core API</span>
            <span class="text-secondary text-[11px] mt-1 block">Receives HassTurnOn/Off or direct service payloads. Executed locally over Unix socket or loopback with ZERO cloud tokens.</span>
          </div>
          <div class="p-2.5 rounded border border-purple-200 bg-purple-50/50">
            <span class="font-semibold text-purple-800 block">🌐 Upstream Target: Cloud LLM Tiering</span>
            <span class="text-secondary text-[11px] mt-1 block">Routes quick prompts to Gemini 3.5 Flash Lite, code to Gemini Flash, and deep financial reasoning to Gemini Pro.</span>
          </div>
        </div>
      </div>

    </div>

  </div>
</div>

<!-- Subtle Bottom Status Bar -->
<footer class="h-6 bg-[#fafaf9] border-t border-surface-container-highest px-space-md flex items-center justify-between text-[11px] font-label-code-sm text-tertiary shrink-0">
  <div class="flex items-center gap-4">
    <span class="flex items-center gap-1.5">
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
      <span>System 1 Engine: <strong class="text-on-surface font-medium">ONLINE</strong></span>
    </span>
    <span>Host: <strong class="text-on-surface font-medium">Intel Arc XPU (Meteor Lake)</strong></span>
    <span>Persistent Shader Cache: <strong class="text-on-surface font-medium">/data/neo_cache</strong></span>
  </div>
  <div class="flex items-center gap-4">
    <span>E2E Reflex SLA: <strong class="text-emerald-700 font-medium">&lt; 100ms</strong></span>
  </div>
</footer>

<script>
  let lastDomoticaAction = null;
  let lastModelDecision = null;
  let currentRawJson = null;

  const presets = {
    spots: "doe de spots in de serre uit",
    house_lights: "turn off all lights in the house",
    living_lights: "doe alle lampen in de woonkamer aan",
    climate: "zet de thermostaat op 20.5 graden",
    led_strip: "doe de led strip in de serre uit",
    keuken: "doe het licht in de keuken aan",
    quick: "Wat is de hoofdstad van Australië?",
    deep: "Bereken de annuïtaire hypotheeklasten voor 450k tegen 4% rente over 30 jaar",
    code: "Schrijf een Python script om entiteiten via Home Assistant REST API op te halen"
  };

  function switchView(view) {
    const vEval = document.getElementById('view-eval');
    const vConfig = document.getElementById('view-config');
    const bEval = document.getElementById('tab-btn-eval');
    const bConfig = document.getElementById('tab-btn-config');

    if (view === 'config') {
      vEval.classList.add('hidden');
      vConfig.classList.remove('hidden');
      bConfig.className = 'px-2.5 py-1 rounded bg-surface-container-lowest text-on-surface font-medium shadow-xs border border-surface-container-highest flex items-center gap-1.5 transition-all';
      bEval.className = 'px-2.5 py-1 rounded text-secondary hover:text-on-surface flex items-center gap-1.5 transition-all';
    } else {
      vConfig.classList.add('hidden');
      vEval.classList.remove('hidden');
      bEval.className = 'px-2.5 py-1 rounded bg-surface-container-lowest text-on-surface font-medium shadow-xs border border-surface-container-highest flex items-center gap-1.5 transition-all';
      bConfig.className = 'px-2.5 py-1 rounded text-secondary hover:text-on-surface flex items-center gap-1.5 transition-all';
    }
  }

  function loadPreset(key) {
    if (presets[key]) {
      document.getElementById('prompt-input').value = presets[key];
      evaluateTurn();
    }
  }

  // Keyboard shortcut Ctrl/Cmd + Enter
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      evaluateTurn();
    }
  });

  async function evaluateTurn() {
    const prompt = document.getElementById('prompt-input').value.trim();
    if (!prompt) return;

    const btn = document.getElementById('route-btn');
    const timing = document.getElementById('timing-hint');
    btn.disabled = true;
    timing.textContent = 'Tracing decision and evaluating on Intel Arc iGPU...';

    const warmupTimer = setTimeout(() => {
      timing.innerHTML = '<span style="color:#e34234;">⏳ Compiling GPU shaders on first run, please wait...</span>';
    }, 2000);

    const t0 = performance.now();
    try {
      const controller = new AbortController();
      const abortTimer = setTimeout(() => controller.abort(), 45000);

      // 1. Evaluate Fast-Path Domotica Engine
      const domoticaData = await fetch('./v1/domotica/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, execute: false }),
        signal: controller.signal
      }).then(r => r.ok ? r.json() : null).catch(() => null);

      // 2. Evaluate Model Router Engine ONLY if not already fast-path resolved to HA
      let routeData = null;
      if (!domoticaData || !domoticaData.fast_path) {
        routeData = await fetch('./v1/route', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, recent_turns: [], question_set: 'hermes-v1' }),
          signal: controller.signal
        }).then(r => r.ok ? r.json() : null).catch(() => null);
      }

      clearTimeout(abortTimer);
      clearTimeout(warmupTimer);

      const wallMs = (performance.now() - t0).toFixed(1);

      lastDomoticaAction = domoticaData;
      lastModelDecision = routeData;

      renderPipelineResults(domoticaData, routeData, wallMs);
      timing.textContent = `Evaluation complete in ${wallMs} ms`;
    } catch (e) {
      clearTimeout(warmupTimer);
      timing.textContent = 'Error: ' + e;
    } finally {
      btn.disabled = false;
    }
  }

  function renderPipelineResults(domotica, routing, wallMs) {
    const isDomotica = domotica && domotica.is_domotica;
    const isFastPath = domotica && domotica.fast_path;
    const prompt = document.getElementById('prompt-input').value.trim();

    // Top badges
    document.getElementById('badge-tokens').textContent = `${Math.ceil(prompt.length / 4)} tokens`;
    const detLang = (routing && routing.detection && routing.detection.language)
      ? (routing.detection.language === 'nl' ? 'Dutch nl-NL' : 'English en-US')
      : (domotica && domotica.raw_input ? 'Auto (NL/EN)' : 'Auto-detect');
    document.getElementById('badge-lang').textContent = detLang;

    // Telemetry micro pills
    document.getElementById('telemetry-latency').textContent = `${wallMs} ms`;
    document.getElementById('telemetry-checkpoint').textContent = (routing && routing.checkpoint) ? routing.checkpoint : 'laya-edge';
    document.getElementById('telemetry-temp').textContent = (routing && routing.temperature !== undefined) ? routing.temperature : '0.00';

    // Step 3 Header & Badges
    const spanTitle = document.getElementById('span-title');
    const spanDesc = document.getElementById('span-desc');
    const spanBadge = document.getElementById('span-badge');
    const decisionModel = document.getElementById('decision-model');
    const decisionEffort = document.getElementById('decision-effort');
    const decisionBudget = document.getElementById('decision-budget');
    const decisionConf = document.getElementById('decision-confidence');

    if (isFastPath) {
      spanTitle.textContent = "Span 2 & 3 // Home Assistant Local Reflex";
      spanDesc.textContent = "Zero-cloud edge execution: local smart home command resolved without internet latency or token costs.";
      spanBadge.textContent = "LOCAL HA DIRECT";
      spanBadge.className = "px-2 py-0.5 rounded text-[11px] font-label-code-sm font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200";

      decisionModel.textContent = "Home Assistant Core API";
      decisionEffort.textContent = "INSTANT REFLEX";
      decisionBudget.textContent = "0 tokens (Zero-Cloud)";
      decisionConf.textContent = `${Math.round((domotica.confidence || 0.99) * 100)}% (Deterministic)`;
    } else {
      const famName = routing ? routing.family.toUpperCase() : 'GENERAL';
      spanTitle.textContent = `Span 3 // System 1 Processing (${famName})`;
      spanDesc.textContent = "High-throughput neural intent classification and model calibration running on Intel Arc XPU.";
      spanBadge.textContent = famName;
      spanBadge.className = "px-2 py-0.5 rounded text-[11px] font-label-code-sm font-semibold bg-primary-light text-primary border border-primary-border";

      decisionModel.textContent = routing ? routing.model : 'gemini-3.5-flash-lite';
      decisionEffort.textContent = routing ? routing.effort.toUpperCase() : 'NORMAL';
      decisionBudget.textContent = (routing && routing.thinking_budget !== null && routing.thinking_budget !== undefined) ? `${routing.thinking_budget} tokens` : 'Standard Budget';
      decisionConf.textContent = `${Math.round(((routing ? routing.confidence.family : 0.85) * 100))}% (Neural Margin)`;
    }

    // Probability Bars
    const distContainer = document.getElementById('distribution-bars');
    distContainer.innerHTML = '';
    if (routing && routing.probabilities) {
      for (const [cand, p] of Object.entries(routing.probabilities)) {
        const pct = Math.round(p * 100);
        const isWinner = (cand === routing.family);
        const barColor = isWinner ? '#e34234' : (pct > 20 ? '#18181b' : '#787679');
        const textColor = isWinner ? 'text-primary font-bold' : 'text-secondary font-medium';
        distContainer.innerHTML += `
          <div>
            <div class="flex justify-between mb-1">
              <span class="${textColor}">${cand.toUpperCase()}${isWinner ? ' ★' : ''}</span>
              <span class="${textColor}">${pct}%</span>
            </div>
            <div class="w-full bg-[#e8e8e7] h-1.5 rounded-full overflow-hidden">
              <div class="h-full rounded-full" style="width: ${pct}%; background: ${barColor};"></div>
            </div>
          </div>`;
      }
    } else if (isFastPath) {
      distContainer.innerHTML = `
        <div>
          <div class="flex justify-between mb-1">
            <span class="text-emerald-700 font-bold">SMARTHOME (LOCAL REFLEX) ★</span>
            <span class="text-emerald-700 font-bold">100%</span>
          </div>
          <div class="w-full bg-[#e8e8e7] h-1.5 rounded-full overflow-hidden">
            <div class="bg-emerald-600 h-full rounded-full" style="width: 100%;"></div>
          </div>
        </div>`;
    }

    // Extracted Semantic Slots
    const slotsCont = document.getElementById('semantic-slots-container');
    slotsCont.innerHTML = '';
    const slots = (domotica && domotica.semantic_slots) || {};
    if (slots.room || slots.device_type || slots.scope) {
      if (slots.room) slotsCont.innerHTML += `<span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-on-surface">room: <strong>${slots.room}</strong></span>`;
      if (slots.device_type) slotsCont.innerHTML += `<span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-on-surface">device: <strong>${slots.device_type}</strong></span>`;
      if (slots.scope) slotsCont.innerHTML += `<span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-on-surface">scope: <strong>${slots.scope}</strong></span>`;
    } else if (isFastPath && domotica.target_id) {
      slotsCont.innerHTML = `<span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-emerald-50 text-emerald-800 border border-emerald-200">target: <strong>${domotica.target_id}</strong> (${domotica.target_type})</span>`;
    } else {
      slotsCont.innerHTML = '<span class="px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-surface-container-lowest border border-[#e5e5e4] text-secondary">None (Abstract Intent)</span>';
    }

    // Safety checks
    const chk = (domotica && domotica.gate_checks) || {};
    setCheckIcon('icon-chk-imperative', chk.is_imperative !== false);
    setCheckIcon('icon-chk-single', chk.is_single_intent !== false);
    setCheckIcon('icon-chk-cond', chk.no_conditions !== false);
    setCheckIcon('icon-chk-safe', chk.not_sensitive !== false);

    // Dispatcher / Endpoint preview
    const ep = document.getElementById('dispatch-endpoint');
    const speech = document.getElementById('dispatch-speech');
    const dispBadge = document.getElementById('dispatch-type-badge');
    const dispStatus = document.getElementById('dispatcher-status');
    const btnExecLabel = document.getElementById('btn-execute-label');

    if (isFastPath) {
      dispBadge.textContent = "HA REST API";
      dispBadge.className = "px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-semibold";
      ep.textContent = `POST /api/services/${domotica.domain}/${domotica.service} [target: ${domotica.target_id}]`;
      speech.textContent = domotica.speech ? `"${domotica.speech}"` : '"Action executed against Home Assistant"';
      dispStatus.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span><span>Qualified (Sub-50ms)</span>';
      btnExecLabel.textContent = "Execute Live against Home Assistant Core";
    } else {
      dispBadge.textContent = "UPSTREAM MODEL";
      dispBadge.className = "px-1.5 py-0.5 text-[10px] font-label-code-sm rounded bg-purple-50 text-purple-800 border border-purple-200 font-semibold";
      ep.textContent = `${routing ? routing.model : 'Cloud LLM'} via ${routing ? routing.provider : 'Provider'}`;
      speech.textContent = '"Standard upstream reasoning and response generation."';
      dispStatus.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-purple-600"></span><span>Routed Upstream</span>';
      btnExecLabel.textContent = "Dispatch Prompt to Upstream Model";
    }

    // Timeline rail updates
    document.getElementById('time-span-1').textContent = '<0.1ms';
    document.getElementById('time-span-2').textContent = isFastPath ? `${wallMs}ms` : 'Bypassed';
    document.getElementById('time-span-3').textContent = isFastPath ? '0ms' : `${(routing && routing.latency_ms ? routing.latency_ms.toFixed(1) : wallMs)}ms`;
    document.getElementById('time-span-4').textContent = (routing && routing.needs_memory === false) ? 'Stripped' : 'Retained';
    document.getElementById('time-span-5').textContent = isFastPath ? 'Direct HA' : (routing ? routing.model : 'Cloud');

    document.getElementById('pipeline-status-badge').textContent = `COMPLETED (${wallMs}ms)`;
    document.getElementById('pipeline-status-badge').className = "px-2 py-0.5 rounded text-[10px] font-label-code-sm bg-emerald-50 text-emerald-800 border border-emerald-200 font-semibold";

    // Raw JSON Telemetry update
    currentRawJson = {
      trace_id: "tr-" + Math.random().toString(36).substring(2, 10),
      timestamp: new Date().toISOString(),
      latency_ms: parseFloat(wallMs),
      spans: {
        input_normalization: {
          raw_text: prompt,
          normalized_text: (routing && routing.normalized_input) || prompt.trim().toLowerCase(),
          locale: detLang
        },
        code_processing: {
          fast_path_qualified: isFastPath,
          rejected_reason: domotica ? domotica.rejected_reason : null,
          target_resolved: domotica ? domotica.target_id : null
        },
        system1_processing: routing ? {
          execution_device: "intel-arc-xpu-drm",
          checkpoint: routing.checkpoint,
          latency_ms: routing.latency_ms,
          winner_family: routing.family,
          confidence: routing.confidence,
          distribution: routing.probabilities,
          slots: domotica ? domotica.semantic_slots : null
        } : null,
        tool_dispatch: {
          target: isFastPath ? `HA Core /services/${domotica.domain}/${domotica.service}` : (routing ? routing.model : "LLM"),
          speech: domotica ? domotica.speech : null,
          tool_call: domotica ? domotica.openai_tool_call : null
        }
      }
    };

    const jsonStr = JSON.stringify(currentRawJson, null, 2);
    document.getElementById('raw-json-block').innerHTML = syntaxHighlightJson(jsonStr);
    document.getElementById('json-trace-size').textContent = (jsonStr.length / 1024).toFixed(2) + " KB";
  }

  function setCheckIcon(id, passed) {
    const el = document.getElementById(id);
    if (!el) return;
    if (passed) {
      el.textContent = 'check';
      el.className = 'material-symbols-outlined text-emerald-600 text-[14px]';
    } else {
      el.textContent = 'close';
      el.className = 'material-symbols-outlined text-red-500 text-[14px]';
    }
  }

  function syntaxHighlightJson(json) {
    return json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\\\"])*"(\\s*:)?|\b(true|false|null)\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g, function (match) {
        let cls = 'syn-num';
        if (/^"/.test(match)) {
          if (/:$/.test(match)) {
            cls = 'syn-key';
          } else {
            cls = 'syn-str';
          }
        } else if (/true|false/.test(match)) {
          cls = 'syn-bool';
        } else if (/null/.test(match)) {
          cls = 'text-zinc-500';
        }
        return '<span class="' + cls + '">' + match + '</span>';
      });
  }

  function copyJsonTrace() {
    if (!currentRawJson) return;
    navigator.clipboard.writeText(JSON.stringify(currentRawJson, null, 2)).then(() => {
      const btn = document.getElementById('copy-btn-text');
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = 'Copy JSON', 2000);
    });
  }

  async function executeCurrentTarget() {
    if (!lastDomoticaAction || !lastDomoticaAction.domain || !lastDomoticaAction.service) {
      alert("No active Home Assistant target to execute.");
      return;
    }
    const btn = document.getElementById('btn-execute-live');
    const label = document.getElementById('btn-execute-label');
    const statusEl = document.getElementById('dispatcher-status');

    label.textContent = "Executing against Home Assistant Core...";
    btn.disabled = true;

    try {
      const res = await fetch('./v1/domotica/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: document.getElementById('prompt-input').value.trim(), execute: true })
      }).then(r => r.json());

      if (res && res.executed) {
        statusEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span><span class="text-emerald-700 font-bold">Executed Successfully (HTTP 200 OK)</span>';
        label.textContent = '✓ Executed Successfully';
      } else {
        statusEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-red-600"></span><span class="text-red-700 font-bold">Execution Failed</span>';
        label.textContent = 'Retry Execution';
      }
    } catch (e) {
      statusEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-red-600"></span><span class="text-red-700">Error: ' + e + '</span>';
      label.textContent = 'Error Occurred';
    } finally {
      setTimeout(() => {
        btn.disabled = false;
        label.textContent = "Execute Live against Home Assistant Core";
      }, 3000);
    }
  }

  async function syncRegistry() {
    try {
      const res = await fetch('./v1/domotica/sync', { method: 'POST' }).then(r => r.json());
      alert(`Home Assistant Entity Mirror synced! Loaded ${res.entity_count} entities.`);
    } catch (e) {
      alert("Error syncing registry: " + e);
    }
  }

  // Auto-run first preset on page load
  window.addEventListener('DOMContentLoaded', () => {
    loadPreset('spots');
  });
</script>

</body>
</html>
"""
