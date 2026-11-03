# Ollama (Vulkan)

Run Ollama locally with Vulkan GPU acceleration. This add-on is designed to support a wide range of GPUs, including **Intel Integrated Graphics**, **AMD Radeon**, and other Vulkan-compatible hardware.

## Configuration

### Option: `model`
The model to run. You can choose from the list of popular models.
Default: `qwen3.5:2b`

See the full list of available models at [Ollama Library](https://ollama.com/library).

### Option: `custom_model_name`
If you select **"Other"** in the `model` dropdown, use this field to specify the exact model tag you want to run (e.g., `deepseek-r1:14b`, `mistral:7b-instruct-v0.3-q4_K_M`).
- Default: `""` (Empty)
- Only used when `model` is set to "Other".
- _Model list last synced with [ollama.com/library](https://ollama.com/library): **2026-04-06**_

### Option: `keep_alive`
Controls how long the model stays loaded in memory (RAM/VRAM) after the last request.
- Default: `5m` (5 minutes)
- Set to `-1` to keep the model loaded indefinitely (improves performance for frequent requests but uses more RAM).
- Examples: `10m`, `1h`, `24h`.

### Option: `num_parallel`
The maximum number of parallel requests to handle.
- Default: `1`
- Increase this if you want to handle multiple requests simultaneously (requires more VRAM).

### Option: `max_loaded_models`
The maximum number of models to keep loaded in memory at the same time.
- Default: `0` (auto — Ollama manages based on available VRAM)
- Increase this to a fixed number if you want to cap how many models stay loaded simultaneously.

### Option: `context_length`
The default context window size (in tokens).
- Default: `8192`
- Set to `0` to let Ollama auto-compute the largest context that fits in VRAM — but on Intel iGPU this will trigger harmless backoff warnings in the log due to a Vulkan single-buffer allocation limit (~4 GB). The model still loads fully on GPU, it's just noisy.
- Recommended values: `4096`, `8192`, `16384`. Above ~16384 on Intel iGPU you may see the backoff warnings.
- With Flash Attention enabled (default), larger contexts are significantly more memory-efficient.

### Option: `gpu_overhead`
Reserve a portion of VRAM (in bytes) for other applications or system overhead.
- Default: `0`

### Option: `log_level`
Controls the verbosity of the add-on logs.
- **`info` (Default)**: Standard logging. Shows startup info, GPU detection, and version numbers. Filters out spammy HTTP request logs.
- **`warning`**: More verbose. Shows everything in `info` plus all standard Ollama logs, including HTTP requests.
- **`debug`**: Full debug mode. Enables deep internal debug logs from Ollama (useful for troubleshooting), but still filters out HTTP requests to prevent the Home Assistant supervisor from hanging.

### Option: `disable_fp16`
Disable FP16 (half-precision floating point) compute in the Vulkan backend.
- Default: `false` _(FP16 enabled — confirmed working for llama3.2:3b on Intel iGPU with Mesa 26.0.4)_
- **What it does:** FP16 uses 16-bit floats (range ±65504, limited precision). Disabling forces FP32 (32-bit, full precision) — slightly more memory usage.
- **Intel iGPU (Mesa 26.0.4+):** Leave at `false`. FP16 is confirmed working for common models. If you see garbled or looping output with a specific model, try setting to `true` to rule out FP16 shader issues.
- **Other GPUs (AMD, NVIDIA via Vulkan):** Leave at `false`.
- Sets `GGML_VK_DISABLE_F16=1` internally when `true`.

### Option: `disable_bf16`
Disable BF16 (bfloat16) compute in the Vulkan backend.
- Default: `false` _(BF16 enabled — confirmed working for llama3.2:3b and other common models)_
- **What it does:** BF16 is a 16-bit float format with the same *range* as FP32 but reduced precision. Disabling forces FP32 — correct output on hardware with buggy BF16 shaders, but slightly higher memory usage.
- **Intel iGPU:** Leave at `false` (default). BF16 is confirmed safe for `llama3.2:3b`, `gemma3`, `qwen2.5`, and similar. If you see looping/repeating garbage output with a specific model, try setting to `true` to disable BF16.
- **Gemma 4 note:** `gemma4:e2b` and `gemma4:e4b` (MoE variants) are broken on Intel iGPU regardless of this setting — see Known Issues. `gemma4:26b` (dense) works fine.
- **Other GPUs (AMD, NVIDIA via Vulkan):** Leave at `false`.
- Sets `GGML_VK_DISABLE_BFLOAT16=1` internally when `true`.

### Option: `disable_flash_attention`
Disable Flash Attention.
- Default: `false`
- **Gemma 4 MoE (`gemma4:e2b`, `gemma4:e4b`) on Intel iGPU:** These models are broken on Vulkan regardless of this setting — see Known Issues. Use `gemma4:26b` (dense) instead.
- Try setting to `true` if you see garbage output with specific models (e.g. `glm4`).
- **Trade-off:** Disabling FA increases VRAM usage per token at longer context lengths.

### Option: `enable_vulkan`
Enable Vulkan GPU support.
- Default: `true`
- Set to `false` to force CPU mode if Vulkan is unstable for a specific model.

## Web UI

The add-on includes a built-in Chat UI (accessible via Home Assistant Ingress or directly on port `8099`).
- **Live Chunked Streaming:** Real-time token streaming with zero idle proxy timeouts.
- **Thinking / Reasoning Models:** Live-updating collapsible thought blocks (`🧠 Denkproces`) for models like `ornith-1.5:35b` and DeepSeek-R1.
- **Mobile Reconnection Resilience:** If your mobile 5G or Wi-Fi connection drops during a long generation, the server keeps generating in the background and resumes seamlessly when connectivity returns.
- **Performance Metrics:** View token generation speed (tokens/sec) and latency.
- **Model Management & Chat History:** Persistent conversation history with quick clear (`🧹 Wis chat`).

## Hardware Support

This add-on uses **Vulkan** for hardware acceleration.
- **Intel GPUs:** Requires `mesa-vulkan-drivers` (included). Supports Intel Arc, Iris Xe, and newer iGPUs (Integrated Graphics).
- **AMD GPUs:** Requires `mesa-vulkan-drivers` (included). Supports Radeon RX series and newer.
- **Other:** Any GPU with Vulkan support and Linux drivers available in the base image.

## Performance Tuning

### Memory Usage (iGPU)
If you are using an Integrated GPU (iGPU), your "VRAM" is actually a portion of your system RAM.
- **Total RAM:** 64GB (Example)
- **Reserved for HA:** Ensure you leave enough for Home Assistant (e.g., 12GB).
- **Available for AI:** The rest can be used by Ollama.

You can safely increase the **Context Window (`context_length`)** to utilize more memory for longer conversations.
- Try setting `context_length` to `8192` or `16384` in the configuration.
- Monitor your Home Assistant memory usage to ensure it stays healthy.

### Parallel Requests
With ample RAM, you can also increase `num_parallel` to `2` or `4` to handle multiple requests simultaneously, though this will split the compute power of the iGPU.

## Models

You can find more details about available models on the [Ollama Library](https://ollama.com/library).

## Known Issues & Limitations

### Gemma 4 MoE variants (`gemma4:e2b`, `gemma4:e4b`) — Broken on Intel iGPU Vulkan
`gemma4:e2b` and `gemma4:e4b` are **Mixture of Experts (MoE)** models with 128 expert sub-networks per layer. During inference the Vulkan backend dispatches all 128 experts simultaneously as a single GPU compute job. On Intel iGPU this exceeds the xe kernel driver's hardcoded 10-second GPU job timeout (`CONFIG_DRM_XE_JOB_TIMEOUT_MAX`), causing a GPU reset mid-inference.

This does not crash cleanly — instead the GPU reset silently corrupts the output, causing the model to appear to respond to a completely different question than the one asked, or to produce garbage tokens. No combination of `disable_bf16`, `disable_fp16`, or `disable_flash_attention` fixes this; the root cause is a kernel-level timeout on the MoE compute dispatch, not a precision issue.

| `disable_bf16` | `disable_flash_attention` | Result |
|---|---|---|
| false | false | ❌ Model ignores input, answers invented question |
| false | true | ❌ Only 3 tokens output |
| true | false | ❌ Garbled/looping output |
| true | true | ❌ Only 3–4 tokens output |

**All combinations fail.** This is a kernel driver limitation — confirmed in [ollama/ollama #13964](https://github.com/ollama/ollama/issues/13964) and [llama.cpp #19327](https://github.com/ggml-org/llama.cpp/issues/19327).

**`gemma4:26b` (the dense, non-MoE variant) works correctly on Intel iGPU Vulkan with default settings.**

**Models confirmed working on Intel iGPU with default settings:**
- `qwen3.5:2b` ← default
- `qwen3.5:9b`
- `llama3.2:3b`
- `phi4-mini`
- `gemma3:4b`
- `gemma4:26b` (dense — loads correctly, runs on GPU)
- `qwen2.5:3b`
- `qwen3:4b`

### Intel iGPU Precision (Other Models)
On Intel iGPUs, some Vulkan compute shader paths have known correctness bugs. This add-on automatically applies the following fixes when Vulkan is detected:
- `GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1` — always on, fixes garbled output on all Intel iGPU
- `GGML_VK_DISABLE_COOPMAT=1` — always on, prevents GPU TDR crashes from cooperative matrix ops
- `GGML_VK_DISABLE_COOPMAT2=1` — always on, prevents GPU TDR crashes from second-gen cooperative matrix ops
- `GGML_VK_DISABLE_F16=1` — optional, controlled via `disable_fp16` setting
- `GGML_VK_DISABLE_BFLOAT16=1` — optional, controlled via `disable_bf16` setting
