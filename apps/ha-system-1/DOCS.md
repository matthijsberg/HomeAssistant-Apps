# HA System 1 — Technical & Protocol Documentation

HA System 1 is a local, sub-50ms cognitive reflex engine, neural intent classifier, and OpenAI-compatible conversation bridge designed for Home Assistant and autonomous AI agents (such as Hermes Agent and OpenCode).

---

## 1. Architectural Philosophy: System 1 First

The architecture separates human cognitive tasks into two distinct layers:
* **System 1 (Local, Fast, Reflexive):** Sub-100ms hardware-accelerated classification running directly on host hardware (Intel Arc iGPU / XPU or edge CPU). System 1 identifies whether an input is a smart home command, general conversation, coding task, or complex financial/mathematical reasoning. It extracts semantic slots without brittle regexes, manages tool allowlists, and strips unnecessary personal memory context.
* **System 2 (Deliberative, Deep, Upstream LLM):** Cloud or high-parameter models (Gemini Flash, Gemini Pro, Claude 3.7 Sonnet) invoked only when genuine deep reasoning, multi-step code execution, or fallback assistance is required.

### Pluggable System 1 Backends
While the current engine uses **Laya** (ModernBERT-large and mmBERT-base cross-encoders running on Intel Arc Level-Zero DRM XPU), the architecture is model-agnostic. The internal backend interface is designed to support:
1. **Laya Cross-Encoder Matrix:** Zero-shot criteria scoring across multilingual candidate sets (55–100ms).
2. **Local Edge SLMs (Future):** Quantized GGUF/Vulkan small language models (Qwen2.5-0.5B, SmolLM2-360M, Llama-3.2-1B) for direct JSON generation.
3. **Embedding Vector Classifiers:** Sub-5ms cosine similarity matching against golden intent embeddings.

---

## 2. Configuration & The Fast-Path Toggle

All operational parameters are configurable via Home Assistant Add-on Options (`config.yaml` / Supervisor GUI):

```yaml
# Hardware Compute & Engine
device: "xpu"                 # 'xpu' for Intel Arc / Meteor Lake iGPU, 'cpu' for fallback
threads: 6                    # Intra-op PyTorch CPU inference threads
router_default: "multilingual" # Fallback checkpoint for short ambiguous turns
api_key: ""                   # Optional Bearer token for remote clients

# Thresholds & Gating (Conservative Gating PRD D-3)
min_confidence: 0.60          # Confidence floor for model routing (fallback to general)
domotica_min_confidence: 0.70 # Minimum confidence for direct smart home execution
smarthome_min_confidence: 0.50# Minimum confidence to allocate HA tools and smarthome profile

# Fast-Path Gate Toggle
fast_path_enabled: true       # Toggle: true = <0.5ms rule gate; false = System 1 neural first
```

### The `fast_path_enabled` Switch
* **`true` (Default):** Simple unambiguous imperatives (*"doe de spots in de serre uit"*) resolve deterministically via registry string matching in `<0.5ms` without engaging GPU compute.
* **`false` (Neural-First):** The regex gate is disabled. **All smart home and user turns flow directly through the System 1 neural model** on the Intel Arc XPU. This eliminates brittle keyword limitations and lets the neural cross-encoder extract rooms, device types, and scopes semantically.

---

## 3. `/v1/systemone` Protocol & API Specification

The `/v1/systemone` endpoint provides a raw, model-agnostic wire protocol for evaluating structured choice and score questions in a single forward pass. It is 100% compatible with Jev and OpenCode System 1 tooling.

### HTTP Endpoint
* **URL:** `http://<host>:8000/v1/systemone`
* **Method:** `POST`
* **Headers:**
  * `Content-Type: application/json`
  * `Authorization: Bearer <api_key>` (if configured)

### Request Schema

```json
{
  "state": {
    "request": "Turn off all the lights in the house",
    "context": [
      "user: Is it late?",
      "assistant: Yes, it is 23:30."
    ]
  },
  "questions": {
    "task_family": {
      "type": "choice",
      "instructions": "What kind of task is this?",
      "criteria": {
        "quick": "small talk, greetings, simple facts, unit conversions",
        "smarthome": "home automation, turning lights on or off, thermostats, switches, Home Assistant",
        "general": "everyday writing, explaining, summarising, translating",
        "code": "writing or debugging code or configuration files",
        "deep": "hard reasoning, finance, mathematics, complex comparison"
      }
    },
    "effort": {
      "type": "choice",
      "instructions": "How much thinking does this task need?",
      "criteria": {
        "light": "the answer is short and obvious",
        "normal": "needs some thought or a few steps",
        "deep": "needs careful multi-step reasoning"
      }
    }
  },
  "parameters": {
    "temperature": 1.0,
    "top_k": null
  },
  "model": "multilingual"
}
```

#### Request Fields
* **`state` (object, required):**
  * `request` (string, required): The latest user turn or command to be evaluated.
  * `context` (array of strings, optional): Preceding conversational context turns.
* **`questions` (object, required):** A map of question identifiers to question specifications.
  * **`type` (string):** `"choice"` (mutually exclusive softmax over `criteria`) or `"score"` (scalar confidence estimation).
  * **`instructions` (string):** Prompt instruction for the question.
  * **`criteria` (object):** Map of option keys to descriptive semantic criteria.
* **`parameters` (object, optional):** Calibrated softmax temperatures or sampling parameters.
* **`model` (string, optional):** Checkpoint override (`"multilingual"` or `"english"`).

---

### Response Schema

```json
{
  "answers": {
    "task_family": {
      "choice": "smarthome",
      "answer_confidence": 0.8842,
      "probabilities": {
        "quick": 0.0512,
        "smarthome": 0.8842,
        "general": 0.0411,
        "code": 0.0125,
        "deep": 0.0110
      },
      "log_odds": {
        "smarthome": 2.0325,
        "quick": -1.8210
      }
    },
    "effort": {
      "choice": "light",
      "answer_confidence": 0.9215,
      "probabilities": {
        "light": 0.9215,
        "normal": 0.0652,
        "deep": 0.0133
      }
    }
  },
  "detection": {
    "script": "latin",
    "script_profile": { "latin": 1.0 },
    "language": "en",
    "is_english": true,
    "language_undecided": false,
    "diacritic_rate": 0.0,
    "non_latin_fraction": 0.0
  },
  "latency_ms": 78.42,
  "model": "multilingual",
  "device": "xpu"
}
```

#### Response Fields
* **`answers` (object):** Evaluated predictions per question key.
  * `choice` (string): The winning category key with the highest softmax probability.
  * `answer_confidence` (float): Probability score of the winning choice (0.0 to 1.0).
  * `probabilities` (object): Complete softmax probability distribution over all submitted criteria options.
  * `log_odds` (object): Raw logits before temperature scaling.
* **`detection` (object):** Language and script telemetry detected from the input string.
* **`latency_ms` (float):** Hardware forward-pass time in milliseconds measured on the Intel Arc XPU.
* **`device` (string):** Compute device utilized (`"xpu"` or `"cpu"`).

---

### Raw cURL Example

```bash
curl -X POST http://local-ha-system-1:8000/v1/systemone \
  -H "Content-Type: application/json" \
  -d '{
    "state": {
      "request": "Bereken de annuïtaire hypotheeklasten voor 450k"
    },
    "questions": {
      "family": {
        "type": "choice",
        "instructions": "Categorize the task:",
        "criteria": {
          "quick": "chit chat, greetings, unit conversions",
          "deep": "complex mathematics, finance, mortgages, investments"
        }
      }
    }
  }'
```

---

## 4. High-Level Decision Endpoint (`POST /v1/route`)

For autonomous agents (Hermes, Claude Code, OpenCode) that require an end-to-end decision payload with configured model assignments, tool pruning, and token ceilings:

```json
// POST /v1/route
{
  "prompt": "turn off all lights in the house",
  "recent_turns": [],
  "question_set": "hermes-v1"
}

// Response (<100ms)
{
  "family": "smarthome",
  "effort": "light",
  "confidence": {
    "family": 0.8842,
    "effort": 0.9215
  },
  "checkpoint": "english",
  "latency_ms": 82.1,
  "provider": "gemini",
  "model": "gemini-3.5-flash-lite",
  "max_tokens": 1024,
  "temperature": 0.0,
  "thinking_budget": 0,
  "needs_memory": false,
  "allowed_tools": [
    "ha_list_entities",
    "ha_get_state",
    "ha_call_service",
    "ha_list_services",
    "homeassistant*"
  ],
  "override_applied": null,
  "fallback_reason": null,
  "probabilities": {
    "quick": 0.0612,
    "smarthome": 0.8842,
    "general": 0.0315,
    "code": 0.0121,
    "deep": 0.0110
  }
}
```

---

## 5. Direct Domotica Endpoint (`POST /v1/domotica/route`)

Resolves smart home natural language into structured OpenAI-compatible tool calls or directly executes them against Home Assistant Core:

```json
// POST /v1/domotica/route
{
  "prompt": "doe de spots in de serre uit",
  "execute": true
}

// Response
{
  "is_domotica": true,
  "fast_path": true,
  "domain": "light",
  "service": "turn_off",
  "target_type": "entity_id",
  "target_id": "light.serre_spots_dimmer",
  "confidence": 0.9984,
  "openai_tool_call": {
    "id": "call_hasys1_945854",
    "type": "function",
    "function": {
      "name": "HassTurnOff",
      "arguments": {
        "name": "light.serre_spots_dimmer"
      }
    }
  },
  "speech": "Oké, spots serre is uitgeschakeld.",
  "executed": true,
  "execution_status": "confirmed"
}
```

---

## 6. Exact Sticky Overrides (`corrections.yaml`)

When a turn is misclassified or requires an absolute override, exact matches are stored in `/addon_configs/local_ha_system_1/corrections.yaml`. Overrides resolve in `<0.5ms` with 100% confidence, bypassing model inference entirely. Every override is logged to `candidates.jsonl` for evaluation gating.
