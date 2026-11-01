---
id: architecture/memory_and_layer_allocation
title: "Integrated GPU Unified Memory & Layer Allocation Limits"
type: "Architecture Invariant"
description: "Invariants governing shared RAM limits, UINT32_MAX single-buffer ranges, and GPU/CPU layer allocation boundaries."
status: active
trust: authoritative
generated:
  by: "human:matthijs"
  at: "2026-11-01T00:00:00Z"
sources:
  - id: vulkan-spec-maxstoragebufferrange
    resource: "https://registry.khronos.org/vulkan/specs/1.3/html/vkspec.html#limits-maxStorageBufferRange"
    title: "Vulkan Specification: maxStorageBufferRange"
  - id: intel-anv-allocation-limits
    resource: "https://gitlab.freedesktop.org/mesa/mesa/-/issues"
    title: "Mesa Intel ANV Buffer Size Limits"
---

# Integrated GPU Unified Memory & Layer Allocation Limits

## Context & Purpose
On systems with Intel Integrated Graphics (e.g. Intel Core Ultra 5 225H with 48 GB host RAM), VRAM is dynamically allocated from unified system RAM. While physical capacity is plentiful (48 GB), hardware driver constraints dictate layer allocation boundaries.

## Architectural Invariants

### 1. Vulkan Single-Buffer Limit (`maxStorageBufferRange`)
The Mesa Intel ANV Vulkan driver enforces a maximum single-buffer allocation limit of approximately 4 GB (`UINT32_MAX`).
- If an individual tensor inside a model (such as an unpartitioned embedding table or output `lm_head`) exceeds ~4 GB, Vulkan buffer creation fails.
- Ollama's automatic layer allocation responds by falling back individual layers to CPU.

### 2. Output Layer (`lm_head`) Precision Mismatch
- **All Layers on GPU (e.g. 36/36 layers):** Full precision compute pipeline runs entirely in Vulkan. Inference succeeds with expected latency and token quality.
- **Partial Offload (e.g. 35/36 layers):** When total memory pressure causes Ollama to drop the final layer (`lm_head`) onto CPU, precision mismatch between Vulkan compute tensors and CPU dequantization triggers immediate End-Of-Sequence (EOS) tokens. The model generates only 2 to 3 tokens before terminating.
- **Rule:** On Intel Arc iGPU, models must fit **100% of layers on the GPU**. Partial offloading to CPU is strictly unsafe for interactive completion.

### 3. Context Length and Compute Graph Sizing
Flash Attention (`OLLAMA_FLASH_ATTENTION=1`) reduces the compute graph footprint during memory sizing.
- Without Flash Attention, compute graph estimates force backoff to fewer GPU layers, prematurely triggering CPU offloading.
- With Flash Attention enabled, context lengths of `8192` tokens comfortably fit within unified memory margins without triggering layer reduction.
