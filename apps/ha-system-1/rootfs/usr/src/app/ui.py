"""WebUI for HA System 1 / Laya Decision Engine Home Assistant Ingress."""


def render_gui_html() -> str:
    """Generate self-contained, offline-first HTML/CSS/JS interface styled after the Stitch Design System."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HA System 1 — Decision & Domotica Fast-Path Console</title>
  <style>
    :root {
      --bg: #09090b;
      --card-bg: #121215;
      --card-sub: #18181b;
      --card-inner: #1e1e24;
      --border: #27272a;
      --border-sub: #3f3f46;
      --border-focus: #3b82f6;
      --text: #f4f4f5;
      --text-muted: #a1a1aa;
      --text-dim: #71717a;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --primary-light: rgba(59, 130, 246, 0.12);
      --success: #10b981;
      --success-light: rgba(16, 185, 129, 0.12);
      --warning: #f59e0b;
      --warning-light: rgba(245, 158, 11, 0.12);
      --purple: #8b5cf6;
      --purple-light: rgba(139, 92, 246, 0.12);
      --danger: #ef4444;
      --radius: 10px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding-bottom: 40px; min-height: 100vh; -webkit-font-smoothing: antialiased; }
    .container { max-width: 1080px; margin: 0 auto; padding: 0 16px; }

    /* Top Sticky Navigation */
    header {
      position: sticky;
      top: 0;
      z-index: 40;
      background: rgba(9, 9, 11, 0.88);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 12px 0;
      margin-bottom: 24px;
    }
    .header-inner { display: flex; justify-content: space-between; align-items: center; }
    .breadcrumbs { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; }
    .brand-title { color: #fff; font-weight: 700; display: flex; align-items: center; gap: 8px; font-size: 15px; }
    .breadcrumb-sep { color: var(--text-dim); }
    .trace-badge { font-family: monospace; font-size: 11px; background: #1f1f23; border: 1px solid var(--border); padding: 2px 7px; border-radius: 4px; color: #a1a1aa; }

    .header-badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .badge {
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 9999px;
      background: var(--card-sub);
      color: #e4e4e7;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--border);
    }
    .badge.xpu { background: var(--primary-light); color: #60a5fa; border-color: rgba(59, 130, 246, 0.3); }
    .badge.ready { background: var(--success-light); color: #34d399; border-color: rgba(16, 185, 129, 0.3); }
    .badge.provider { background: var(--purple-light); color: #c084fc; border-color: rgba(139, 92, 246, 0.3); }

    .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981; }

    /* Cards */
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
    .card-title { font-size: 13px; font-weight: 700; margin-bottom: 14px; color: #a1a1aa; text-transform: uppercase; letter-spacing: 0.6px; display: flex; justify-content: space-between; align-items: center; }

    /* Chips */
    .chips-title { font-size: 11px; color: var(--text-dim); margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
    .chip { font-size: 12px; background: var(--card-sub); border: 1px solid var(--border); color: #a1a1aa; padding: 6px 12px; border-radius: 6px; cursor: pointer; transition: all 0.15s ease; user-select: none; }
    .chip:hover { border-color: var(--primary); color: #fff; background: var(--primary-light); }

    /* Inputs */
    textarea { width: 100%; background: var(--card-sub); border: 1px solid var(--border); border-radius: 8px; padding: 14px; color: #fff; font-size: 14px; font-family: monospace; outline: none; transition: border 0.15s; min-height: 75px; resize: vertical; margin-bottom: 12px; }
    textarea:focus { border-color: var(--border-focus); }

    .context-toggle { font-size: 12px; font-weight: 600; color: var(--primary); cursor: pointer; margin-bottom: 12px; display: inline-block; user-select: none; }
    .context-panel { display: none; margin-bottom: 14px; }
    .context-panel.open { display: block; }

    .action-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
    .btn { background: var(--primary); color: #fff; border: none; padding: 9px 20px; border-radius: 7px; font-weight: 600; cursor: pointer; transition: all 0.15s; font-size: 13px; display: inline-flex; align-items: center; gap: 7px; }
    .btn:hover { background: var(--primary-hover); transform: translateY(-1px); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    .btn.execute { background: var(--success); }
    .btn.execute:hover { background: #059669; }

    /* Metric Summary Ribbon */
    .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .metric-box { background: var(--card-sub); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
    .metric-label { font-size: 10px; font-family: monospace; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.5px; }
    .metric-val { font-size: 20px; font-weight: 700; color: #fff; margin-top: 4px; font-family: monospace; }
    .metric-sub { font-size: 11px; margin-top: 4px; }

    /* Stepper Ribbon */
    .pipeline-ribbon { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 24px; }
    @media (max-width: 768px) {
      .pipeline-ribbon { grid-template-columns: 1fr; }
    }
    .ribbon-stage { background: var(--card-sub); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; cursor: pointer; transition: all 0.2s ease; display: flex; flex-direction: column; justify-content: space-between; }
    .ribbon-stage:hover { border-color: var(--border-focus); transform: translateY(-1px); }
    .ribbon-stage.active { border-color: var(--primary); background: rgba(59, 130, 246, 0.08); box-shadow: 0 0 14px rgba(59, 130, 246, 0.2); }
    .ribbon-stage.fastpath { border-color: var(--success); background: rgba(16, 185, 129, 0.08); box-shadow: 0 0 14px rgba(16, 185, 129, 0.2); }
    .ribbon-stage.bypassed { opacity: 0.45; border-style: dashed; }
    .ribbon-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .ribbon-idx { font-size: 10px; font-family: monospace; font-weight: 700; color: var(--text-dim); }
    .ribbon-time { font-size: 10px; font-family: monospace; color: #34d399; }
    .ribbon-title { font-size: 12px; font-weight: 700; color: #fff; }
    .ribbon-sub { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
    .ribbon-foot { margin-top: 8px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 10px; font-family: monospace; color: var(--text-dim); display: flex; align-items: center; gap: 5px; }

    /* Deep Trace Step Cards */
    .step-card { background: var(--card-sub); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; margin-bottom: 16px; transition: all 0.25s ease; }
    .step-card.bypassed { opacity: 0.4; filter: grayscale(0.85); background: rgba(18, 18, 21, 0.4); border-style: dashed; }
    .step-card.bypassed:hover { opacity: 0.75; filter: grayscale(0.2); }
    .step-card.bypassed .bypassed-msg { display: block; font-size: 13px; color: var(--text-muted); font-style: italic; padding: 6px 0; }
    .step-card.bypassed .step-content { display: none; }
    .step-card:not(.bypassed) .bypassed-msg { display: none; }
    .step-card:not(.bypassed) .step-content { display: block; }

    .step-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .step-title { font-size: 14px; font-weight: 700; color: #60a5fa; display: flex; align-items: center; gap: 8px; }
    .step-badge { font-size: 11px; padding: 3px 8px; border-radius: 4px; font-weight: 600; text-transform: uppercase; font-family: monospace; }

    .trace-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 13px; }
    .trace-item:last-child { border-bottom: none; }
    .trace-k { color: var(--text-muted); }
    .trace-v { font-weight: 600; color: #e2e8f0; font-family: monospace; }

    /* Probability Bar Styles */
    .prob-row { margin-bottom: 8px; }
    .prob-header { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 3px; }
    .prob-bar-bg { background: #27272a; height: 8px; border-radius: 4px; overflow: hidden; }
    .prob-bar-fill { height: 100%; transition: width 0.3s ease; }

    pre { background: #0c0c0e; padding: 14px; border-radius: 8px; font-size: 12px; overflow-x: auto; color: #cbd5e1; border: 1px solid var(--border); margin-top: 10px; line-height: 1.5; font-family: monospace; }
    details { margin-top: 14px; cursor: pointer; font-size: 13px; color: var(--text-muted); }
  </style>
</head>
<body>

<header>
  <div class="container header-inner">
    <div class="breadcrumbs">
      <div class="brand-title">⚡ HA System 1</div>
      <span class="breadcrumb-sep">/</span>
      <span style="color: var(--text-muted);">Evaluation &amp; Routing Console</span>
      <span class="breadcrumb-sep">/</span>
      <span id="trace-id-badge" class="trace-badge">#live-pass</span>
    </div>
    <div class="header-badges">
      <div id="badge-device" class="badge xpu"><span class="pulse-dot"></span> Device: Loading...</div>
      <div id="badge-latency" class="badge ready">Latency: --</div>
      <div id="badge-provider" class="badge provider">Provider: Loading...</div>
    </div>
  </div>
</header>

<div class="container">
  <!-- Query Editor Card -->
  <div class="card">
    <div class="card-title">
      <span>Decision &amp; Routing Playground</span>
      <span id="prompt-meta" style="font-size: 11px; font-family: monospace; color: var(--text-dim);">UTF-8 Normalized • Multi-Language</span>
    </div>

    <div class="chips-title">Quick Presets:</div>
    <div class="chips">
      <div class="chip" onclick="loadPreset('led_strip')">💡 Doe de led strip in de serre uit</div>
      <div class="chip" onclick="loadPreset('lights_off')">💡 Doe alle lampen in de serre uit</div>
      <div class="chip" onclick="loadPreset('en_lights')">💡 Turn off all lights in the serre</div>
      <div class="chip" onclick="loadPreset('spots')">💡 Doe de spots in de serre uit</div>
      <div class="chip" onclick="loadPreset('climate')">🌡️ Zet de thermostaat op 20.5 graden</div>
      <div class="chip" onclick="loadPreset('quick')">❓ Wat is de hoofdstad van Australië?</div>
      <div class="chip" onclick="loadPreset('deep')">📊 Bereken de annuïtaire hypotheek voor 450k</div>
    </div>

    <textarea id="prompt-input" placeholder="Enter prompt or smart home command to trace routing and observe execution..."></textarea>

    <div class="context-toggle" onclick="toggleContext()">+ Toggle Preceding Conversation History (Optional)</div>
    <div id="context-panel" class="context-panel">
      <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Context (Preceding turns):</label>
      <textarea id="context-input" style="min-height: 55px;" placeholder="user: Wil je de verwarming aanzetten?\nassistant: Zeker, welke temperatuur wens je?"></textarea>
    </div>

    <div class="action-row">
      <span id="timing-hint" style="font-size: 12px; color: var(--text-muted); font-family: monospace;">Ready for live evaluation</span>
      <div style="display: flex; gap: 10px;">
        <button id="route-btn" class="btn" onclick="evaluateTurn()">
          <span>🚀 Evaluate &amp; Trace Flow</span>
        </button>
      </div>
    </div>
  </div>

  <div id="results-area" style="display: none;">
    <!-- High-Level Metric Summary Ribbon -->
    <div class="metric-grid">
      <div class="metric-box">
        <div class="metric-label">Total Latency</div>
        <div id="metric-latency" class="metric-val">--<span style="font-size: 12px; color: var(--text-dim); margin-left: 2px;">ms</span></div>
        <div id="metric-latency-sub" class="metric-sub" style="color: #34d399;">Sub-50ms SLA met</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Decision Path</div>
        <div id="metric-path" class="metric-val" style="font-size: 16px;">Fast-Path</div>
        <div id="metric-path-sub" class="metric-sub" style="color: #60a5fa;">Zero-LLM Local API</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Confidence Score</div>
        <div id="metric-conf" class="metric-val" style="color: #60a5fa;">100%</div>
        <div id="metric-conf-sub" class="metric-sub" style="color: var(--text-dim);">Deterministic rule match</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Tokens &amp; Cost</div>
        <div id="metric-tokens" class="metric-val">0 <span style="font-size: 12px; color: var(--text-dim);">tokens</span></div>
        <div id="metric-tokens-sub" class="metric-sub" style="color: #34d399;">Zero cloud cost</div>
      </div>
    </div>

    <!-- Stepper Ribbon (Stage 01 to 05) -->
    <div class="pipeline-ribbon">
      <div id="ribbon-1" class="ribbon-stage active" onclick="scrollToStep('card-step-1')">
        <div class="ribbon-top">
          <span class="ribbon-idx">STAGE 01</span>
          <span id="ribbon-time-1" class="ribbon-time">&lt; 0.5ms</span>
        </div>
        <div class="ribbon-title">Input Normalization</div>
        <div class="ribbon-sub">Context isolation</div>
        <div class="ribbon-foot"><span class="pulse-dot" style="width: 5px; height: 5px;"></span> Deterministic pass</div>
      </div>

      <div id="ribbon-2" class="ribbon-stage" onclick="scrollToStep('card-step-2')">
        <div class="ribbon-top">
          <span class="ribbon-idx">STAGE 02</span>
          <span id="ribbon-time-2" class="ribbon-time">&lt; 1.0ms</span>
        </div>
        <div class="ribbon-title">Zero-LLM Fast Path</div>
        <div id="ribbon-sub-2" class="ribbon-sub">Safety gates &amp; target</div>
        <div id="ribbon-foot-2" class="ribbon-foot">Passed Gate</div>
      </div>

      <div id="ribbon-3" class="ribbon-stage" onclick="scrollToStep('card-step-3')">
        <div class="ribbon-top">
          <span class="ribbon-idx">STAGE 03 • NEURAL</span>
          <span id="ribbon-time-3" class="ribbon-time">--</span>
        </div>
        <div class="ribbon-title">Laya System 1</div>
        <div id="ribbon-sub-3" class="ribbon-sub">Intel Arc iGPU</div>
        <div id="ribbon-foot-3" class="ribbon-foot">XPU Matrix</div>
      </div>

      <div id="ribbon-4" class="ribbon-stage" onclick="scrollToStep('card-step-4')">
        <div class="ribbon-top">
          <span class="ribbon-idx">STAGE 04</span>
          <span id="ribbon-time-4" class="ribbon-time">0ms</span>
        </div>
        <div class="ribbon-title">Tool &amp; Memory Gate</div>
        <div id="ribbon-sub-4" class="ribbon-sub">Dynamic pruning</div>
        <div id="ribbon-foot-4" class="ribbon-foot">Token optimized</div>
      </div>

      <div id="ribbon-5" class="ribbon-stage" onclick="scrollToStep('card-step-5')">
        <div class="ribbon-top">
          <span class="ribbon-idx">STAGE 05 • FINAL</span>
          <span id="ribbon-time-5" class="ribbon-time" style="color: #60a5fa;">Ready</span>
        </div>
        <div class="ribbon-title">Action &amp; Target</div>
        <div id="ribbon-sub-5" class="ribbon-sub">Execution dispatch</div>
        <div id="ribbon-foot-5" class="ribbon-foot"><span class="pulse-dot" style="width: 5px; height: 5px;"></span> Final Destination</div>
      </div>
    </div>

    <!-- 5 Detailed Stage Cards -->
    <div id="pipeline-steps-container">
      <!-- Step 1 Card: Input Normalization -->
      <div id="card-step-1" class="step-card">
        <div class="step-header">
          <div class="step-title"><span>💬</span> Stage 1: Input Normalization &amp; Context Isolation</div>
          <span class="step-badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">Stage 1 Complete</span>
        </div>
        <div class="step-content">
          <div class="trace-item">
            <span class="trace-k">Raw User Input:</span>
            <span id="trace-raw-input" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Normalized String (UTF-8 Diacritics Folded):</span>
            <span id="trace-norm-input" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Deterministic Follow-up Detector (RT-04/05):</span>
            <span id="trace-followup-status" class="trace-v">-</span>
          </div>
        </div>
      </div>

      <!-- Step 2 Card: Fast-Path Domotica Gate -->
      <div id="card-step-2" class="step-card">
        <div class="step-header">
          <div class="step-title"><span>⚡</span> Stage 2: Fast-Path Domotica Gate (Sub-50ms Zero-LLM)</div>
          <span id="badge-step-fp" class="step-badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">Qualified</span>
        </div>
        <div id="msg-step-fp" class="bypassed-msg">Bypassed: Prompt does not represent an unambiguous smart home imperative. Escalated to Stage 3 (Laya S1).</div>
        <div class="step-content">
          <div class="trace-item">
            <span class="trace-k">Gate Qualification Status:</span>
            <span id="trace-fp-status" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Safety Gates Checklist (FP-01..18):</span>
            <span id="trace-fp-checklist" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Resolved Target Object:</span>
            <span id="trace-fp-resolved" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Resolution Latency:</span>
            <span id="trace-fp-latency" class="trace-v" style="color: #34d399;">&lt; 0.5 ms</span>
          </div>
        </div>
      </div>

      <!-- Step 3 Card: Laya System 1 Neural Router (Intel Arc iGPU) -->
      <div id="card-step-3" class="step-card">
        <div class="step-header">
          <div class="step-title"><span>🧠</span> Stage 3: Laya System 1 Neural Router (Intel Arc iGPU)</div>
          <span id="badge-step-laya" class="step-badge" style="background: rgba(139, 92, 246, 0.2); color: #c084fc;">XPU Active</span>
        </div>
        <div id="msg-step-laya" class="bypassed-msg">Bypassed — Fast-Path Domotica Gate resolved deterministically without neural model evaluation (0 cloud tokens, &lt;1ms).</div>
        <div class="step-content">
          <div class="trace-item">
            <span class="trace-k">Hardware Device:</span>
            <span id="trace-laya-hw" class="trace-v">Intel Arc iGPU (Level-Zero DRM XPU)</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Checkpoint &amp; Language Detection:</span>
            <span id="trace-laya-checkpoint" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Hardware Inference Latency:</span>
            <span id="trace-laya-latency" class="trace-v" style="color: #34d399;">-</span>
          </div>

          <div style="margin-top: 14px;">
            <div style="font-size: 11px; font-weight: 700; color: #a1a1aa; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Softmax Probability Distribution (All Candidates):</div>
            <div id="laya-prob-bars"></div>
          </div>

          <!-- Sticky Override Correction Controls -->
          <div style="margin-top: 16px; padding: 12px; background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.25); border-radius: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #93c5fd; margin-bottom: 6px;">🎯 Correct this Routing (Exact Sticky Override):</div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
              <button class="chip" onclick="submitCorrection('quick')">⚡ Quick</button>
              <button class="chip" onclick="submitCorrection('smarthome')">🏠 Smarthome</button>
              <button class="chip" onclick="submitCorrection('general')">💬 General</button>
              <button class="chip" onclick="submitCorrection('code')">🐍 Code</button>
              <button class="chip" onclick="submitCorrection('deep')">🧠 Deep</button>
            </div>
            <div id="correction-feedback" style="display: none; font-size: 12px; padding: 6px 10px; border-radius: 5px;"></div>
          </div>
        </div>
      </div>

      <!-- Step 4 Card: Optimization Gate -->
      <div id="card-step-4" class="step-card">
        <div class="step-header">
          <div class="step-title"><span>✂️</span> Stage 4: Optimization Gate (Tools &amp; Memory Gating)</div>
          <span id="badge-step-opt" class="step-badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">Optimized</span>
        </div>
        <div id="msg-step-opt" class="bypassed-msg">Bypassed — Direct Home Assistant service call requires no LLM context, tool pruning, or token optimization.</div>
        <div class="step-content">
          <div class="trace-item">
            <span class="trace-k">Smart Memory Gating:</span>
            <span id="trace-opt-mem" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Dynamic Tool Pruning:</span>
            <span id="trace-opt-tools" class="trace-v">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Thinking Budget:</span>
            <span id="trace-opt-thinking" class="trace-v">-</span>
          </div>
        </div>
      </div>

      <!-- Step 5 Card: Action Target & Execution Feedback -->
      <div id="card-step-5" class="step-card">
        <div class="step-header">
          <div class="step-title"><span>🎯</span> Stage 5: Action Target &amp; System Output</div>
          <span id="badge-step-out" class="step-badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">Dispatched</span>
        </div>
        <div class="step-content">
          <div class="trace-item">
            <span class="trace-k">Target Execution Destination:</span>
            <span id="trace-target-dest" class="trace-v" style="color: #60a5fa;">-</span>
          </div>
          <div class="trace-item">
            <span class="trace-k">Spoken Speech Confirmation:</span>
            <span id="trace-target-speech" class="trace-v" style="color: #34d399;">-</span>
          </div>

          <div style="margin-top: 14px;">
            <div style="font-size: 11px; font-weight: 700; color: #a1a1aa; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">Dispatched Wire Payload / Tool Call:</div>
            <pre id="trace-wire-payload" style="margin-top: 0;"></pre>
          </div>

          <div style="margin-top: 16px; padding: 14px; background: rgba(16, 185, 129, 0.06); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
              <span style="font-size: 13px; font-weight: 700; color: #34d399;">📡 Real-Time Execution Feedback:</span>
              <button id="btn-execute-live" class="btn execute" onclick="executeCurrentTarget()">
                <span id="btn-execute-text">⚡ Execute Live against Home Assistant Core</span>
              </button>
            </div>
            <div id="live-execution-output" style="margin-top: 12px; font-size: 13px; color: #cbd5e1; display: none;"></div>
          </div>
        </div>
      </div>

      <details open style="margin-top: 16px;">
        <summary>Raw JSON Telemetry Dump</summary>
        <pre id="json-dump"></pre>
      </details>
    </div>
  </div>
</div>

<script>
  let lastDomoticaAction = null;
  let lastModelDecision = null;

  async function loadStatus() {
    try {
      const res = await fetch('./health');
      if (res.ok) {
        const data = await res.json();
        document.getElementById('badge-device').innerHTML = '<span class="pulse-dot"></span> ' + data.device.toUpperCase() + (data.device === 'xpu' ? ' (Intel Arc iGPU)' : ' (CPU)');
        document.getElementById('badge-device').className = 'badge ' + (data.device === 'xpu' ? 'xpu' : '');
      }
      const modelRes = await fetch('./v1/models');
      if (modelRes.ok) {
        const modelData = await modelRes.json();
        document.getElementById('badge-provider').textContent = 'Provider: ' + modelData.provider.toUpperCase();
      }
    } catch (e) {
      console.error('Failed to load status:', e);
    }
  }

  function toggleContext() {
    const p = document.getElementById('context-panel');
    p.classList.toggle('open');
  }

  function scrollToStep(cardId) {
    const el = document.getElementById(cardId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  const presets = {
    led_strip: "doe de led strip in de serre uit",
    lights_off: "doe alle lampen in de serre uit",
    en_lights: "turn off all lights in the serre",
    spots: "doe de spots in de serre uit",
    climate: "zet de thermostaat op 20.5 graden",
    quick: "Wat is de hoofdstad van Australië?",
    deep: "Bereken de annuïtaire hypotheeklasten voor 450k tegen 4% rente over 30 jaar"
  };

  function loadPreset(key) {
    if (presets[key]) {
      document.getElementById('prompt-input').value = presets[key];
    }
  }

  // Keyboard shortcut Ctrl/Cmd + Enter to trigger evaluation
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

    const t0 = performance.now();
    try {
      // 1. Evaluate Fast-Path Domotica Engine
      const domoticaPromise = fetch('./v1/domotica/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, execute: false })
      }).then(r => r.ok ? r.json() : null);

      // 2. Evaluate Model Router Engine
      const routePromise = fetch('./v1/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, recent_turns: [], question_set: 'hermes-v1' })
      }).then(r => r.ok ? r.json() : null);

      const [domoticaData, routeData] = await Promise.all([domoticaPromise, routePromise]);
      const wallMs = (performance.now() - t0).toFixed(1);

      lastDomoticaAction = domoticaData;
      lastModelDecision = routeData;

      renderPipelineResults(domoticaData, routeData, wallMs);
      timing.textContent = `Evaluation complete in ${wallMs} ms`;
      document.getElementById('badge-latency').textContent = `Latency: ${wallMs}ms`;
    } catch (e) {
      alert('Error evaluating turn: ' + e);
      timing.textContent = 'Error occurred';
    } finally {
      btn.disabled = false;
    }
  }

  function renderPipelineResults(domotica, routing, wallMs) {
    document.getElementById('results-area').style.display = 'block';

    const isDomotica = domotica && domotica.is_domotica;
    const isFastPath = domotica && domotica.fast_path;

    // Reset execution feedback
    document.getElementById('live-execution-output').style.display = 'none';

    // Summary Metric updates
    document.getElementById('metric-latency').innerHTML = `${wallMs}<span style="font-size: 12px; color: var(--text-dim); margin-left: 2px;">ms</span>`;
    document.getElementById('metric-latency-sub').textContent = wallMs < 50 ? 'Sub-50ms SLA met' : (wallMs < 150 ? 'Edge XPU SLA met' : 'Completed');
    document.getElementById('metric-latency-sub').style.color = wallMs < 150 ? '#34d399' : '#f59e0b';

    // Ribbons & Cards
    const r1 = document.getElementById('ribbon-1');
    const r2 = document.getElementById('ribbon-2');
    const r3 = document.getElementById('ribbon-3');
    const r4 = document.getElementById('ribbon-4');
    const r5 = document.getElementById('ribbon-5');

    const cardFp = document.getElementById('card-step-2');
    const cardLaya = document.getElementById('card-step-3');
    const cardOpt = document.getElementById('card-step-4');
    const cardOut = document.getElementById('card-step-5');

    const traceId = 'tr-' + Math.random().toString(36).substring(2, 10);
    document.getElementById('trace-id-badge').textContent = '#' + traceId;

    if (isFastPath) {
      // Metric cards
      document.getElementById('metric-path').textContent = 'Fast-Path (HA)';
      document.getElementById('metric-path').style.color = '#34d399';
      document.getElementById('metric-path-sub').textContent = (domotica.domain || 'HA') + '.' + (domotica.service || 'call');
      document.getElementById('metric-conf').textContent = '100%';
      document.getElementById('metric-conf').style.color = '#34d399';
      document.getElementById('metric-conf-sub').textContent = 'Deterministic rule qualification';
      document.getElementById('metric-tokens').innerHTML = '0 <span style="font-size: 12px; color: var(--text-dim);">tokens</span>';
      document.getElementById('metric-tokens-sub').textContent = 'Zero cloud cost';

      // Ribbon States
      r2.className = 'ribbon-stage fastpath';
      r2.classList.remove('bypassed');
      document.getElementById('ribbon-sub-2').textContent = (domotica.domain || 'HA') + '.' + (domotica.service || 'call');
      document.getElementById('ribbon-foot-2').innerHTML = '<span style="color:#34d399;">✓ Qualified</span>';

      r3.className = 'ribbon-stage bypassed';
      document.getElementById('ribbon-time-3').textContent = '0ms';
      document.getElementById('ribbon-sub-3').textContent = 'Bypassed (Zero-LLM)';
      document.getElementById('ribbon-foot-3').textContent = 'Skipped';

      r4.className = 'ribbon-stage bypassed';
      document.getElementById('ribbon-sub-4').textContent = 'Bypassed (Zero-Token)';
      document.getElementById('ribbon-foot-4').textContent = '0 tokens';

      r5.className = 'ribbon-stage fastpath';
      document.getElementById('ribbon-sub-5').textContent = 'HA Core API';
      document.getElementById('ribbon-foot-5').innerHTML = '<span style="color:#34d399;">Direct Service Call</span>';

      // Detailed Cards Bypassed styling
      cardFp.classList.remove('bypassed');
      cardLaya.classList.add('bypassed');
      cardOpt.classList.add('bypassed');
      cardOut.classList.remove('bypassed');

      document.getElementById('badge-step-fp').textContent = 'QUALIFIED';
      document.getElementById('badge-step-fp').style.background = 'rgba(16, 185, 129, 0.2)';
      document.getElementById('badge-step-fp').style.color = '#34d399';

      document.getElementById('badge-step-laya').textContent = 'BYPASSED';
      document.getElementById('badge-step-laya').style.background = 'rgba(100, 116, 139, 0.2)';
      document.getElementById('badge-step-laya').style.color = '#94a3b8';

      document.getElementById('badge-step-opt').textContent = 'BYPASSED';
      document.getElementById('badge-step-opt').style.background = 'rgba(100, 116, 139, 0.2)';
      document.getElementById('badge-step-opt').style.color = '#94a3b8';

      document.getElementById('badge-step-out').textContent = 'DISPATCHED TO HA';
      document.getElementById('badge-step-out').style.background = 'rgba(16, 185, 129, 0.2)';
      document.getElementById('badge-step-out').style.color = '#34d399';

      document.getElementById('trace-target-dest').textContent = 'Home Assistant Core REST API (/services/' + domotica.domain + '/' + domotica.service + ')';
      document.getElementById('trace-target-speech').textContent = domotica.speech || 'Action confirmed';
      document.getElementById('trace-wire-payload').textContent = domotica.openai_tool_call
        ? JSON.stringify(domotica.openai_tool_call, null, 2)
        : JSON.stringify({ domain: domotica.domain, service: domotica.service, target: domotica.target_id }, null, 2);

      document.getElementById('btn-execute-text').textContent = '⚡ Execute Live against Home Assistant Core';
    } else {
      // Model route active
      const rejectReason = domotica ? (domotica.rejected_reason || 'not_domotica') : 'none';
      const famName = routing ? routing.family.toUpperCase() : 'GENERAL';
      const famConf = Math.round(((routing ? routing.confidence.family : 0) * 100));

      document.getElementById('metric-path').textContent = famName;
      document.getElementById('metric-path').style.color = '#c084fc';
      document.getElementById('metric-path-sub').textContent = routing ? routing.model : 'Cloud LLM';
      document.getElementById('metric-conf').textContent = famConf + '%';
      document.getElementById('metric-conf').style.color = '#c084fc';
      document.getElementById('metric-conf-sub').textContent = 'Neural classification confidence';
      document.getElementById('metric-tokens').innerHTML = (routing && routing.needs_memory === false) ? 'Stripped <span style="font-size: 12px; color: var(--text-dim);">-2k tokens</span>' : 'Retained';
      document.getElementById('metric-tokens-sub').textContent = routing && routing.needs_memory === false ? 'Context memory stripped' : 'Full context enabled';

      // Ribbon States
      r2.className = 'ribbon-stage bypassed';
      document.getElementById('ribbon-sub-2').textContent = `Bypassed (${rejectReason})`;
      document.getElementById('ribbon-foot-2').textContent = 'Escalated to S1';

      r3.className = 'ribbon-stage active';
      r3.classList.remove('bypassed');
      document.getElementById('ribbon-time-3').textContent = (routing ? routing.latency_ms.toFixed(1) : '80') + 'ms';
      document.getElementById('ribbon-sub-3').textContent = famName;
      document.getElementById('ribbon-foot-3').innerHTML = `<span style="color:#c084fc;">${famConf}% confidence</span>`;

      r4.className = 'ribbon-stage active';
      r4.classList.remove('bypassed');
      document.getElementById('ribbon-sub-4').textContent = routing && routing.needs_memory === false ? 'Memory Stripped' : 'Tools Pruned';
      document.getElementById('ribbon-foot-4').textContent = 'Token saving active';

      r5.className = 'ribbon-stage active';
      r5.classList.remove('bypassed');
      document.getElementById('ribbon-sub-5').textContent = routing ? routing.model : 'Cloud LLM';
      document.getElementById('ribbon-foot-5').innerHTML = '<span style="color:#60a5fa;">Upstream Dispatched</span>';

      // Detailed Cards Bypassed styling
      cardFp.classList.add('bypassed');
      cardLaya.classList.remove('bypassed');
      cardOpt.classList.remove('bypassed');
      cardOut.classList.remove('bypassed');

      document.getElementById('badge-step-fp').textContent = 'BYPASSED';
      document.getElementById('badge-step-fp').style.background = 'rgba(245, 158, 11, 0.2)';
      document.getElementById('badge-step-fp').style.color = '#f59e0b';
      document.getElementById('msg-step-fp').textContent = `Bypassed (${rejectReason}): Prompt escalated to Laya System 1 Neural Router.`;

      document.getElementById('badge-step-laya').textContent = routing && routing.override_applied ? 'EXACT OVERRIDE' : 'XPU ACTIVE';
      document.getElementById('badge-step-laya').style.background = 'rgba(139, 92, 246, 0.2)';
      document.getElementById('badge-step-laya').style.color = '#c084fc';

      document.getElementById('badge-step-opt').textContent = 'OPTIMIZED';
      document.getElementById('badge-step-opt').style.background = 'rgba(59, 130, 246, 0.2)';
      document.getElementById('badge-step-opt').style.color = '#60a5fa';

      document.getElementById('badge-step-out').textContent = 'DISPATCHED TO LLM';
      document.getElementById('badge-step-out').style.background = 'rgba(139, 92, 246, 0.2)';
      document.getElementById('badge-step-out').style.color = '#c084fc';

      document.getElementById('trace-target-dest').textContent = `${routing ? routing.model : 'LLM'} via ${routing ? routing.provider : 'Provider'}`;
      document.getElementById('trace-target-speech').textContent = 'Direct Upstream Model Completion';
      document.getElementById('trace-wire-payload').textContent = JSON.stringify({
        model: routing ? routing.model : 'gemini-flash-latest',
        temperature: routing ? routing.temperature : 0.7,
        max_tokens: routing ? routing.max_tokens : 4096,
        thinking_budget: routing ? routing.thinking_budget : null,
        tools_enabled: routing ? routing.allowed_tools : '*'
      }, null, 2);

      document.getElementById('btn-execute-text').textContent = '💬 Query Upstream Model / Chat Endpoint';
    }

    // Populate Step 1 (Input)
    const rawP = document.getElementById('prompt-input').value;
    document.getElementById('trace-raw-input').textContent = rawP;
    document.getElementById('trace-norm-input').textContent = (routing && routing.normalized_input) || rawP.trim().toLowerCase();
    const isFollowup = routing ? routing.is_followup : false;
    document.getElementById('trace-followup-status').innerHTML = isFollowup
      ? '<span style="color:#f59e0b;">Follow-up turn (context injected)</span>'
      : '<span style="color:#34d399;">✓ Standalone turn (isolated evaluation)</span>';

    // Populate Step 2 (Fast Path)
    if (domotica) {
      document.getElementById('trace-fp-status').innerHTML = isFastPath
        ? '<span style="color:#34d399;">✓ Qualified for sub-50ms execution</span>'
        : `<span style="color:#f59e0b;">Bypassed (${domotica.rejected_reason || 'not domotica'})</span>`;
      document.getElementById('trace-fp-checklist').innerHTML = isFastPath
        ? '✓ Imperative | ✓ Single Intent | ✓ Non-conditional | ✓ Safe Target'
        : (domotica.rejected_reason === 'question' ? '✗ Rejected: Question sentence' : 'Bypassed: Non-domotica or low confidence');
      document.getElementById('trace-fp-resolved').textContent = domotica.target_id
        ? `${domotica.target_id} (${domotica.target_type})`
        : (domotica.target_name || 'None');
    }

    // Populate Step 3 (Laya Neural Router)
    if (routing) {
      document.getElementById('trace-laya-latency').textContent = (routing.latency_ms || 0).toFixed(1) + ' ms';
      const layaCp = routing.checkpoint || 'multilingual';
      const detLang = (routing.detection && routing.detection.language) ? routing.detection.language.toUpperCase() : 'NL/EN';
      document.getElementById('trace-laya-checkpoint').textContent = `${layaCp} (Language: ${detLang})`;

      // Render Probability Bars
      const barContainer = document.getElementById('laya-prob-bars');
      barContainer.innerHTML = '';
      if (routing.probabilities) {
        for (const [cand, p] of Object.entries(routing.probabilities)) {
          const pct = Math.round(p * 100);
          const isWinner = (cand === routing.family);
          const barColor = isWinner ? '#3b82f6' : (pct > 20 ? '#52525b' : '#27272a');
          const textColor = isWinner ? '#60a5fa' : '#a1a1aa';
          barContainer.innerHTML += `
            <div class="prob-row">
              <div class="prob-header">
                <span style="font-weight: 600; color: ${textColor};">${cand.toUpperCase()}${isWinner ? ' ★' : ''}</span>
                <span style="font-family: monospace; color: #cbd5e1;">${pct}%</span>
              </div>
              <div class="prob-bar-bg">
                <div class="prob-bar-fill" style="width: ${pct}%; background: ${barColor};"></div>
              </div>
            </div>`;
        }
      }
    }

    // Populate Step 4 (Optimization)
    if (routing) {
      document.getElementById('trace-opt-mem').innerHTML = (routing.needs_memory === false)
        ? '<span style="color:#34d399;">Bypassed &amp; Stripped (Token savings: ~2,000 chars)</span>'
        : '<span style="color:#60a5fa;">Full personal context retained</span>';

      document.getElementById('trace-opt-tools').innerHTML = Array.isArray(routing.allowed_tools)
        ? `<span style="color:#34d399;">Allowed: [${routing.allowed_tools.join(', ')}] (developer tools pruned)</span>`
        : '<span style="color:#60a5fa;">All tools allowed (*)</span>';

      document.getElementById('trace-opt-thinking').textContent = (routing.thinking_budget !== undefined && routing.thinking_budget !== null)
        ? `${routing.thinking_budget} tokens`
        : 'Unconstrained (Deep thinking enabled)';
    }

    // Raw Dump
    document.getElementById('json-dump').textContent = JSON.stringify({
      step_1_input_normalization: {
        raw: rawP,
        normalized: (routing && routing.normalized_input) || rawP.trim().toLowerCase(),
        is_followup: isFollowup
      },
      step_2_fast_path_gate: domotica,
      step_3_laya_system_one_router: routing,
      step_4_optimization: {
        memory_gated: routing ? routing.needs_memory === false : false,
        tools_allowed: routing ? routing.allowed_tools : null,
        thinking_budget: routing ? routing.thinking_budget : null
      },
      step_5_execution_target: {
        destination: isFastPath ? "Home Assistant Core API" : (routing ? routing.model : "LLM"),
        speech: domotica ? domotica.speech : null,
        wall_clock_ms: parseFloat(wallMs)
      }
    }, null, 2);
  }

  async function executeCurrentTarget() {
    const isFastPath = lastDomoticaAction && lastDomoticaAction.fast_path;
    const btn = document.getElementById('btn-execute-live');
    const fb = document.getElementById('live-execution-output');
    btn.disabled = true;
    fb.style.display = 'block';

    if (isFastPath) {
      fb.innerHTML = '<span style="color: #60a5fa;">Dispatching direct REST call to Home Assistant Core...</span>';
      try {
        const res = await fetch('./v1/domotica/route', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: document.getElementById('prompt-input').value.trim(),
            execute: true
          })
        });
        const data = await res.json();
        if (data.executed) {
          fb.innerHTML = `
            <div style="color: #34d399; font-weight: 700; margin-bottom: 4px;">✓ Executed successfully in Home Assistant!</div>
            <div style="font-family: monospace; font-size: 12px; color: #a1a1aa;">Service: ${data.domain}.${data.service} on ${data.target_id}</div>
            <div style="font-family: monospace; font-size: 11px; color: #cbd5e1; margin-top: 6px; background: #0c0c0e; padding: 8px; border-radius: 4px;">${JSON.stringify(data.execution_result || { status: 'confirmed' }, null, 2)}</div>
          `;
        } else {
          fb.innerHTML = '<span style="color: #ef4444; font-weight: 700;">✗ Execution failed or dry-run rejected.</span>';
        }
      } catch (e) {
        fb.innerHTML = '<span style="color: #ef4444;">Error calling HA: ' + e + '</span>';
      } finally {
        btn.disabled = false;
      }
    } else {
      fb.innerHTML = '<span style="color: #c084fc;">Querying conversation completion endpoint...</span>';
      try {
        const res = await fetch('./v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: [{ role: 'user', content: document.getElementById('prompt-input').value.trim() }],
            model: lastModelDecision ? lastModelDecision.model : 'default'
          })
        });
        const data = await res.json();
        const content = (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || JSON.stringify(data);
        fb.innerHTML = `
          <div style="color: #c084fc; font-weight: 700; margin-bottom: 4px;">✓ Response from System 1 Bridge:</div>
          <div style="font-size: 13px; color: #f4f4f5; background: #0c0c0e; padding: 10px; border-radius: 6px; border: 1px solid var(--border);">${content}</div>
        `;
      } catch (e) {
        fb.innerHTML = '<span style="color: #ef4444;">Error calling chat completion: ' + e + '</span>';
      } finally {
        btn.disabled = false;
      }
    }
  }

  async function submitCorrection(family) {
    const prompt = document.getElementById('prompt-input').value.trim();
    if (!prompt) return;
    const fb = document.getElementById('correction-feedback');
    fb.style.display = 'block';
    fb.style.color = '#60a5fa';
    fb.style.background = 'rgba(59, 130, 246, 0.15)';
    fb.textContent = 'Saving override for "' + prompt + '" to ' + family.toUpperCase() + '...';

    try {
      const res = await fetch('./v1/corrections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt,
          family: family,
          effort: (family === 'code' || family === 'deep') ? 'high' : 'normal',
          author: 'ingress_ui'
        })
      });
      const data = await res.json();
      if (data.success) {
        fb.style.color = '#34d399';
        fb.style.background = 'rgba(16, 185, 129, 0.15)';
        fb.textContent = '✓ Override active! Saved to corrections.yaml and queued in candidates.jsonl.';
        setTimeout(() => evaluateTurn(), 400);
      } else {
        fb.style.color = '#ef4444';
        fb.style.background = 'rgba(239, 68, 68, 0.15)';
        fb.textContent = 'Failed saving correction: ' + (data.detail || 'unknown error');
      }
    } catch (e) {
      fb.style.color = '#ef4444';
      fb.style.background = 'rgba(239, 68, 68, 0.15)';
      fb.textContent = 'Error: ' + e;
    }
  }

  loadStatus();
</script>
</body>
</html>"""
