---
id: operations/model_lifecycle
title: "Model Lifecycle, Persistence, and Preloading"
type: "Operational Pattern"
description: "Normative operational pattern for persistent model storage in /share, startup preloading, and lifecycle management."
status: active
trust: authoritative
generated:
  by: "human:matthijs"
  at: "2026-11-01T00:00:00Z"
sources:
  - id: ollama-modelfile
    resource: "https://github.com/ollama/ollama/blob/main/docs/modelfile.md"
    title: "Ollama Modelfile & Storage Reference"
  - id: ha-share-storage
    resource: "https://developers.home-assistant.io/docs/add-ons/configuration#map"
    title: "Home Assistant Add-on Storage Mapping"
---

# Model Lifecycle, Persistence, and Preloading

## Context & Purpose
Downloading multi-gigabyte LLM weights on every container rebuild or restart is intolerable in production. Furthermore, cold-start latency for the first user query must be eliminated by pre-warming weights and Vulkan shader pipelines during startup.

## Operational Standards

### 1. Storage Persistence
- Model weights and manifests are strictly mapped to `/share/ollama_models` (configured via `export OLLAMA_MODELS="/share/ollama_models"`).
- This storage persists across add-on restarts, image rebuilds, and Home Assistant OS updates.
- Backups exclude `/share/ollama_models` by default to avoid inflating backup archives with easily re-downloadable public model weights.

### 2. Multi-Model and Custom Model Configuration
- **Standard Selector:** The `model` configuration option provides curated popular models (`qwen2.5:1.5b`, `llama3.2:3b`, etc.).
- **Custom Model Tag:** Selecting `Other` delegates resolution to `custom_model_name`.
- **Comma-Separated Preloading:** `custom_model_name` accepts comma-separated model identifiers (e.g. `qwen2.5:1.5b,bge-m3:latest`). The startup script iterates through each tag, pulls if missing, and preloads into memory via `/api/generate`.

### 3. Graceful Eviction via `keep_alive`
- **Default:** `5m` (5 minutes). Models remain loaded in memory for 5 minutes after the last inference request.
- **Persistent / Always-On:** Setting `keep_alive: "-1"` or `keep_alive: "24h"` retains the model permanently in VRAM for zero-latency instant responses.
- **Automatic Unload:** When the `keep_alive` timer expires, Ollama unloads weights from GPU memory, freeing shared RAM for other host containers (e.g. Frigate, Plex, Hermes).
