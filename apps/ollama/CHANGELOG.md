# Changelog — Ollama (Vulkan) Home Assistant App

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-11-03

### Added
- **Live Chunked Streaming (`web_server.py` & `index.html`)**: Switched chat completions to HTTP/1.1 chunked streaming (`Transfer-Encoding: chunked`) with native `ReadableStream` decoding. Eliminates the 60s idle reverse proxy timeout on long generations (such as code generation on 35B models).
- **Mobile Reconnection Resilience (`SessionManager` & `/api/chat_resume`)**: Background worker thread buffers Ollama response tokens on the host. If a mobile 5G or Wi-Fi connection drops mid-stream, the generation continues uninterrupted and the browser automatically re-attaches and resumes via `/api/chat_resume?id=<message_id>&offset=<token_count>`.
- **Reasoning / Thinking Model Visualization**: Dedicated live-updating collapsible card (`🧠 Denkproces`) for reasoning models (e.g. `ornith-1.5:35b` / DeepSeek-R1) displaying thought steps in real time before code/content output.
- **LocalStorage State Persistence**: Multi-turn chat history and active in-flight requests persist in browser `localStorage`, seamlessly recovering conversations across browser restarts or page reloads.
- **Chat Management**: Added `🧹 Wis chat` button in the Web UI to reset conversation history cleanly.

---

## [0.7.3] - 2026-11-01

### Fixed
- **Strip Forwarded Transfer-Encoding Header (`web_server.py`)**: Fixed critical bug where `Transfer-Encoding: chunked` from HA Supervisor Ingress was forwarded in `requests` headers to Ollama while passing a decoded `bytes` body, causing Ollama's Go HTTP server to reject or hang on malformed chunk framing.
- **Conversational Multi-Turn Memory (`index.html`)**: Added `chatHistory` array to `sendMessage()` so chat turns preserve conversational context and support both `/api/chat` and `/api/generate` responses.

---

## [0.7.2] - 2026-11-01

### Added
- **Direct LAN Port Mapping (`8099/tcp`)**: Added direct port `8099` mapping to allow opening the Web UI directly on the local network (`http://<ha-ip>:8099/`), bypassing Home Assistant Ingress iframes.

### Fixed
- **Ingress Chunked Request Body Decoding (`web_server.py`)**: Fixed critical bug where Home Assistant Supervisor Ingress proxies POST request bodies with `Transfer-Encoding: chunked`. Previously, `web_server.py` only checked `Content-Length`, forwarding empty payload `data=None` to Ollama which caused Ollama to wait until a 300s read timeout occurred.

---

## [0.7.1] - 2026-11-01

### Added
- **Mobile-First Responsive Web UI (`index.html`)**: HTML `<form>` submission handling to support mobile touch virtual keyboards (Android Gboard / iOS) on Enter/Go key.
- **In-Chat Diagnostics**: Replaced browser `alert()` popups with in-chat diagnostic messages for model loading, connection testing, and deletion.
- **Auto-Selection**: Guaranteed selection of default model (`qwen2.5:7b`) on initial dropdown populate across mobile WebViews.
- **Cache-Busting & Version Header**: Integrated `v0.7.1` version badge and no-cache meta tags to prevent stale WebView asset caching.

### Fixed
- **CORS Preflight (`web_server.py`)**: Added full `do_OPTIONS` handler with `Access-Control-Allow-Origin: *` to prevent `Error: Failed to fetch` on browser JSON requests.
- **Stream Stalling & Framing**: Fixed unchunked HTTP stream hang by delivering clean buffered responses with explicit `Content-Length`.
- **Ingress Path Normalization**: Automatically strips redundant leading slashes (`//api/chat` -> `/api/chat`) passed by Home Assistant Ingress.

### Changed
- **Default Resource Allocation**: Set `context_length: 8192` and `num_parallel: 1` as standard to avoid VRAM over-allocation and 5-minute allocation timeouts on shared Intel Arc memory.

---

## [0.7.0] - 2026-11-01

### Added
- **Ollama Core Upgrade**: Upgraded base engine to official Ollama `v0.40.13` (October 2026).
- **Mesa Vulkan 26 Drivers**: Integrated `ppa:ernstp/mesarc` delivering Mesa 26.2 for Intel Arrow Lake (ARL) Xe-LPG graphics support.
- **Unified Host Memory**: Enabled `GGML_VK_PREFER_HOST_MEMORY=1` allowing iGPU to access the full 48 GB host RAM (41.1 GiB available).
- **Elimination of llvmpipe**: Explicit ICD configuration via `VK_DRIVER_FILES` and `GGML_VK_VISIBLE_DEVICES="0"` to completely disable software CPU rendering.
- **Persistent Shader Cache**: Mapped `MESA_SHADER_CACHE_DIR="/share/ollama_models/.mesa_cache"` on persistent NVMe storage.
- **Flash Attention & KV-Cache**: Enabled `OLLAMA_FLASH_ATTENTION=1` with `OLLAMA_KV_CACHE_TYPE=q8_0` for 50% reduced context memory usage.
- **Open Knowledge Format (OKF v0.2)**: Comprehensive knowledge bundle documenting architecture invariants, memory bounds, watchdog supervision, and performance tuning.
- **Automated Verification Harness**: Added `scripts/setup.sh`, manifest validation, OKF validation, security audits, and automated pytest suite.
