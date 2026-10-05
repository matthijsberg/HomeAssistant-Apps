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
<header class="flex justify-between items-center w-full px-3 sm:px-space-md h-12 border-b border-surface-container-highest bg-surface-container-lowest z-40 shrink-0 sticky top-0">
  <div class="flex items-center gap-2 sm:gap-space-lg min-w-0">
    <div class="flex items-center gap-2 min-w-0">
      <span class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse shrink-0"></span>
      <span class="text-sm sm:text-headline-sm font-semibold tracking-tight text-on-surface truncate">HA System 1 <span class="hidden sm:inline">// RouteTrace Console</span></span>
      <span class="hidden md:inline-block text-[10px] font-label-code-sm uppercase px-1.5 py-0.5 rounded border border-[#e5e5e4] bg-[#fafaf9] text-tertiary shrink-0">v0.1.5 • Intel Arc XPU</span>
    </div>

    <!-- View Switcher Tabs -->
    <div class="hidden sm:inline-flex p-0.5 rounded bg-surface-container border border-surface-container-highest font-label-code-sm text-[11px] shrink-0">
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

  <div class="flex items-center gap-1.5 sm:gap-space-sm shrink-0">
    <div class="hidden sm:flex items-center gap-1.5 bg-surface-container-low border border-surface-container-highest rounded px-2.5 py-1 text-label-code-sm text-secondary">
      <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
      <span class="text-secondary font-label-code-sm">Local XPU Online</span>
      <kbd class="ml-2 font-label-code-sm text-[10px] bg-surface-container-lowest px-1 rounded border border-surface-container-highest text-tertiary">Sub-50ms</kbd>
    </div>
    <span class="sm:hidden w-2 h-2 rounded-full bg-emerald-500 mr-1" title="Local XPU Online"></span>
    <!-- Gear Wheel Settings Button in Top Right -->
    <button id="gear-btn" onclick="switchView('config')" class="p-1.5 rounded hover:bg-surface-container-low transition-colors duration-150 text-secondary hover:text-primary cursor-pointer border border-transparent hover:border-surface-container-highest" title="System Settings / Flow Pipeline Configuration">
      <span class="material-symbols-outlined text-[20px]">settings</span>
    </button>
    <button onclick="syncRegistry()" class="p-1.5 rounded hover:bg-surface-container-low transition-colors duration-150 text-secondary" title="Sync Home Assistant Registry Mirror">
      <span class="material-symbols-outlined text-[18px]">sync</span>
    </button>
  </div>
</header>

<!-- Breadcrumb & Trace Context Bar -->
<div class="w-full bg-surface-container-lowest border-b border-surface-container-highest px-3 sm:px-space-md py-1.5 flex flex-wrap items-center justify-between text-label-code-sm gap-1.5">
  <div class="flex items-center gap-1.5 truncate">
    <span class="text-caption uppercase tracking-wider text-tertiary font-semibold text-[10px]">Active Topology:</span>
    <span class="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-semibold">LOCAL FIRST</span>
    <span class="text-tertiary">/</span>
    <span id="active-trace-tag" class="text-on-surface font-label-code-sm truncate">trace_live_eval</span>
  </div>
  <div class="hidden sm:flex items-center gap-3">
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
<div id="view-eval" class="flex-1 flex flex-col lg:flex-row overflow-y-auto lg:overflow-hidden min-w-0">

  <!-- LEFT/CENTER WORKSPACE: Main Trace & Evaluation Inspector -->
  <main class="w-full flex-1 p-3 sm:p-space-md lg:p-space-lg space-y-3 sm:space-y-space-md overflow-y-visible lg:overflow-y-auto min-w-0">

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
        <!-- Review Horizon: Goldfish (Stateless) vs Elephant (Contextual) -->
        <div class="mb-3 p-2 rounded bg-[#f7f7f6] border border-[#e5e5e4] flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="text-[11px] font-label-code-sm font-semibold uppercase tracking-wider text-secondary">Review Horizon:</span>
            <div class="inline-flex p-0.5 rounded bg-white border border-[#e5e5e4] text-xs font-label-code-sm">
              <button id="mode-goldfish-btn" onclick="setReviewMode('goldfish')" class="px-2.5 py-1 rounded font-semibold text-xs transition-all bg-primary text-white shadow-xs flex items-center gap-1 cursor-pointer">
                <span>🐠</span> <span>Goldfish (Stateless)</span>
              </button>
              <button id="mode-elephant-btn" onclick="setReviewMode('elephant')" class="px-2.5 py-1 rounded font-medium text-xs transition-all text-secondary hover:text-on-surface flex items-center gap-1 cursor-pointer">
                <span>🐘</span> <span>Elephant (Contextual)</span>
              </button>
            </div>
          </div>
          <div id="elephant-status-pill" class="hidden text-[11px] font-label-code-sm text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded flex items-center gap-1.5">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
            <span>Elephant Memory: <strong id="elephant-turn-count">0</strong> prior turns active</span>
            <button onclick="clearElephantContext()" class="ml-1 text-[10px] text-amber-700 hover:text-amber-900 underline cursor-pointer">Clear</button>
          </div>
        </div>

        <!-- Elephant Context Drawer (visible only in Elephant mode) -->
        <div id="elephant-context-drawer" class="hidden mb-3 p-2.5 rounded bg-[#fdfaf5] border border-amber-200 text-xs font-label-code-sm space-y-2">
          <div class="flex items-center justify-between text-amber-900 font-semibold border-b border-amber-200/60 pb-1">
            <span class="flex items-center gap-1.5"><span>🐘</span> Conversational Turn Memory (Context Buffer)</span>
            <span class="text-[10px] text-amber-700">Pronoun &amp; Anaphora binding enabled</span>
          </div>
          <div id="elephant-context-list" class="space-y-1 text-slate-700">
            <div class="text-[11px] text-secondary italic">No prior turns yet. Run a command like "zet de spots in de serre aan" to seed memory, then follow up with "zet ze op 50%".</div>
          </div>
          <div class="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-amber-200/60">
            <span class="text-[10px] text-amber-800 font-semibold uppercase">Multi-Turn Benchmarks:</span>
            <button onclick="runElephantBenchmark(1)" class="px-2 py-0.5 rounded bg-amber-100/80 hover:bg-amber-100 text-amber-900 border border-amber-300 text-[11px] cursor-pointer">
              Seq 1: Spots serre aan ➔ Zet ze op 50% ➔ Doe hem uit
            </button>
            <button onclick="runElephantBenchmark(2)" class="px-2 py-0.5 rounded bg-amber-100/80 hover:bg-amber-100 text-amber-900 border border-amber-300 text-[11px] cursor-pointer">
              Seq 2: Woonkamer lampen aan ➔ Dim hem ➔ Uit
            </button>
          </div>
        </div>

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
  <aside class="w-full lg:w-80 border-t lg:border-t-0 lg:border-l border-surface-container-highest bg-surface-container-lowest flex flex-col shrink-0">
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
<!-- VIEW 2: FLOW PIPELINE & ENGINE CONFIGURATION WORKSTATION                  -->
<!-- ========================================================================= -->
<div id="view-config" class="flex-1 overflow-y-auto bg-surface flex flex-col hidden">
<header class="flex justify-between items-center w-full px-space-md h-12 border-b border-surface-container-highest bg-surface-container-lowest z-40 sticky top-0"><div class="flex items-center gap-space-md"><button onclick="switchView('eval')" class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-surface-container cursor-pointer transition-colors text-secondary hover:text-on-surface font-label-code-sm text-label-code-sm" href="javascript:void(0)" onclick="switchView('eval')"><span class="material-symbols-outlined text-[15px]">arrow_back</span><span class="">Back to Evaluation Console</span></a><span class="text-surface-container-highest">/</span><h1 class="font-headline-sm text-headline-sm font-semibold tracking-tight text-on-surface">System 1 Flow Configuration</h1></div><div class="flex items-center gap-space-md"><div class="hidden md:flex items-center gap-2 text-label-code-sm font-label-code-sm text-secondary"><span class="flex h-2 w-2 relative"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span><span class="font-medium text-on-surface">Production Edge</span><span class="text-surface-container-highest">·</span><code class="text-tertiary">d7f8a11</code></div><button onclick="savePolicyConfig()" class="flex items-center gap-1.5 bg-primary hover:bg-primary-hover text-on-primary px-3 py-1.5 rounded text-label-code-sm font-label-code-sm font-medium transition-all shadow-sm active:scale-[0.99] cursor-pointer"><span class="material-symbols-outlined text-[15px]">bolt</span><span id="btn-deploy-policy">Deploy Policy</span></button></div></header>
<!-- Secondary Cluster Status Bar -->

<!-- Primary Configuration Workstation Shell -->
<main class="flex-1 w-full max-w-[1600px] mx-auto p-space-md lg:p-space-lg flex flex-col gap-space-lg">
<!-- Page Title & Section Switcher Pill Bar -->
<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-container-highest pb-4">
<div>
<h1 class="text-headline-lg font-headline-lg font-semibold tracking-tight text-on-surface flex items-center gap-2">
<span class="">System 1 LLM Flow Configuration</span>
<span class="text-label-code-sm font-label-code-sm text-tertiary font-normal px-2 py-0.5 rounded border border-surface-container-highest bg-surface-container-lowest">v2.4.1-rc</span>
</h1>
<p class="text-body-sm font-body-sm text-secondary mt-0.5">
          Deterministic pre-route inspection, normalization hooks, and neural confidence calibration settings for low-latency decision agents.
        </p>
</div>
<!-- Segmented Navigation Tier Selector -->
<div class="inline-flex p-1 rounded-xl bg-surface-container border border-surface-container-highest font-label-code-sm text-label-code-sm">
<a class="px-3 py-1.5 rounded-lg bg-surface-container-lowest text-on-surface font-medium shadow-xs border border-surface-container-highest flex items-center gap-1.5" href="#span-1">
<span class="w-1.5 h-1.5 rounded-full bg-primary"></span>
<span class="">Span 1: Normalization</span>
</a>
<a class="px-3 py-1.5 rounded-lg text-secondary hover:text-on-surface transition-colors flex items-center gap-1.5" href="#span-2">
<span class="w-1.5 h-1.5 rounded-full bg-surface-container-highest"></span>
<span class="">Span 2: Code Processing</span>
</a>
<a class="px-3 py-1.5 rounded-lg text-secondary hover:text-on-surface transition-colors flex items-center gap-1.5" href="#span-3">
<span class="w-1.5 h-1.5 rounded-full bg-surface-container-highest"></span>
<span class="">Span 3: Laya Engine</span>
</a>
</div>
</div>
<!-- ========================================================================= -->
<!-- SECTION 1: SPAN 1 - INPUT NORMALIZATION & CANONICALIZATION -->
<!-- ========================================================================= -->
<section class="rounded-xl border border-surface-container-highest bg-surface-container-lowest overflow-hidden shadow-xs" id="span-1">
<!-- Section Header -->
<div class="p-space-md border-b border-surface-container-highest bg-surface flex flex-wrap items-center justify-between gap-2">
<div class="flex items-center gap-2.5">
<div class="w-6 h-6 rounded bg-primary-fixed flex items-center justify-center text-primary font-label-code-sm font-bold border border-outline-variant">
            01
          </div>
<div>
<h2 class="text-headline-sm font-headline-sm font-semibold text-on-surface flex items-center gap-2">
<span class="">Span 1: Input Normalization &amp; Canonicalization</span>
<span class="text-label-code-sm font-label-code-sm text-primary font-normal bg-primary-fixed px-2 py-0.5 rounded border border-outline-variant">HOT PATH &lt; 2.0ms</span>
</h2>
<p class="text-caption font-caption text-secondary">Pre-embeddings text cleansing, script identification, and unicode folding pipeline.</p>
</div>
</div>
<div class="flex items-center gap-2">
<span class="text-label-code-sm font-label-code-sm text-secondary">Execution Target:</span>
<span class="text-label-code-sm font-label-code-sm px-2 py-0.5 rounded bg-surface-container-highest font-mono text-on-surface">C-Python / Regex 2024.11</span>
</div>
</div>
<!-- Content Split: Rule Controls + Dark Code Editor Box -->
<div class="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-surface-container-highest">
<!-- Left: Configurable Rule Toggles (5 Cols) -->
<div class="lg:col-span-5 p-space-md space-y-4">
<div class="text-label-code-sm font-label-code-sm font-semibold text-tertiary tracking-wider uppercase">Pipeline Flags &amp; Toggles</div>
<!-- Rule 1: Unicode NFKC -->
<div class="flex items-start justify-between gap-3 p-3 rounded-lg border border-surface-container-highest bg-surface hover:border-outline-variant transition-colors">
<div>
<div class="flex items-center gap-1.5">
<span class="font-medium text-body-sm text-on-surface">Unicode NFKC Canonicalization</span>
<span class="text-[10px] px-1.5 rounded bg-primary-fixed text-primary font-label-code-sm">Active</span>
</div>
<p class="text-caption font-caption text-secondary mt-1">Normalizes compatibility characters, full-width kana/digits, and decomposed diacritics into standard precomposed form.</p>
</div>
<!-- Toggle switch (active vermilion) -->
<button class="w-10 h-5 rounded-full bg-primary p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
<!-- Rule 2: Control Char & Whitespace Sanitization -->
<div class="flex items-start justify-between gap-3 p-3 rounded-lg border border-surface-container-highest bg-surface hover:border-outline-variant transition-colors">
<div>
<div class="flex items-center gap-1.5">
<span class="font-medium text-body-sm text-on-surface">Whitespace &amp; Control Character Strip</span>
<span class="text-[10px] px-1.5 rounded bg-primary-fixed text-primary font-label-code-sm">Active</span>
</div>
<p class="text-caption font-caption text-secondary mt-1">Strips ANSI escape codes, null bytes (\x00), zero-width spaces (\u200B), and folds multi-spaces into single space.</p>
</div>
<button class="w-10 h-5 rounded-full bg-primary p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
<!-- Rule 3: Language Identification & Script Routing -->
<div class="p-3 rounded-lg border border-surface-container-highest bg-surface space-y-2">
<div class="flex items-center justify-between">
<span class="font-medium text-body-sm text-on-surface">Script &amp; LID Multi-Language Routing</span>
<span class="text-caption font-caption text-primary font-medium">Built-in &lt;0.5ms Pure Py</span>
</div>
<p class="text-caption font-caption text-secondary">Resolves primary script boundary before token count estimation.</p>
<div class="grid grid-cols-2 gap-2 pt-1 font-label-code-sm text-label-code-sm">
<label class="flex items-center gap-2 p-1.5 rounded border border-surface-container-highest bg-surface-container-lowest cursor-pointer">
<input checked="" class="text-primary focus:ring-primary h-3.5 w-3.5" name="lid_backend" type="radio">
<span class="">Pure-Py Regex (&lt;0.4ms)</span>
</label>
<label class="flex items-center gap-2 p-1.5 rounded border border-surface-container-highest bg-surface-container-lowest cursor-pointer opacity-70">
<input class="text-primary focus:ring-primary h-3.5 w-3.5" name="lid_backend" type="radio">
<span class="">FastText Hook (1.8ms)</span>
</label>
</div>
<div class="flex items-center justify-between text-caption font-caption text-tertiary pt-1">
<span class="">Fallback Locale:</span>
<span class="font-mono bg-surface-container-high px-1.5 py-0.5 rounded text-on-surface">nl-NL (Dutch / Benelux)</span>
</div>
</div>
<!-- Rule 4: Stopword & Punctuation Filter Mode -->
<div class="flex items-center justify-between p-3 rounded-lg border border-surface-container-highest bg-surface">
<div>
<span class="font-medium text-body-sm text-on-surface">Punctuation &amp; Mask Token Normalizer</span>
<p class="text-caption font-caption text-secondary">Retains ModernBERT special tokens: [MASK], [SEP], [CLS]</p>
</div>
<button class="w-10 h-5 rounded-full bg-surface-container-highest p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white shadow-xs"></div>
</button>
</div>
</div>
<!-- Right: Developer Terminal Code Editor + Live Dry-Run (7 Cols) -->
<div class="lg:col-span-7 flex flex-col bg-terminal-bg">
<!-- Code Editor Top Bar -->
<div class="px-4 py-2 bg-terminal-panel border-b border-terminal-border flex items-center justify-between text-label-code-sm font-label-code-sm text-zinc-400"><div class="flex items-center gap-2 font-mono text-zinc-200 text-xs"><span class="material-symbols-outlined text-[15px] text-zinc-400">code</span><span class="font-medium text-zinc-200">span1_normalize.py</span><span class="text-zinc-500 font-sans text-xs">· hook: `normalize_input`</span></div><div class="flex items-center gap-3"><span class="text-[11px] text-zinc-400 font-mono">UTF-8 NFKC</span><button class="text-zinc-400 hover:text-zinc-100 transition-colors p-1" title="Copy hook code"><span class="material-symbols-outlined text-[15px]">content_copy</span></button></div></div>
<!-- Monospace Code Editor Area -->
<div class="p-4 font-caption text-[12px] leading-relaxed overflow-x-auto text-zinc-200 selection:bg-rose-900/60 selection:text-white">
<pre><code><span class="syn-keyword">import</span> unicodedata
<span class="syn-keyword">from</span> typing <span class="syn-keyword">import</span> Optional, Dict
<span class="syn-keyword">from</span> dataclasses <span class="syn-keyword">import</span> dataclass

<span class="syn-decorator">@dataclass(slots=True)</span>
<span class="syn-keyword">class</span> <span class="syn-type">NormalizedPayload</span>:
    text: <span class="syn-type">str</span>
    locale: <span class="syn-type">str</span>
    token_estimate: <span class="syn-type">int</span>
    has_control_chars: <span class="syn-type">bool</span> = <span class="syn-num">False</span>

<span class="syn-keyword">def</span> <span class="syn-def">normalize_input</span>(raw_text: <span class="syn-type">str</span>, metadata: <span class="syn-type">dict</span>) -&gt; <span class="syn-type">NormalizedPayload</span>:
    <span class="syn-comment"># UTF-8 NFKC canonicalization + whitespace folding (&lt;0.2ms)</span>
    sanitized = <span class="syn-str">" "</span>.join(raw_text.strip().split())
    text = unicodedata.normalize(<span class="syn-str">'NFKC'</span>, sanitized)

    <span class="syn-comment"># Fast-path regex script detection (Dutch fallback)</span>
    lang = detect_script_or_lid(text, fallback=<span class="syn-str">'nl-NL'</span>)

    <span class="syn-keyword">return</span> <span class="syn-type">NormalizedPayload</span>(
        text=text,
        locale=lang,
        token_estimate=<span class="syn-type">len</span>(text.split()),
        has_control_chars=<span class="syn-num">False</span>
    )</code></pre>
</div>
<!-- Live Interactive Dry-Run / Test Input Preview -->
<div class="mt-auto border-t border-terminal-border p-3 bg-terminal-panel">
<div class="flex items-center justify-between text-label-code-sm font-label-code-sm mb-1.5">
<span class="text-zinc-300 font-semibold flex items-center gap-1.5">
<span class="material-symbols-outlined text-[14px] text-primary">play_arrow</span>
<span class="">Live Test / Normalizer Dry-Run</span>
</span>
<div class="flex items-center gap-2">
<span class="text-emerald-400 font-mono text-[11px]">Latency: 1.2ms</span>
<span class="text-zinc-500">·</span>
<span class="text-zinc-400 font-mono text-[11px]">Tokens: 5</span>
</div>
</div>
<div class="grid grid-cols-1 md:grid-cols-2 gap-2 font-label-code-sm text-label-code-sm">
<div class="bg-black/40 rounded p-2 border border-zinc-800">
<div class="text-[10px] text-zinc-500 uppercase tracking-wider mb-1 font-mono">Raw Input Payload:</div>
<div class="text-zinc-300 font-mono text-xs">"Bereken de   annuïtaire   hypotheeklasten..."</div>
<div class="text-[10px] text-amber-400 mt-1 flex items-center gap-1">
<span class="material-symbols-outlined text-[11px]">info</span>
<span class="">Decomposed diacritic detected (\u0308)</span>
</div>
</div>
<div class="bg-black/60 rounded p-2 border border-zinc-700/80">
<div class="text-[10px] text-emerald-400 uppercase tracking-wider mb-1 font-mono">Normalized Payload Output:</div>
<div class="text-white font-mono text-xs">"Bereken de annuïtaire hypotheeklasten..."</div>
<div class="flex items-center gap-2 text-[10px] text-zinc-400 mt-1">
<span class="">locale: <strong class="text-zinc-200">nl-NL</strong></span>
<span class="">·</span>
<span class="">status: <strong class="text-emerald-400">PASSED</strong></span>
</div>
</div>
</div>
</div>
</div>
</div>
</section>
<!-- ========================================================================= -->
<!-- SECTION 2: SPAN 2 - CODE PROCESSING (FAST-PATH & GUARDRAILS) -->
<!-- ========================================================================= -->
<section class="rounded-xl border border-surface-container-highest bg-surface-container-lowest overflow-hidden shadow-xs" id="span-2">
<!-- Section Header -->
<div class="p-space-md border-b border-surface-container-highest bg-surface flex flex-wrap items-center justify-between gap-2">
<div class="flex items-center gap-2.5">
<div class="w-6 h-6 rounded bg-primary-fixed flex items-center justify-center text-primary font-label-code-sm font-bold border border-outline-variant">
            02
          </div>
<div>
<h2 class="text-headline-sm font-headline-sm font-semibold text-on-surface flex items-center gap-2">
<span class="">Span 2: Code Processing (Fast-Path Logic &amp; Deterministic Gates)</span>
<span class="text-label-code-sm font-label-code-sm text-secondary bg-surface-container-high px-2 py-0.5 rounded">TRIE / REGEX ENGINE</span>
</h2>
<p class="text-caption font-caption text-secondary">Zero-GPU deterministic execution. Intercepts frequent imperative commands in &lt;5.0ms prior to neural inference.</p>
</div>
</div>
<div class="flex items-center gap-2">
<span class="text-label-code-sm font-label-code-sm text-tertiary">Max Latency Budget:</span>
<span class="text-label-code-sm font-label-code-sm px-2 py-0.5 rounded bg-primary-fixed text-primary font-mono font-semibold border border-outline-variant">5.0 ms SLA</span>
</div>
</div>
<!-- Content Split: Rule Table & Parameters + Dark Code Editor -->
<div class="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-surface-container-highest">
<!-- Left: Rule Matrix and Latency Guard Controls (5 Cols) -->
<div class="lg:col-span-5 p-space-md space-y-4">
<div class="flex items-center justify-between">
<span class="text-label-code-sm font-label-code-sm font-semibold text-tertiary tracking-wider uppercase">Active Fast-Path Gateways</span>
<span class="text-[11px] text-secondary">3 of 3 Active</span>
</div>
<!-- Fast Path Rule Cards -->
<div class="space-y-2.5">
<!-- Rule 1: Domotica light/switch direct hook -->
<div class="p-2.5 rounded-lg border border-surface-container-highest bg-surface flex items-center justify-between">
<div class="space-y-0.5">
<div class="flex items-center gap-2">
<span class="font-medium text-body-sm text-on-surface">Domotica Light/Switch Direct Hook</span>
<span class="text-[10px] font-mono px-1 rounded bg-zinc-200 text-zinc-800">4.1ms avg</span>
</div>
<div class="text-caption font-caption text-secondary">Trie matcher for turn_on, turn_off, set_dimmer</div>
</div>
<button class="w-9 h-5 rounded-full bg-primary p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
<!-- Rule 2: Quick math calculation hook -->
<div class="p-2.5 rounded-lg border border-surface-container-highest bg-surface flex items-center justify-between">
<div class="space-y-0.5">
<div class="flex items-center gap-2">
<span class="font-medium text-body-sm text-on-surface">Quick Math Calculation Hook</span>
<span class="text-[10px] font-mono px-1 rounded bg-zinc-200 text-zinc-800">0.9ms avg</span>
</div>
<div class="text-caption font-caption text-secondary">SymPy evaluated arithmetic expressions</div>
</div>
<button class="w-9 h-5 rounded-full bg-primary p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
<!-- Rule 3: Regex triage classifier -->
<div class="p-2.5 rounded-lg border border-surface-container-highest bg-surface flex items-center justify-between">
<div class="space-y-0.5">
<div class="flex items-center gap-2">
<span class="font-medium text-body-sm text-on-surface">Regex Triage Classifier</span>
<span class="text-[10px] font-mono px-1 rounded bg-zinc-200 text-zinc-800">2.4ms avg</span>
</div>
<div class="text-caption font-caption text-secondary">Direct routing to FAQ cache for canned responses</div>
</div>
<button class="w-9 h-5 rounded-full bg-primary p-0.5 transition-colors relative shrink-0">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
</div>
<!-- Safety Gate Checklist Requirements -->
<div class="p-3 rounded-lg border border-surface-container-highest bg-surface-container-low space-y-2">
<span class="text-label-code-sm font-label-code-sm font-semibold text-on-surface block">Deterministic Safety Gate Requirements:</span>
<div class="grid grid-cols-2 gap-2 text-caption font-caption">
<div class="flex items-center gap-1.5 text-on-surface">
<span class="material-symbols-outlined text-primary text-[15px]">check_circle</span>
<span class="">Imperative Verb Root</span>
</div>
<div class="flex items-center gap-1.5 text-on-surface">
<span class="material-symbols-outlined text-primary text-[15px]">check_circle</span>
<span class="">Single Intent Verified</span>
</div>
<div class="flex items-center gap-1.5 text-on-surface">
<span class="material-symbols-outlined text-primary text-[15px]">check_circle</span>
<span class="">Non-conditional Syntax</span>
</div>
<div class="flex items-center gap-1.5 text-on-surface">
<span class="material-symbols-outlined text-primary text-[15px]">check_circle</span>
<span class="">Safe Target Whitelisted</span>
</div>
</div>
<div class="pt-1 text-[11px] text-tertiary">
              Failure on any criteria triggers immediate fall-through to <strong>Span 3: System 1 Router</strong>.
            </div>
</div>
</div>
<!-- Right: Code Editor for Fast Path Gate Logic (7 Cols) -->
<div class="lg:col-span-7 flex flex-col bg-terminal-bg">
<div class="px-4 py-2 bg-terminal-panel border-b border-terminal-border flex items-center justify-between text-label-code-sm font-label-code-sm text-zinc-400"><div class="flex items-center gap-2 font-mono text-zinc-200 text-xs"><span class="material-symbols-outlined text-[15px] text-zinc-400">code</span><span class="font-medium text-zinc-200">span2_fastpath_gate.py</span></div><div class="flex items-center gap-2"><span class="text-amber-400 font-mono text-[11px] bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/60">Deterministic FastPath</span><button class="text-zinc-400 hover:text-zinc-100 transition-colors p-1" title="Copy hook code"><span class="material-symbols-outlined text-[15px]">content_copy</span></button></div></div>
<div class="p-4 font-caption text-[12px] leading-relaxed overflow-x-auto text-zinc-200 selection:bg-rose-900/60 selection:text-white flex-1">
<pre><code><span class="syn-keyword">from</span> laya.fastpath <span class="syn-keyword">import</span> fast_path_gate, FastPathResult
<span class="syn-keyword">from</span> typing <span class="syn-keyword">import</span> Optional

<span class="syn-decorator">@fast_path_gate(max_latency_ms=5.0, strict_mode=True)</span>
<span class="syn-keyword">def</span> <span class="syn-def">evaluate_code_rules</span>(payload: <span class="syn-type">NormalizedPayload</span>) -&gt; <span class="syn-type">Optional</span>[<span class="syn-type">FastPathResult</span>]:
    <span class="syn-comment"># 1. Deterministic regex / compiled trie matching before neural pass</span>
    <span class="syn-keyword">for</span> pattern, target <span class="syn-keyword">in</span> COMPILED_DOMOTICA_RULES:
        <span class="syn-keyword">if</span> match := pattern.match(payload.text):
            <span class="syn-keyword">return</span> <span class="syn-type">FastPathResult</span>(
                gate_passed=<span class="syn-num">True</span>,
                target=target,
                confidence=<span class="syn-num">1.0</span>,
                latency_ms=<span class="syn-num">4.1</span>
            )

    <span class="syn-comment"># 2. Arithmetic / Direct Expression Hook</span>
    <span class="syn-keyword">if</span> payload.text.startswith((<span class="syn-str">"calc:"</span>, <span class="syn-str">"bereken:"</span>)):
        <span class="syn-keyword">return</span> evaluate_math_kernel(payload.text)

    <span class="syn-comment"># 3. Fall-through to System 1 Neural Classifier</span>
    <span class="syn-keyword">return</span> <span class="syn-num">None</span>  <span class="syn-comment"># Escalate to Laya Engine</span></code></pre>
</div>
<div class="p-3 bg-terminal-panel border-t border-terminal-border flex items-center justify-between text-label-code-sm font-label-code-sm">
<div class="text-zinc-400 flex items-center gap-2">
<span class="w-2 h-2 rounded-full bg-emerald-400"></span>
<span class="">Fast-Path Bypass Rate: <strong class="text-zinc-200">28.4% of total traffic</strong></span>
</div>
<div class="text-zinc-500 font-mono text-[11px]">Estimated GPU savings: ~$412 / day</div>
</div>
</div>
</div>
</section>
<!-- ========================================================================= -->
<!-- SECTION 3: SPAN 3 - SYSTEM 1 / LAYA ENGINE SETTINGS -->
<!-- ========================================================================= -->
<section class="rounded-xl border border-surface-container-highest bg-surface-container-lowest overflow-hidden shadow-xs" id="span-3">
<!-- Section Header -->
<div class="p-space-md border-b border-surface-container-highest bg-surface flex flex-wrap items-center justify-between gap-2">
<div class="flex items-center gap-2.5">
<div class="w-6 h-6 rounded bg-primary-fixed flex items-center justify-center text-primary font-label-code-sm font-bold border border-outline-variant">
            03
          </div>
<div>
<h2 class="text-headline-sm font-headline-sm font-semibold text-on-surface flex items-center gap-2">
<span class="">Span 3: System 1 / Laya Engine Settings</span>
<span class="text-label-code-sm font-label-code-sm text-on-primary bg-primary px-2 py-0.5 rounded font-mono font-medium">convaiinnovations/laya</span>
</h2>
<p class="text-caption font-caption text-secondary">Neural checkpoint architecture, resident memory management, and temperature-scaled decision primitives.</p>
</div>
</div>
<div class="flex items-center gap-3">
<span class="text-label-code-sm font-label-code-sm text-secondary">Scoring Rule:</span>
<span class="text-label-code-sm font-label-code-sm px-2 py-0.5 rounded bg-surface-container font-mono text-on-surface border border-surface-container-highest">RLCD (Spherical + Log)</span>
</div>
</div>
<!-- Main Engine Configuration Canvas -->
<div class="p-space-md space-y-6">
<!-- Part A: Checkpoint Selection Visual Model Cards -->
<div>
<div class="flex items-center justify-between mb-3">
<div>
<h3 class="text-body-sm font-body-sm font-semibold text-on-surface">Neural Checkpoint Selection</h3>
<p class="text-caption font-caption text-secondary">ModernBERT architecture optimized for calibrated masked-language decision routing.</p>
</div>
<span class="text-caption font-caption text-primary font-mono">Current resident checkpoint: convaiinnovations/laya</span>
</div>
<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
<!-- Card 1: Selected (ModernBERT-large) -->
<div class="relative rounded-lg p-3.5 border-2 border-primary bg-surface flex flex-col justify-between shadow-xs">
<div class="absolute -top-2.5 right-3 px-2 py-0.5 rounded bg-primary text-white text-[10px] font-label-code-sm font-medium tracking-wide">
                ACTIVE CHECKPOINT
              </div>
<div class="space-y-2">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-primary text-[18px]">verified</span>
<div class="font-label-code-md font-semibold text-on-surface truncate">convaiinnovations/laya</div>
</div>
<div class="text-caption font-caption text-secondary">
                  ModernBERT-large base. High-throughput English &amp; Benelux triage routing.
                </div>
<div class="flex flex-wrap gap-1.5 pt-1 text-[11px] font-mono">
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">421M params</span>
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">512 context</span>
<span class="px-1.5 py-0.5 rounded bg-primary-fixed text-primary font-semibold">18.4ms P95</span>
</div>
</div>
<div class="mt-4 pt-2 border-t border-surface-container-highest flex items-center justify-between text-caption font-caption">
<span class="text-secondary">Resident in VRAM</span>
<span class="text-primary font-medium flex items-center gap-1">
<span class="w-1.5 h-1.5 rounded-full bg-primary"></span>
                  Active Edge Node
                </span>
</div>
</div>
<!-- Card 2: Multilingual (mmBERT) -->
<div class="rounded-lg p-3.5 border border-surface-container-highest bg-surface-container-lowest hover:border-outline-variant transition-colors flex flex-col justify-between">
<div class="space-y-2">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-secondary text-[18px]">translate</span>
<div class="font-label-code-md font-semibold text-on-surface truncate">convaiinnovations/laya-multilingual</div>
</div>
<div class="text-caption font-caption text-secondary">
                  mmBERT-base. 100+ languages supported out of the box with zero-shot cross-lingual transfer.
                </div>
<div class="flex flex-wrap gap-1.5 pt-1 text-[11px] font-mono">
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">322M params</span>
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">1024-8192 ctx</span>
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">32.8ms fwd</span>
</div>
</div>
<div class="mt-4 pt-2 border-t border-surface-container-highest flex items-center justify-between text-caption font-caption">
<span class="text-secondary">Standby In Memory</span>
<button class="text-primary hover:underline font-medium">Switch to Model</button>
</div>
</div>
<!-- Card 3: Typed Decisions -->
<div class="rounded-lg p-3.5 border border-surface-container-highest bg-surface-container-lowest hover:border-outline-variant transition-colors flex flex-col justify-between">
<div class="space-y-2">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-secondary text-[18px]">schema</span>
<div class="font-label-code-md font-semibold text-on-surface truncate">convaiinnovations/laya-typed-decisions</div>
</div>
<div class="text-caption font-caption text-secondary">
                  ModernBERT-large fine-tuned on strictly typed enterprise schema workflows.
                </div>
<div class="flex flex-wrap gap-1.5 pt-1 text-[11px] font-mono">
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">421M params</span>
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">0.766 typed acc</span>
<span class="px-1.5 py-0.5 rounded bg-surface-container text-tertiary">Banking77 eval</span>
</div>
</div>
<div class="mt-4 pt-2 border-t border-surface-container-highest flex items-center justify-between text-caption font-caption">
<span class="text-secondary">Cold Storage</span>
<button class="text-primary hover:underline font-medium">Switch to Model</button>
</div>
</div>
</div>
</div>
<!-- Part B: Execution Hyperparameters & Hardware Configuration Bento -->
<div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
<!-- Hyperparameter 1: Checkpoint Resident Preloading -->
<div class="p-3.5 rounded-lg border border-surface-container-highest bg-surface space-y-3">
<div class="flex items-center justify-between">
<span class="font-medium text-body-sm text-on-surface">Checkpoint Preloading</span>
<button class="w-9 h-5 rounded-full bg-primary p-0.5 transition-colors relative">
<div class="w-4 h-4 rounded-full bg-white ml-auto shadow-xs"></div>
</button>
</div>
<div class="text-caption font-caption text-secondary">
<code class="text-primary font-mono">Router(preload=True)</code> keeps checkpoints active in resident device memory to guarantee sub-35ms cold starts.
            </div>
<div class="pt-1 flex items-center justify-between text-[11px] font-mono">
<span class="text-tertiary">Max Loaded Checkpoints:</span>
<span class="font-semibold text-on-surface bg-surface-container px-2 py-0.5 rounded">max_loaded=2</span>
</div>
</div>
<!-- Hyperparameter 2: Execution Hardware Acceleration -->
<div class="p-3.5 rounded-lg border border-surface-container-highest bg-surface space-y-2">
<div class="flex items-center justify-between">
<span class="font-medium text-body-sm text-on-surface">Execution Device</span>
<span class="text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded font-mono font-medium">ONLINE</span>
</div>
<p class="text-caption font-caption text-secondary">Kernel compute backend for tensor operations.</p>
<select class="w-full text-label-code-sm font-label-code-sm rounded border-surface-container-highest bg-surface-container-lowest focus:border-primary focus:ring-0">
<option selected="">Intel Arc iGPU (Level-Zero DRM)</option>
<option>NVIDIA CUDA (cu124 / TensorRT)</option>
<option>Apple Silicon MPS (Metal)</option>
<option>CPU (AVX-512 VNNI Vectorized)</option>
</select>
</div>
<!-- Hyperparameter 3: Option Budget (head_max_len) -->
<div class="p-3.5 rounded-lg border border-surface-container-highest bg-surface space-y-2">
<div class="flex items-center justify-between">
<span class="font-medium text-body-sm text-on-surface">Option Budget (head_max_len)</span>
<span class="font-mono text-caption text-primary font-bold">256 tok</span>
</div>
<p class="text-caption font-caption text-secondary">Max token budget for high-cardinality label space choices (e.g. Banking77).</p>
<div class="flex items-center gap-1.5 pt-1">
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-surface-container-highest bg-surface-container-lowest text-secondary hover:text-on-surface">192</button>
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-primary bg-primary-fixed text-primary font-semibold">256</button>
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-surface-container-highest bg-surface-container-lowest text-secondary hover:text-on-surface">512</button>
</div>
</div>
<!-- Hyperparameter 4: Context Window Limit (max_len) -->
<div class="p-3.5 rounded-lg border border-surface-container-highest bg-surface space-y-2">
<div class="flex items-center justify-between">
<span class="font-medium text-body-sm text-on-surface">Context Limit (max_len)</span>
<span class="text-caption font-caption text-tertiary font-mono">RoPE Rotary</span>
</div>
<p class="text-caption font-caption text-secondary">Maximum sequence length fed to ModernBERT attention.</p>
<div class="flex items-center gap-1.5 pt-1">
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-surface-container-highest bg-surface-container-lowest text-secondary">512</button>
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-primary bg-primary-fixed text-primary font-semibold">1024</button>
<button class="flex-1 py-1 rounded text-label-code-sm font-label-code-sm border border-surface-container-highest bg-surface-container-lowest text-secondary">8192</button>
</div>
</div>
</div>
<!-- Part C: Calibration & Decision Primitives (2-Col Deep Inspection) -->
<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
<!-- Calibration & Temperature Scaling -->
<div class="p-4 rounded-lg border border-surface-container-highest bg-surface space-y-3">
<div class="flex items-center justify-between">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-primary text-[18px]">tune</span>
<span class="font-medium text-body-sm text-on-surface">Temperature Scaling &amp; ECE Calibration</span>
</div>
<span class="font-label-code-sm text-label-code-sm px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono">
                ECE: 0.081 (Optimized)
              </span>
</div>
<p class="text-caption font-caption text-secondary">
              Calibrated via Platt scaling &amp; isotonic temperature optimization. Prevents overconfident routing failures on boundary ambiguities.
            </p>
<div class="space-y-3 pt-2">
<div>
<div class="flex items-center justify-between text-label-code-sm font-label-code-sm mb-1">
<span class="text-secondary font-mono">Domain Temperature:</span>
<span class="font-mono text-primary font-bold">0.20 T</span>
</div>
<input class="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg cursor-pointer" max="1.0" min="0.05" step="0.05" type="range" value="0.20">
<div class="flex justify-between text-[10px] text-tertiary font-mono mt-0.5">
<span class="">0.05 (Rigid ArgMax)</span>
<span class="">0.20 (Optimal)</span>
<span class="">1.0 (Raw Logits)</span>
</div>
</div>
<div class="p-2.5 rounded bg-surface-container-lowest border border-surface-container-highest text-caption font-caption space-y-1">
<div class="flex justify-between">
<span class="text-secondary">Expected Calibration Error (ECE):</span>
<span class="font-mono text-on-surface font-semibold">0.081 (-62% vs uncalibrated)</span>
</div>
<div class="flex justify-between">
<span class="text-secondary">Brier Score Calibration Loss:</span>
<span class="font-mono text-on-surface font-semibold">0.042</span>
</div>
</div>
</div>
</div>
<!-- Decision Primitives & Guardrail Escalation -->
<div class="p-4 rounded-lg border border-surface-container-highest bg-surface space-y-3">
<div class="flex items-center justify-between">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-primary text-[18px]">rule</span>
<span class="font-medium text-body-sm text-on-surface">Decision Primitives &amp; LLM Fallback Gate</span>
</div>
<span class="text-label-code-sm font-label-code-sm font-mono text-secondary">3 Enabled</span>
</div>
<p class="text-caption font-caption text-secondary">
              Active primitives executed over ModernBERT [MASK] token probability distributions.
            </p>
<!-- Primitives Chips -->
<div class="flex flex-wrap gap-2 pt-1">
<div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-surface-container-lowest border border-surface-container-highest text-label-code-sm font-label-code-sm">
<span class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
<code>choice</code>
<span class="text-tertiary text-[10px]">(Softmax over [MASK])</span>
</div>
<div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-surface-container-lowest border border-surface-container-highest text-label-code-sm font-label-code-sm">
<span class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
<code>noul</code>
<span class="text-tertiary text-[10px]">(Binary Yes/No)</span>
</div>
<div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-surface-container-lowest border border-surface-container-highest text-label-code-sm font-label-code-sm">
<span class="material-symbols-outlined text-emerald-600 text-[14px]">check</span>
<code>score</code>
<span class="text-tertiary text-[10px]">(Ordinal 1..5)</span>
</div>
</div>
<!-- Confidence Gate Slider -->
<div class="pt-2 border-t border-surface-container-highest space-y-2">
<div class="flex items-center justify-between text-label-code-sm font-label-code-sm">
<span class="text-on-surface font-medium">Confidence Escalation Threshold:</span>
<span class="font-mono text-primary font-bold">0.40 (40%)</span>
</div>
<input class="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg cursor-pointer" max="0.90" min="0.10" step="0.05" type="range" value="0.40">
<!-- Warning Badge as requested -->
<div class="p-2 rounded bg-amber-50 border border-amber-200 text-caption font-caption text-amber-900 flex items-start gap-1.5">
<span class="material-symbols-outlined text-[15px] text-amber-600 shrink-0 mt-0.5">warning</span>
<span class=""><strong>Note:</strong> confidence is calibrated; <code>act_probability</code> raw signal remains uncalibrated. Queries below 0.40 escalate directly to Downstream Claude 3.5 / GPT-4o.</span>
</div>
</div>
</div>
</div>
</div>
</section>
</main>
<!-- Sticky Fixed Bottom Action Footer Bar -->
<footer class="sticky bottom-0 w-full border-t border-surface-container-highest bg-surface-container-lowest px-space-md py-2.5 z-40 shadow-md">
<div class="max-w-[1600px] mx-auto flex flex-wrap items-center justify-between gap-3">
<!-- Left: Status & Modified Pills -->
<div class="flex items-center gap-3 text-label-code-sm font-label-code-sm">
<span class="w-2 h-2 rounded-full bg-amber-500 inline-block"></span>
<span class="text-on-surface font-medium">1 Parameter Modified:</span>
<code class="text-secondary bg-surface-container px-2 py-0.5 rounded">span3.ece_domain_temp = 0.20</code>
<span class="text-tertiary text-caption font-caption hidden sm:inline">· Unsaved draft buffer</span>
</div>
<!-- Right: Action Buttons Group -->
<div class="flex items-center gap-2.5 font-label-code-sm text-label-code-sm">
<button onclick="switchView('eval')" class="px-3 py-1.5 rounded border border-surface-container-highest bg-surface-container-lowest hover:bg-surface-container text-secondary hover:text-on-surface transition-colors font-medium cursor-pointer">
          Return to Trace Console
        </button>
<button class="px-3 py-1.5 rounded border border-surface-container-highest bg-surface-container-lowest hover:bg-surface-container text-on-surface transition-colors flex items-center gap-1.5 font-medium">
<span class="material-symbols-outlined text-[15px]">download</span>
<span class="">Export config.json</span>
</button>
<!-- Vermilion Primary Action Button (#e34234) -->
<button onclick="savePolicyConfig()" class="px-4 py-1.5 rounded bg-primary hover:bg-primary-hover text-on-primary font-semibold flex items-center gap-2 shadow-sm transition-all active:scale-[0.99] cursor-pointer">
<span class="material-symbols-outlined text-[16px]">cloud_upload</span>
<span class="">Save &amp; Deploy to Edge Cluster</span>
</button>
</div>
</div>
</footer>
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
