#!/usr/bin/env bashio

bashio::log.info "Starting Ollama (Vulkan) Add-on v0.6.13..."

# --- Software Versions ---
if command -v ollama >/dev/null 2>&1; then
    # ollama --version prints a "could not connect" warning before the version line;
    # suppress stderr and extract only the version number
    OLLAMA_VER=$(ollama --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1)
    bashio::log.info "Ollama: ${OLLAMA_VER:-unknown}"
else
    bashio::log.warning "Ollama binary not found!"
fi

bashio::log.info "Kernel: $(uname -r)"
bashio::log.info "Python: $(python3 --version 2>&1)"

MESA_PKG_VER=$(dpkg -l mesa-vulkan-drivers 2>/dev/null | grep "^ii" | awk '{print $3}')
if [ -n "$MESA_PKG_VER" ]; then
    bashio::log.info "Mesa (mesa-vulkan-drivers pkg): $MESA_PKG_VER"
fi

# --- 0. Environment Setup ---
export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_MODELS="/share/ollama_models"
export OLLAMA_ORIGINS="*"

# Load Config
KEEP_ALIVE=$(bashio::config 'keep_alive')
NUM_PARALLEL=$(bashio::config 'num_parallel')
MAX_LOADED_MODELS=$(bashio::config 'max_loaded_models')
NUM_CTX=$(bashio::config 'context_length')
GPU_OVERHEAD=$(bashio::config 'gpu_overhead')
LOG_LEVEL=$(bashio::config 'log_level')
CUSTOM_MODEL_NAME=$(bashio::config 'custom_model_name')
DISABLE_FP16=$(bashio::config 'disable_fp16')
DISABLE_BF16=$(bashio::config 'disable_bf16')
DISABLE_FA=$(bashio::config 'disable_flash_attention')
ENABLE_VULKAN=$(bashio::config 'enable_vulkan')

export OLLAMA_KEEP_ALIVE="$KEEP_ALIVE"
export OLLAMA_NUM_PARALLEL="$NUM_PARALLEL"
export OLLAMA_MAX_LOADED_MODELS="$MAX_LOADED_MODELS"
# 0 = auto-detect based on available VRAM (Ollama default behaviour)
if [ "$NUM_CTX" -gt 0 ] 2>/dev/null; then
    export OLLAMA_CONTEXT_LENGTH="$NUM_CTX"
fi
export OLLAMA_GPU_OVERHEAD="$GPU_OVERHEAD"

# Set Bashio Log Level to info so startup logs always show
bashio::log.level "info"

# Configure Ollama Logging based on level
if [ "$LOG_LEVEL" = "debug" ] || [ "$LOG_LEVEL" = "trace" ]; then
    export OLLAMA_DEBUG="1"
else
    export OLLAMA_DEBUG="0"
fi

# --- 1. Hardware Check ---
bashio::log.info "Checking for Vulkan support..."

if command -v vulkaninfo >/dev/null 2>&1; then
    # Check if vulkaninfo returns any devices
    if vulkaninfo --summary 2>/dev/null | grep -i "GPU" > /dev/null; then
        GPU_NAME=$(vulkaninfo --summary 2>/dev/null | grep "deviceName" | cut -d'=' -f2 | xargs)
        DRIVER_VER=$(vulkaninfo --summary 2>/dev/null | grep "driverVersion" | cut -d'=' -f2 | xargs)
        API_VER=$(vulkaninfo --summary 2>/dev/null | grep "apiVersion" | cut -d'=' -f2 | xargs)

        bashio::log.info "Vulkan GPU detected: $GPU_NAME"
        bashio::log.info "Mesa Driver Version: $DRIVER_VER"
        bashio::log.info "API Version: $API_VER"
        
        # Enable experimental Vulkan support
        export OLLAMA_VULKAN=1
        export OLLAMA_IGPU_ENABLE=1
        export OLLAMA_SCHED_SPREAD=1
        export GGML_VK_VISIBLE_DEVICES="0"

        # Filter out llvmpipe software rasterizer to prevent false multi-device allocations
        if echo "$GPU_NAME" | grep -iq "intel"; then
            export VK_DRIVER_FILES="/usr/share/vulkan/icd.d/intel_icd.x86_64.json"
            export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/intel_icd.x86_64.json"
        elif echo "$GPU_NAME" | grep -iq "radeon\|amd"; then
            export VK_DRIVER_FILES="/usr/share/vulkan/icd.d/radeon_icd.x86_64.json"
            export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/radeon_icd.x86_64.json"
        fi

        # Unified host memory access for iGPU (avoids artificial VRAM caps and gives 10-15% throughput boost)
        export GGML_VK_PREFER_HOST_MEMORY=1

        # Persistent Mesa shader cache on persistent NVMe storage (eliminates first-token stutter)
        mkdir -p "/share/ollama_models/.mesa_cache"
        export MESA_SHADER_CACHE_DIR="/share/ollama_models/.mesa_cache"
        export MESA_SHADER_CACHE_MAX_SIZE="2G"
        export ANV_ENABLE_PIPELINE_CACHE=1

        # Intel iGPU correctness fixes (prevents garbage output and GPU TDR crashes)
        export GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1
        export GGML_VK_DISABLE_COOPMAT=1
        export GGML_VK_DISABLE_COOPMAT2=1

        # Performance: exact VRAM measurement — fits more model layers on-GPU
        export OLLAMA_NEW_ENGINE=1

        # Performance: Flash Attention + KV cache quantization
        # Reduces VRAM per token at longer contexts; critical for iGPU shared memory
        if [ "$DISABLE_FA" = "true" ]; then
            export OLLAMA_FLASH_ATTENTION=0
            bashio::log.info "Flash Attention Disabled"
        else
            export OLLAMA_FLASH_ATTENTION=1
            export OLLAMA_KV_CACHE_TYPE=q8_0
            bashio::log.info "Flash Attention enabled, KV cache type: q8_0"
        fi

        # FP16 precision control
        if [ "$DISABLE_FP16" = "true" ]; then
            export GGML_VK_DISABLE_F16=1
            bashio::log.info "Precision Tweak: FP16 Disabled"
        fi

        # BF16 precision control
        if [ "$DISABLE_BF16" = "true" ]; then
            export GGML_VK_DISABLE_BFLOAT16=1
            bashio::log.info "Precision Tweak: BF16 Disabled"
        fi

        bashio::log.info "Enabled OLLAMA_VULKAN=1, SCHED_SPREAD, NEW_ENGINE, DISABLE_INTEGER_DOT_PRODUCT, DISABLE_COOPMAT, DISABLE_COOPMAT2"

        if [ "$OLLAMA_DEBUG" = "1" ]; then
            vulkaninfo --summary
        fi
    else
        bashio::log.warning "Vulkan tools installed, but no GPU detected via vulkaninfo."
    fi
else
    bashio::log.warning "vulkaninfo not found. Cannot verify Vulkan support explicitly."
fi

if [ -d "/dev/dri" ]; then
    bashio::log.info "/dev/dri exists. GPU device files are present."
else
    bashio::log.warning "ATTENTION: /dev/dri missing. GPU might not be accessible."
fi

# --- 2. Start Ollama (Background) ---
bashio::log.info "Starting Ollama server (Vulkan: ${OLLAMA_VULKAN:-0}, Log Level: $LOG_LEVEL)..."

if [ "$LOG_LEVEL" = "debug" ] || [ "$LOG_LEVEL" = "trace" ]; then
    # Full debug, but filter GIN to prevent supervisor hang
    # --line-buffered prevents pipe back-pressure that can freeze inference
    OLLAMA_VULKAN=${OLLAMA_VULKAN:-0} ollama serve 2>&1 | grep --line-buffered -v "\[GIN\]" &
elif [ "$LOG_LEVEL" = "warning" ]; then
    # More verbose than info: shows all standard logs including HTTP requests
    OLLAMA_VULKAN=${OLLAMA_VULKAN:-0} ollama serve &
else
    # Standard info level — filters HTTP request logs
    # --line-buffered prevents pipe back-pressure that can freeze inference
    OLLAMA_VULKAN=${OLLAMA_VULKAN:-0} ollama serve 2>&1 | grep --line-buffered -v "\[GIN\]" &
fi
PID=$!

# Wait for API to be ready
bashio::log.info "Waiting for Ollama API..."
until curl -s -f "http://localhost:11434/" > /dev/null; do
    sleep 1
done
bashio::log.info "Ollama is online!"

# --- 3. Model Management ---
MODEL=$(bashio::config 'model')

# Handle Custom Model
if [ "$MODEL" = "Other" ]; then
    if [ -z "$CUSTOM_MODEL_NAME" ]; then
        bashio::log.info "Model set to 'Other' and 'custom_model_name' is empty. Skipping automatic model download."
        MODEL=""
    else
        MODEL="$CUSTOM_MODEL_NAME"
        bashio::log.info "Using custom model: $MODEL"
    fi
fi

# Split MODEL by comma and process each
IFS=',' read -ra MODEL_ARRAY <<< "$MODEL"
for SINGLE_MODEL in "${MODEL_ARRAY[@]}"; do
    # Trim whitespace
    SINGLE_MODEL=$(echo "$SINGLE_MODEL" | xargs)
    
    if [ -n "$SINGLE_MODEL" ]; then
        bashio::log.info "Checking model: $SINGLE_MODEL"

        if ollama list | grep -q "$SINGLE_MODEL"; then
            bashio::log.info "Model '$SINGLE_MODEL' already present."
        else
            bashio::log.info "Downloading '$SINGLE_MODEL'. This may take a while..."
            ollama pull "$SINGLE_MODEL"
            bashio::log.info "Download of '$SINGLE_MODEL' complete."
        fi
        
        bashio::log.info "Preloading '$SINGLE_MODEL' into memory..."
        curl -s -X POST http://localhost:11434/api/generate -d "{\"model\": \"$SINGLE_MODEL\", \"keep_alive\": \"$KEEP_ALIVE\"}" > /dev/null
    fi
done

# --- 4. Keep Running ---
bashio::log.info "Ready to serve. Keep-alive set to: $KEEP_ALIVE"

# --- 5. Start Web UI ---
bashio::log.info "Starting Web UI..."
python3 -u /web_server.py 2>&1 &
WEB_PID=$!

# --- 6. Watchdog: Detect silent inference hangs ---
# Ollama can appear online (TCP port open) but stop generating output — typically
# caused by a GPU hang or an internal deadlock. The HA supervisor watchdog only
# checks TCP connectivity, so this loop catches silent hangs and exits the script
# so the supervisor can restart the addon cleanly.
#
# Rate limit: if the watchdog triggers more than WATCHDOG_MAX_TRIGGERS times
# within WATCHDOG_WINDOW seconds, it gives up and logs a fatal error instead of
# restarting in a tight loop. Trigger timestamps are written to /tmp so the
# count survives supervisor-triggered restarts (but resets on a full addon
# stop/start or system reboot, which is the desired behaviour).
WATCHDOG_MODEL="${MODEL_ARRAY[0]}"
WATCHDOG_MAX_TRIGGERS=3       # max restarts allowed within the window
WATCHDOG_WINDOW=1800          # rolling window in seconds (30 minutes)
WATCHDOG_TRIGGER_FILE="/tmp/ollama_watchdog_triggers"
(
    sleep 120  # Grace period — allow model to fully warm up first
    while true; do
        sleep 300  # Check every 5 minutes
        if ! kill -0 "$PID" 2>/dev/null; then
            break  # Ollama already exited; nothing to do
        fi
        # Only probe if the model is currently loaded — avoids resetting the
        # keep_alive unload timer when the model has intentionally been unloaded
        PS_RESPONSE=$(curl -s --max-time 10 http://localhost:11434/api/ps 2>&1)
        if ! echo "$PS_RESPONSE" | grep -q "\"${WATCHDOG_MODEL}\""; then
            bashio::log.info "Watchdog: model not loaded (keep_alive expired), skipping check."
            continue
        fi

        bashio::log.info "Watchdog: checking model '${WATCHDOG_MODEL}' health..."
        RESPONSE=$(curl -s --max-time 60 -X POST http://localhost:11434/api/generate \
            -d "{\"model\": \"${WATCHDOG_MODEL}\", \"prompt\": \"hi\", \"stream\": false, \"options\": {\"num_predict\": 1}}" 2>&1)
        if echo "$RESPONSE" | grep -q '"response"'; then
            bashio::log.info "Watchdog: model healthy."
        else
            bashio::log.warning "Watchdog: model '${WATCHDOG_MODEL}' is unresponsive (no 'response' field)."

            # Count triggers within the rolling window
            NOW=$(date +%s)
            echo "$NOW" >> "$WATCHDOG_TRIGGER_FILE"

            # Rewrite file keeping only timestamps within the window, count them
            RECENT_COUNT=0
            FRESH_LINES=""
            while IFS= read -r T; do
                if [ $((NOW - T)) -le $WATCHDOG_WINDOW ]; then
                    FRESH_LINES="${FRESH_LINES}${T}\n"
                    RECENT_COUNT=$((RECENT_COUNT + 1))
                fi
            done < "$WATCHDOG_TRIGGER_FILE"
            printf "%b" "$FRESH_LINES" > "$WATCHDOG_TRIGGER_FILE"

            if [ "$RECENT_COUNT" -gt "$WATCHDOG_MAX_TRIGGERS" ]; then
                bashio::log.error "Watchdog: FATAL — model unresponsive ${RECENT_COUNT} times in the last $((WATCHDOG_WINDOW / 60)) minutes (limit: ${WATCHDOG_MAX_TRIGGERS}). Giving up to avoid restart loop. Please check the logs and restart the addon manually."
                break  # Exit watchdog without restarting; addon stays running but unprotected
            fi

            bashio::log.warning "Watchdog: triggering restart (${RECENT_COUNT}/${WATCHDOG_MAX_TRIGGERS} within $((WATCHDOG_WINDOW / 60))m window)..."
            kill "$PID" "$WEB_PID" 2>/dev/null
            exit 1
        fi
    done
) &
WATCHDOG_PID=$!

wait "$PID" "$WEB_PID"
kill "$WATCHDOG_PID" 2>/dev/null
