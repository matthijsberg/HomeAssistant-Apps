# Home Assistant App: Ollama (Vulkan)

Run [Ollama](https://ollama.com) locally on Home Assistant with native Vulkan GPU hardware acceleration.

Optimized for **Intel Arc graphics (Discrete & Integrated Xe-LPG)** and **AMD Radeon GPUs** running on Home Assistant OS.

## Highlights
- **Vulkan Acceleration:** Hardware inference acceleration via Mesa ANV drivers (`ppa:ernstp/mesarc`).
- **Intel Arc & Core Ultra Support:** Includes stability workarounds for cooperative matrix (`GGML_VK_DISABLE_COOPMAT=1`) and integer dot products (`GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1`).
- **Memory Efficiency:** Enables Flash Attention (`OLLAMA_FLASH_ATTENTION=1`) paired with Q8_0 KV cache quantization (`OLLAMA_KV_CACHE_TYPE=q8_0`).
- **Supervision & Watchdog:** Autonomous background health loop detects silent inference hangs and restarts Ollama cleanly with a 3-strike restart limit in a 30-minute rolling window.
- **Embedded Web UI:** Ingress proxy on port 8099 with direct model metrics, token latency, and local test chat.
- **Open Knowledge Format (OKF v0.2):** Full architecture and operational specifications located in `knowledge/`.

## Architecture & Documentation
See [`DOCS.md`](DOCS.md) for full configuration instructions and [`knowledge/index.md`](knowledge/index.md) for architectural invariants.
