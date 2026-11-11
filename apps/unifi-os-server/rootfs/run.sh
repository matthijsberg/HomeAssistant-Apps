#!/bin/bash
set -Eeuo pipefail

# -----------------------------------------------------------------------------
# Home Assistant App Entrypoint: UniFi OS Server (unifi_os_server)
# Zero-nested-containers supervisor with cgroup v2 support & auto-persistence
# -----------------------------------------------------------------------------

# Colors & Logging helpers
info() { echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $*"; }
notice() { echo "[NOTICE] $(date '+%Y-%m-%d %H:%M:%S') - $*"; }
warn() { echo "[WARN] $(date '+%Y-%m-%d %H:%M:%S') - $*"; }
error() { echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $*"; }

notice "Starting UniFi OS Server Home Assistant App..."

# 1. Parse Options from Home Assistant Supervisor
OPTIONS_FILE="/data/options.json"
SYSTEM_IP=""
LOG_LEVEL="info"
MEMORY_INIT=512
MEMORY_MAX=1536
SHOW_JOURNAL=false
SSL_CERT=""
SSL_KEY=""

if [ -f "$OPTIONS_FILE" ] && command -v jq >/dev/null 2>&1; then
    SYSTEM_IP=$(jq -r '.system_ip // empty' "$OPTIONS_FILE")
    LOG_LEVEL=$(jq -r '.log_level // "info"' "$OPTIONS_FILE")
    MEMORY_INIT=$(jq -r '.memory_init // 512' "$OPTIONS_FILE")
    MEMORY_MAX=$(jq -r '.memory_max // 1536' "$OPTIONS_FILE")
    SHOW_JOURNAL=$(jq -r '.show_journal // false' "$OPTIONS_FILE")
    SSL_CERT=$(jq -r '.ssl_cert // empty' "$OPTIONS_FILE")
    SSL_KEY=$(jq -r '.ssl_key // empty' "$OPTIONS_FILE")
fi

info "Loaded options: SYSTEM_IP='${SYSTEM_IP}', MEMORY_INIT=${MEMORY_INIT}M, MEMORY_MAX=${MEMORY_MAX}M, LOG_LEVEL='${LOG_LEVEL}'"

# 2. Dynamic Memory Scaling via Cgroup v2
if [ -f "/sys/fs/cgroup/memory.max" ]; then
    CGROUP_MAX=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "max")
    if [ "$CGROUP_MAX" != "max" ] && [ "$CGROUP_MAX" -gt 0 ] 2>/dev/null; then
        TOTAL_MB=$(( CGROUP_MAX / 1024 / 1024 ))
        AUTO_MAX=$(( TOTAL_MB * 45 / 100 ))
        if [ "$AUTO_MAX" -gt "$MEMORY_MAX" ]; then
            info "Cgroup v2 detected: ${TOTAL_MB} MB total container limit. Scaling JVM max to ${AUTO_MAX} MB."
            MEMORY_MAX="$AUTO_MAX"
        fi
    fi
fi

# 3. Storage Persistence under /data/uos_storage
STORAGE_ROOT="/data/uos_storage"
mkdir -p "${STORAGE_ROOT}"/{unifi,mongodb,postgresql,rabbitmq-ssl,persistent,unifi-core}
mkdir -p "${STORAGE_ROOT}/persistent/.config"
mkdir -p "${STORAGE_ROOT}/unifi-core/config"

# Symlink persistent paths if not already mounted
link_dir() {
    local target="$1"
    local source="$2"
    if [ ! -L "$target" ]; then
        if [ -d "$target" ] && [ ! -d "$source" ]; then
            cp -a "$target/." "$source/" 2>/dev/null || true
        fi
        rm -rf "$target"
        mkdir -p "$(dirname "$target")"
        ln -sf "$source" "$target"
    fi
}

link_dir "/var/lib/unifi" "${STORAGE_ROOT}/unifi"
link_dir "/var/lib/mongodb" "${STORAGE_ROOT}/mongodb"
link_dir "/var/lib/postgresql" "${STORAGE_ROOT}/postgresql"
link_dir "/etc/rabbitmq/ssl" "${STORAGE_ROOT}/rabbitmq-ssl"
link_dir "/persistent" "${STORAGE_ROOT}/persistent"

# Fix permissions
chown -R 1000:1000 "${STORAGE_ROOT}/unifi" 2>/dev/null || true
chown -R 1000:1000 "${STORAGE_ROOT}/mongodb" 2>/dev/null || true
chown -R 105:109 "${STORAGE_ROOT}/postgresql" 2>/dev/null || true # postgres:postgres

# 4. Map Backups to Host Storage Outside the Container (/backup/unifi)
if [ -d "/backup" ]; then
    mkdir -p "/backup/unifi/autobackup"
    mkdir -p "/var/lib/unifi/data"
    if [ ! -L "/var/lib/unifi/data/backup" ]; then
        if [ -d "/var/lib/unifi/data/backup" ]; then
            cp -a /var/lib/unifi/data/backup/. /backup/unifi/ 2>/dev/null || true
            rm -rf "/var/lib/unifi/data/backup"
        fi
        ln -sf "/backup/unifi" "/var/lib/unifi/data/backup"
    fi
    info "UniFi backup destination mapped to external host storage: /backup/unifi/"
fi

# 5. SSL Directory Integration (/ssl)
CERT_SOURCE=""
KEY_SOURCE=""

if [ -d "/ssl" ]; then
    if [ -n "$SSL_CERT" ] && [ -n "$SSL_KEY" ] && [ -f "/ssl/${SSL_CERT}" ] && [ -f "/ssl/${SSL_KEY}" ]; then
        CERT_SOURCE="/ssl/${SSL_CERT}"
        KEY_SOURCE="/ssl/${SSL_KEY}"
    elif [ -f "/ssl/fullchain.pem" ] && [ -f "/ssl/privkey.pem" ]; then
        CERT_SOURCE="/ssl/fullchain.pem"
        KEY_SOURCE="/ssl/privkey.pem"
    fi

    if [ -n "$CERT_SOURCE" ] && [ -n "$KEY_SOURCE" ]; then
        info "Applying SSL certificate from ${CERT_SOURCE} and key from ${KEY_SOURCE}..."
        mkdir -p "${STORAGE_ROOT}/unifi-core/config"
        cp -L "$CERT_SOURCE" "${STORAGE_ROOT}/unifi-core/config/server.crt"
        cp -L "$KEY_SOURCE" "${STORAGE_ROOT}/unifi-core/config/server.key"
        chmod 600 "${STORAGE_ROOT}/unifi-core/config/server.key"
        notice "Custom SSL certificates successfully deployed for UniFi OS Console."
    else
        info "No custom SSL certificates detected in /ssl. UniFi OS will manage internal certificates."
    fi
fi

# 6. Generate & Persist UOS UUID & Identity Strings
UUID_FILE="/data/uos_uuid"
if [ ! -f "$UUID_FILE" ]; then
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen > "$UUID_FILE"
    else
        python3 -c "import uuid; print(uuid.uuid4())" > "$UUID_FILE"
    fi
fi
UOS_UUID=$(cat "$UUID_FILE")
export UOS_UUID

# Set platform strings
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    export FIRMWARE_PLATFORM="linux-x64"
else
    export FIRMWARE_PLATFORM="linux-arm64"
fi

export APP_VERSION="6.0.19"
export APP_MODEL="UOSSERVER"
export PRODUCT_NAME="UniFi OS Server"

echo "$FIRMWARE_PLATFORM" > /usr/lib/platform 2>/dev/null || true
echo "$PRODUCT_NAME" > /usr/lib/product_name 2>/dev/null || true
echo "$APP_MODEL" > /usr/lib/app_model 2>/dev/null || true
echo "$APP_MODEL.0000000.v$APP_VERSION.0000000.000000.0000" > /usr/lib/version 2>/dev/null || true

# 7. Configure system.properties for Network Application
SYS_PROPS="/var/lib/unifi/system.properties"
mkdir -p "/var/lib/unifi"
touch "$SYS_PROPS"

set_prop() {
    local key="$1"
    local val="$2"
    if grep -q "^${key}=" "$SYS_PROPS" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$SYS_PROPS"
    else
        echo "${key}=${val}" >> "$SYS_PROPS"
    fi
}

set_prop "unifi.xms" "${MEMORY_INIT}"
set_prop "unifi.xmx" "${MEMORY_MAX}"
if [ -n "$SYSTEM_IP" ]; then
    set_prop "system_ip" "${SYSTEM_IP}"
fi

# 8. Dropzone Auto-Restore (.unf backups from /backup or /share/unifi-backup)
if [ ! -d "/var/lib/unifi/data/db" ] && [ ! -d "/var/lib/unifi/db" ]; then
    LATEST_UNF=""
    for search_dir in "/backup/unifi" "/backup" "/share/unifi-backup" "/share/backup"; do
        if [ -d "$search_dir" ]; then
            CANDIDATE=$(find "$search_dir" -maxdepth 2 -name "*.unf" -type f 2>/dev/null | head -n 1 || true)
            if [ -n "$CANDIDATE" ]; then
                LATEST_UNF="$CANDIDATE"
                break
            fi
        fi
    done

    if [ -n "$LATEST_UNF" ]; then
        notice "Found legacy UniFi backup file at '${LATEST_UNF}'."
        mkdir -p "/backup/unifi/autobackup"
        cp "$LATEST_UNF" "/backup/unifi/autobackup/autobackup_initial.unf" 2>/dev/null || true
        chown -R 1000:1000 "/backup/unifi" 2>/dev/null || true
        notice "Staged backup to /backup/unifi/autobackup/ for auto-migration."
    fi
fi

# 9. Idempotent PostgreSQL 16 Pre-Seeding
PG_DATA="/var/lib/postgresql/16/main"
PG_BIN="/usr/lib/postgresql/16/bin"
if [ ! -d "$PG_DATA" ] && [ -x "$PG_BIN/initdb" ]; then
    info "Initializing fresh PostgreSQL 16 cluster in ${PG_DATA}..."
    su - postgres -c "$PG_BIN/initdb -D '$PG_DATA' --encoding=UTF8 --locale=C.UTF-8"
fi

if [ -d "$PG_DATA" ] && [ -x "$PG_BIN/pg_ctl" ]; then
    info "Starting PostgreSQL temporary cluster for role & DB pre-seeding..."
    su - postgres -c "$PG_BIN/pg_ctl -D '$PG_DATA' -l /tmp/pg_init.log -w start" || true

    for role in "ulp-go" "unifi" "ucs-agent" "uid"; do
        su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${role}'\" | grep -q 1 || createuser -s '${role}'" 2>/dev/null || true
    done

    for dbname in "ulp-go" "ulp-go-syslog" "uid" "ucs-agent" "unifi-directory" "unifi-identity-update" "unifi"; do
        su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${dbname}'\" | grep -q 1 || createdb -O unifi '${dbname}'" 2>/dev/null || true
    done

    su - postgres -c "$PG_BIN/pg_ctl -D '$PG_DATA' -w stop" || true
    info "PostgreSQL pre-seeding completed cleanly."
fi

# 10. Start Service Supervision via systemctl3.py
notice "Starting UniFi OS Server services via supervisor..."

if [ "$SHOW_JOURNAL" = "true" ]; then
    exec /usr/bin/python3 /usr/bin/systemctl --init
else
    exec /usr/bin/python3 /usr/bin/systemctl --init >/dev/null 2>&1
fi
