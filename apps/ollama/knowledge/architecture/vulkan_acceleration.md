---
id: architecture/vulkan_acceleration
title: "Intel Arc Vulkan GPU Hardware Acceleration"
type: "Architecture Invariant"
description: "Normative specification of the Vulkan runtime environment, Mesa ANV driver stack, and required precision/TDR workarounds."
status: active
trust: authoritative
generated:
  by: "human:matthijs"
  at: "2026-11-01T00:00:00Z"
sources:
  - id: llama-cpp-17056
    resource: "https://github.com/ggml-org/llama.cpp/issues/17056"
    title: "Vulkan integer dot product broken on Intel Arc ANV"
  - id: llama-cpp-11592
    resource: "https://github.com/ggml-org/llama.cpp/discussions/12770"
    title: "Vulkan GGML_VK_PREFER_HOST_MEMORY iGPU Host Visible Memory"
  - id: ollama-docs-gpu
    resource: "https://docs.ollama.com/gpu"
    title: "Ollama Hardware Support Documentation"
  - id: mesa-anv-notes
    resource: "https://docs.mesa3d.org/drivers/anv.html"
    title: "Mesa Intel ANV Vulkan Driver Documentation"
---

# Intel Arc Vulkan GPU Hardware Acceleration

## Context & Purpose
Ollama does not provide native Level-Zero/SYCL compute binaries in its official Linux distribution. On Intel hardware (such as Intel Core Ultra Meteor Lake / Arrow Lake with Xe-LPG graphics), high-performance local inference is achieved using Vulkan compute (`OLLAMA_VULKAN=1`) driven by the open-source Mesa Intel ANV driver.

## Mandatory Architectural Invariants

### 1. Driver Stack & PPA
- **Base Distribution:** Ubuntu 24.04 LTS (Noble Numbat).
- **Mesa Driver:** Pinned to `ppa:ernstp/mesarc` (Mesa 26.0 / 26.1 series). Mesa 26 is strictly required for Arrow Lake / Lunar Lake Xe-LPG / Xe2 architectures to eliminate first-run pipeline stutter and provide `VK_KHR_pipeline_binary`.
- **Packages:** `mesa-vulkan-drivers`, `libvulkan1`, and `vulkan-tools` must be present.

### 2. Elimination of Software Rasterizer (`llvmpipe`)
By default, Mesa exposes both the hardware GPU (`GPU0: Intel(R) Graphics (ARL)`) and the CPU fallback (`GPU1: llvmpipe (LLVM)`).
- **Invariant:** When hardware acceleration is enabled, `VK_DRIVER_FILES` and `VK_ICD_FILENAMES` must be clamped strictly to `/usr/share/vulkan/icd.d/intel_icd.x86_64.json` (or `radeon_icd.x86_64.json` for AMD).
- In addition, `GGML_VK_VISIBLE_DEVICES="0"` restricts GGML device enumeration strictly to the first physical device, completely preventing split-device or CPU-fallback scheduling traps.

### 3. Unified Host Memory Optimization (`GGML_VK_PREFER_HOST_MEMORY=1`)
On integrated GPUs (iGPUs), VRAM is dynamically shared system memory.
- Standard Vulkan initialization queries a small device-local memory heap (often clamped to 2–4 GB), leading to unnecessary layer eviction or false OOM errors.
- **Invariant:** `export GGML_VK_PREFER_HOST_MEMORY=1` must be set. This allows the Vulkan backend to allocate directly from unified host RAM (up to the full system limit of 48 GB) and yields an empirical **10% to 15% throughput boost** by bypassing redundant host-to-device memory copy stages.

### 4. Persistent Shader Pipeline Caching
Mesa ANV compiles compute pipelines at runtime for model-specific tensor dimensions. In Docker containers, default cache paths write to `/root/.cache` and are lost on container restart.
- **Invariant:** `MESA_SHADER_CACHE_DIR="/share/ollama_models/.mesa_cache"` and `MESA_SHADER_CACHE_MAX_SIZE="2G"` must be set with `ANV_ENABLE_PIPELINE_CACHE=1`.
- This ensures all compiled shader binaries are permanently cached to NVMe storage, eliminating cold-start pipeline stutters across container restarts.

### 5. Intel iGPU Hardware Workarounds (Non-Negotiable)
When an Intel Vulkan GPU is detected, the container runtime must export the following environment flags:

1. **`GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1`**
   - *Rationale:* Integer dot product operations in the Mesa ANV Vulkan backend cause corrupted/garbage output and numerical instability across GGML quantization kernels (llama.cpp #17056, #17106).
2. **`GGML_VK_DISABLE_COOPMAT=1` & `GGML_VK_DISABLE_COOPMAT2=1`**
   - *Rationale:* Enabling `VK_KHR_cooperative_matrix` on Intel Arc integrated graphics triggers GPU Timeout Detection and Recovery (TDR) crashes and kernel resets.
3. **`OLLAMA_SCHED_SPREAD=1`**
   - *Rationale:* Ensures deterministic memory spreading across available compute blocks.

### 6. Flash Attention & KV-Cache Quantization
To maintain low VRAM footprint on shared system RAM:
- **`OLLAMA_FLASH_ATTENTION=1`**: Must be explicitly exported unless the user flags `disable_flash_attention: true`.
- **`OLLAMA_KV_CACHE_TYPE=q8_0`**: Compresses the key-value context cache by 50% with negligible perplexity penalty, critical for context lengths up to 8192 or 16384 tokens on unified memory.
- **`OLLAMA_NEW_ENGINE=1`**: Enables exact VRAM measurement prior to model loading, preventing over-allocation backoff.
