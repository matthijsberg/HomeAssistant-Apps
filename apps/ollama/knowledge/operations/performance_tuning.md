---
id: operations/performance_tuning
title: "Performance Tuning & Edge Model Selection"
type: "Operational Pattern"
description: "Guidelines for context window sizing, KV-cache tuning, concurrency scaling, and model recommendations for bilingual NL/EN environments."
status: active
trust: authoritative
generated:
  by: "human:matthijs"
  at: "2026-11-01T00:00:00Z"
sources:
  - id: llama-cpp-benchmarks
    resource: "https://github.com/ggml-org/llama.cpp/discussions"
    title: "llama.cpp Intel Arc Performance & Benchmarking"
  - id: qwen-multilingual-evaluation
    resource: "https://qwenlm.github.io/blog/qwen2.5/"
    title: "Qwen 2.5 Multilingual Evaluation Report"
---

# Performance Tuning & Edge Model Selection

## Context & Purpose
Local inference on Intel Arc Xe-LPG iGPU provides exceptional latency when properly tuned. Sub-optimal parameters (such as excessive parallel slots or oversized context without KV-quantization) degrade throughput from 90 tokens/sec down to single digits.

## Tuning Guidelines

### 1. Recommended Models for Dutch/English Multilingual Environments
On host hardware (Intel Core Ultra 5 225H with 48 GB host RAM):

1. **Qwen 2.5 (1.5B & 3B Instruct) — Primary Recommendation:**
   - Outstanding grammatical grasp of Dutch compound nouns (`vloerverwarming`, `inbouwspots`).
   - Generation speed: **~90 to 120 tokens/sec** on Intel Arc iGPU (Q4_K_M).
   - Time-to-first-token (TTFT): **~35 to 50 ms**.
   - Output format: Direct support for native JSON function calling.
2. **Llama 3.2 (3B Instruct) — Secondary Recommendation:**
   - High instruction fidelity and conversational fluency.
   - Generation speed: **~50 to 75 tokens/sec**.
   - Latency P95: **~220 ms** for typical turn responses.
3. **SmolLM2 (1.7B Instruct):**
   - Ultra-lightweight footprint (~1.2 GB VRAM).
   - Ideal for instant classification and intent routing tasks.

### 2. Context Window & KV Cache Sizing
- **Recommended `context_length`:** Set to `4096` or `8192` tokens.
- **KV Cache Quantization:** `OLLAMA_KV_CACHE_TYPE=q8_0` cuts memory consumption in half. With `8192` tokens and Q8_0 KV cache, memory pressure remains well below 3.5 GB, avoiding Intel ANV buffer limit warnings.

### 3. Concurrency (`num_parallel` and `max_loaded_models`)
- **`num_parallel: 1` (Default for Home Assistant):** Eliminates VRAM duplication and context switching overhead for interactive conversational turns.
- **`max_loaded_models: 0` (Auto):** Allows Ollama to dynamically manage model residency based on actual available VRAM rather than hardcoded caps.
