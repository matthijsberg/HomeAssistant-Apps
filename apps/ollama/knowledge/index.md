---
okf_version: "0.2"
title: "Ollama Vulkan Home Assistant App Knowledge Bundle"
description: "Authoritative architectural invariants, hardware constraints, and operational patterns for ha-addon-ollama."
last_updated: "2026-11-01"
---

# Knowledge Index — ha-addon-ollama

This bundle contains the normative architectural decisions, hardware acceleration constraints, and operational invariants governing the **Ollama (Vulkan) Home Assistant App**.

## 1. Architecture Invariants
- [`vulkan-acceleration`](architecture/vulkan_acceleration.md) — Intel Arc & AMD GPU Vulkan runtime configuration, Mesa 26 ANV drivers, Flash Attention, and mandatory integer dot product / cooperative matrix workarounds.
- [`watchdog-supervision`](architecture/watchdog_supervision.md) — Multi-tier health probe architecture, generation hang detection, and 3-strike rolling window circuit breaker preventing restart loops.
- [`memory-and-layer-allocation`](architecture/memory_and_layer_allocation.md) — Shared RAM iGPU memory limits, UINT32_MAX Vulkan single-buffer constraint, 36/36 vs 35/36 layer behavior, and CPU offloading failure modes.
- [`streaming-and-reconnection`](architecture/streaming_and_reconnection.md) — HTTP/1.1 chunked streaming, thinking token handling, and mobile reconnection resilience via SessionManager and resume endpoints.

## 2. Operations & Performance
- [`model-lifecycle`](operations/model_lifecycle.md) — Model persistence in `/share/ollama_models`, custom model tags, preloading semantics, and idle unloading via `keep_alive`.
- [`performance-tuning`](operations/performance_tuning.md) — Context window sizing, KV-cache quantization (`q8_0`), parallel execution scaling, and recommended bilingual (Dutch/English) SLM archetypes.
