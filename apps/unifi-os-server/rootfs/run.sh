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
ENABLE_INNERSPACE=false
USE_HA_SSL=true
SSL_CERT="fullchain.pem"
SSL_KEY="privkey.pem"

if [ -f "$OPTIONS_FILE" ] && command -v jq >/dev/null 2>&1; then
    SYSTEM_IP=$(jq -r '.system_ip // empty' "$OPTIONS_FILE")
    LOG_LEVEL=$(jq -r '.log_level // "info"' "$OPTIONS_FILE")
    MEMORY_INIT=$(jq -r '.memory_init // 512' "$OPTIONS_FILE")
    MEMORY_MAX=$(jq -r '.memory_max // 1536' "$OPTIONS_FILE")
    SHOW_JOURNAL=$(jq -r '.show_journal // false' "$OPTIONS_FILE")
    ENABLE_INNERSPACE=$(jq -r 'if has("enable_innerspace") then .enable_innerspace else false end' "$OPTIONS_FILE")
    USE_HA_SSL=$(jq -r 'if has("use_ha_ssl") then .use_ha_ssl else true end' "$OPTIONS_FILE")
    SSL_CERT=$(jq -r '.ssl_cert // "fullchain.pem"' "$OPTIONS_FILE")
    SSL_KEY=$(jq -r '.ssl_key // "privkey.pem"' "$OPTIONS_FILE")
fi

info "Loaded options: SYSTEM_IP='${SYSTEM_IP}', MEMORY_INIT=${MEMORY_INIT}M, MEMORY_MAX=${MEMORY_MAX}M, LOG_LEVEL='${LOG_LEVEL}', ENABLE_INNERSPACE=${ENABLE_INNERSPACE}, USE_HA_SSL=${USE_HA_SSL}"

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
mkdir -p "${STORAGE_ROOT}/unifi"/{data,logs,run}
mkdir -p "${STORAGE_ROOT}/persistent/.config"
mkdir -p "${STORAGE_ROOT}/unifi-core/config/http"

# Symlink persistent paths if not already mounted
link_dir() {
    local target="$1"
    local source="$2"
    if [ ! -L "$target" ]; then
        if [ -d "$target" ] && [ -z "$(ls -A "$source" 2>/dev/null)" ]; then
            cp -a "$target/." "$source/" 2>/dev/null || true
        fi
        rm -rf "$target"
        mkdir -p "$(dirname "$target")"
        ln -sf "$source" "$target"
    fi
}

link_dir "/data/unifi" "${STORAGE_ROOT}/unifi"
link_dir "/var/lib/unifi" "${STORAGE_ROOT}/unifi"
link_dir "/var/lib/mongodb" "${STORAGE_ROOT}/mongodb"
link_dir "/var/lib/postgresql" "${STORAGE_ROOT}/postgresql"
link_dir "/etc/rabbitmq/ssl" "${STORAGE_ROOT}/rabbitmq-ssl"
link_dir "/persistent" "${STORAGE_ROOT}/persistent"
link_dir "/data/unifi-core" "${STORAGE_ROOT}/unifi-core"
link_dir "/data/unifi-innerspace" "${STORAGE_ROOT}/unifi-innerspace"
link_dir "/data/unifi-matter-controller" "${STORAGE_ROOT}/unifi-matter-controller"

# Fix permissions using actual system UIDs/GIDs (never hardcoded numbers)
mkdir -p \
    /persistent/.config \
    /data/unifi-core/config/http \
    /var/opt/unifi/tmp \
    "${STORAGE_ROOT}/unifi" \
    "${STORAGE_ROOT}/mongodb" \
    "${STORAGE_ROOT}/unifi-matter-controller" \
    "${STORAGE_ROOT}/unifi-innerspace" \
    "${STORAGE_ROOT}/postgresql" \
    "${STORAGE_ROOT}/rabbitmq-ssl"
touch /persistent/.migrated60
chmod 755 "${STORAGE_ROOT}"
if id unifi >/dev/null 2>&1; then
    chown -R unifi:unifi "${STORAGE_ROOT}/unifi" "${STORAGE_ROOT}/mongodb" "${STORAGE_ROOT}/unifi-matter-controller" /var/opt/unifi /etc/unifi-matter-controller /etc/default/unifi 2>/dev/null || true
    chown -h unifi:unifi /data/unifi /var/lib/unifi /data/unifi-matter-controller 2>/dev/null || true
else
    chown -R 1000:1000 "${STORAGE_ROOT}/unifi" "${STORAGE_ROOT}/mongodb" 2>/dev/null || true
fi
chown -R unifi-innerspace:unifi-innerspace "${STORAGE_ROOT}/unifi-innerspace" /var/log/unifi-innerspace 2>/dev/null || true
if [ -d /usr/share/unifi-matter-controller/paa-certs ]; then
    mkdir -p "${STORAGE_ROOT}/unifi-matter-controller/attestation/paa-trust-store" "${STORAGE_ROOT}/unifi-matter-controller/attestation/dac-revocation"
    cp -pf /usr/share/unifi-matter-controller/paa-certs/*.der "${STORAGE_ROOT}/unifi-matter-controller/attestation/paa-trust-store/" 2>/dev/null || true
    cp -pf /usr/share/unifi-matter-controller/paa-certs/*.pem "${STORAGE_ROOT}/unifi-matter-controller/attestation/paa-trust-store/" 2>/dev/null || true
    [ -f /usr/share/unifi-matter-controller/dac-revocation/revocation_set.json ] && cp -pf /usr/share/unifi-matter-controller/dac-revocation/revocation_set.json "${STORAGE_ROOT}/unifi-matter-controller/attestation/dac-revocation/revocation_set.json" 2>/dev/null || true
    chown -R unifi:unifi "${STORAGE_ROOT}/unifi-matter-controller" 2>/dev/null || true
fi
chown -R postgres:postgres "${STORAGE_ROOT}/postgresql" /var/run/postgresql 2>/dev/null || true
chown -R rabbitmq:rabbitmq "${STORAGE_ROOT}/rabbitmq-ssl" 2>/dev/null || true
mkdir -p /var/lib/fluent-bit-audit/storage
chown -R audit-shipper:audit /var/lib/fluent-bit-audit 2>/dev/null || true

# Apply cap.conf User=root override directly on unifi-core.service for systemctl3.py compatibility
if [ -f /usr/lib/systemd/system/unifi-core.service ]; then
    sed -i 's/^User=unifi-core$/User=root/' /usr/lib/systemd/system/unifi-core.service 2>/dev/null || true
fi

# Enable static unifi-mongodb.service so systemctl3.py starts MongoDB alongside multi-user.target
mkdir -p /etc/systemd/system/multi-user.target.wants
if [ -f /usr/lib/systemd/system/unifi-mongodb.service ]; then
    ln -snf /usr/lib/systemd/system/unifi-mongodb.service /etc/systemd/system/multi-user.target.wants/unifi-mongodb.service
fi
if [ -f /lib/systemd/system/unifi-matter-controller.service ]; then
    ln -snf /lib/systemd/system/unifi-matter-controller.service /etc/systemd/system/multi-user.target.wants/unifi-matter-controller.service
fi
if [ "$ENABLE_INNERSPACE" = "true" ] && [ -f /lib/systemd/system/unifi-innerspace.service ]; then
    ln -snf /lib/systemd/system/unifi-innerspace.service /etc/systemd/system/multi-user.target.wants/unifi-innerspace.service
    info "UniFi InnerSpace enabled."
else
    rm -f /etc/systemd/system/multi-user.target.wants/unifi-innerspace.service
    info "UniFi InnerSpace disabled (enable_innerspace=${ENABLE_INNERSPACE})."
fi

# Ensure RabbitMQ TLS certificates exist before rabbitmq-server unit starts
if [ -x /sbin/uos-rabbitmq-gen-certs-wrapper ] && [ ! -f /etc/rabbitmq/ssl/01.pem ]; then
    /sbin/uos-rabbitmq-gen-certs-wrapper || true
fi

# 4. Map Backups to Isolated Host Storage Outside the Container (/backup/unifi-os-server)
UOS_BACKUP_DIR="/backup/unifi-os-server"
if [ -d "/backup" ]; then
    mkdir -p "${UOS_BACKUP_DIR}/autobackup"
    mkdir -p "/var/lib/unifi/data"
    if [ ! -L "/var/lib/unifi/data/backup" ]; then
        if [ -d "/var/lib/unifi/data/backup" ]; then
            cp -a /var/lib/unifi/data/backup/. "${UOS_BACKUP_DIR}/" 2>/dev/null || true
            rm -rf "/var/lib/unifi/data/backup"
        fi
        ln -sf "${UOS_BACKUP_DIR}" "/var/lib/unifi/data/backup"
    fi
    chown -R unifi:unifi "${UOS_BACKUP_DIR}" 2>/dev/null || chown -R 1000:1000 "${UOS_BACKUP_DIR}" 2>/dev/null || true
    info "UniFi backup destination mapped to external host storage: ${UOS_BACKUP_DIR}/"
fi

# 5. SSL Directory Integration (/ssl -> synced via uos-supervisor-shim to unifi-core userCertificates API)
CORE_CFG_DIR="${STORAGE_ROOT}/unifi-core/config"
CORE_CRT="${CORE_CFG_DIR}/unifi-core.crt"
CORE_KEY="${CORE_CFG_DIR}/unifi-core.key"
CORE_CRT_DEFAULT="${CORE_CFG_DIR}/unifi-core.crt.default"
CORE_KEY_DEFAULT="${CORE_CFG_DIR}/unifi-core.key.default"
mkdir -p "${CORE_CFG_DIR}"
rm -f "${CORE_CFG_DIR}/server.crt" "${CORE_CFG_DIR}/server.key"

# Restore UniFi's original self-signed cert if previously replaced directly on disk
if [ -f "${CORE_CRT_DEFAULT}" ] && [ -f "${CORE_KEY_DEFAULT}" ]; then
    cp -f "${CORE_CRT_DEFAULT}" "${CORE_CRT}"
    cp -f "${CORE_KEY_DEFAULT}" "${CORE_KEY}"
    chmod 644 "${CORE_CRT}"
    chmod 600 "${CORE_KEY}"
    rm -f "${CORE_CRT_DEFAULT}" "${CORE_KEY_DEFAULT}"
fi

if [ "$USE_HA_SSL" = "true" ] && [ -d "/ssl" ]; then
    info "Home Assistant SSL integration enabled (cert='${SSL_CERT}', key='${SSL_KEY}'); uos-supervisor-shim will sync valid certificates."
elif [ "$USE_HA_SSL" != "true" ]; then
    info "use_ha_ssl is disabled; UniFi OS will use its built-in self-signed certificate."
else
    info "No /ssl directory mounted; UniFi OS will use its built-in self-signed certificate."
fi

# 5b. Disable in-container UniFi OS / Application Auto-Update Schedules (updates are managed by Home Assistant)
if command -v node24 >/dev/null 2>&1 && [ -d "/usr/share/unifi-core/app/node_modules/js-yaml" ]; then
    node24 -e '
        const fs = require("fs");
        const { load, dump, CORE_SCHEMA } = require("/usr/share/unifi-core/app/node_modules/js-yaml");
        const cfgDir = process.argv[1];
        const fwPath = `${cfgDir}/firmware.yaml`;
        if (fs.existsSync(fwPath)) {
            const fw = load(fs.readFileSync(fwPath, "utf8"), { schema: CORE_SCHEMA }) || {};
            fw.autoUpdate = { schedule: null, includeApplications: false, preferencesPrompt: null };
            fw.schedule = null;
            fs.writeFileSync(fwPath, dump(fw), "utf8");
        }
        const prefsPath = `${cfgDir}/apps.userPrefs.yaml`;
        if (fs.existsSync(prefsPath)) {
            const prefs = load(fs.readFileSync(prefsPath, "utf8"), { schema: CORE_SCHEMA }) || {};
            prefs.updateSchedules = {};
            fs.writeFileSync(prefsPath, dump(prefs), "utf8");
        }
    ' "${CORE_CFG_DIR}" && info "Disabled UniFi OS in-container auto-update schedules (updates managed via Home Assistant)." || warn "Failed to update UniFi OS auto-update settings."
fi

# 6. Generate & Persist UOS UUID (must be UUIDv5 — UniFi Network validates version == 5)
UUID_FILE="/data/uos_uuid"
NEED_UUID=true
if [ -f "$UUID_FILE" ]; then
    if python3 -c "import uuid, sys; u = uuid.UUID(open('$UUID_FILE').read().strip()); sys.exit(0 if u.version == 5 else 1)" 2>/dev/null; then
        NEED_UUID=false
    fi
fi
if [ "$NEED_UUID" = "true" ]; then
    SEED=$(cat /etc/machine-id 2>/dev/null || hostname || echo "unifi-os-server")
    python3 -c "import uuid, sys; print(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1]))" "$SEED" > "$UUID_FILE"
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

export APP_VERSION="6.0.21"
export APP_MODEL="UOSSERVER"
export PRODUCT_NAME="UniFi OS Server"

echo "$FIRMWARE_PLATFORM" > /usr/lib/platform 2>/dev/null || true
echo "$PRODUCT_NAME" > /usr/lib/product_name 2>/dev/null || true
echo "$APP_MODEL" > /usr/lib/app_model 2>/dev/null || true
echo "$APP_MODEL.0000000.v$APP_VERSION.0000000.000000.0000" > /usr/lib/version 2>/dev/null || true

# 7. Configure system.properties for Network Application
SYS_PROPS="/data/unifi/data/system.properties"
mkdir -p "/data/unifi/data"
touch "$SYS_PROPS"
chown unifi:unifi "$SYS_PROPS" 2>/dev/null || true

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
    for search_dir in "${UOS_BACKUP_DIR}" "/backup/unifi" "/backup" "/share/unifi-backup" "/share/backup"; do
        if [ -d "$search_dir" ]; then
            CANDIDATE=$(find "$search_dir" -maxdepth 2 -name "*.unf" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2- || true)
            if [ -n "$CANDIDATE" ]; then
                LATEST_UNF="$CANDIDATE"
                break
            fi
        fi
    done

    if [ -n "$LATEST_UNF" ]; then
        notice "Found legacy UniFi backup file at '${LATEST_UNF}'."
        mkdir -p "${UOS_BACKUP_DIR}/autobackup"
        cp "$LATEST_UNF" "${UOS_BACKUP_DIR}/autobackup/autobackup_initial.unf" 2>/dev/null || true
        chown -R unifi:unifi "${UOS_BACKUP_DIR}" 2>/dev/null || chown -R 1000:1000 "${UOS_BACKUP_DIR}" 2>/dev/null || true
        notice "Staged backup to ${UOS_BACKUP_DIR}/autobackup/ for auto-migration."
    fi
fi

# 9. Idempotent PostgreSQL 14 Cluster Initialization & Pre-Seeding
PG_VER="14"
if [ ! -x "/usr/lib/postgresql/14/bin/initdb" ] && [ -x "/usr/lib/postgresql/16/bin/initdb" ]; then
    PG_VER="16"
fi
mkdir -p /var/run/postgresql /var/log/postgresql "/data/postgresql/${PG_VER}"
chown -R postgres:postgres /var/run/postgresql /var/log/postgresql /data/postgresql

if command -v pg_createcluster >/dev/null 2>&1; then
    for cluster_cfg in /etc/default/postgresql/${PG_VER}-*; do
        [ -f "$cluster_cfg" ] || continue
        (
            set -a
            # shellcheck disable=SC1090
            source "$cluster_cfg"
            set +a
            CLUSTER_DIR="${DIR:-/data/postgresql/${PG_VER}/${CLUSTER_NAME}}"
            if [ ! -e "${CLUSTER_DIR}/.configured" ] || [ ! -s "${CLUSTER_DIR}/conf/pg_hba.conf" ]; then
                info "Initializing PostgreSQL cluster ${PG_VER}-${CLUSTER_NAME} on port ${CLUSTER_PORT}..."
                rm -rf "${CLUSTER_DIR}"
                mkdir -p "${CLUSTER_DIR}/conf" "${CLUSTER_DIR}/data" "/etc/postgresql/${PG_VER}"
                chown -R postgres:postgres "${CLUSTER_DIR}" "/etc/postgresql/${PG_VER}"
                ln -snf "${CLUSTER_DIR}/conf" "/etc/postgresql/${PG_VER}/${CLUSTER_NAME}"
                pg_dropcluster "${PG_VER}" "${CLUSTER_NAME}" 2>/dev/null || true
                # shellcheck disable=SC2086
                pg_createcluster -d "${CLUSTER_DIR}/data" -e "${ENCODING:-UTF-8}" -p "${CLUSTER_PORT:-5432}" ${CLUSTER_ARGS:-} "${PG_VER}" "${CLUSTER_NAME}" -- ${INITARGS:---auth=trust --auth-local=trust}
                touch "${CLUSTER_DIR}/.configured"
                chown -R postgres:postgres "${CLUSTER_DIR}"
            else
                mkdir -p "/etc/postgresql/${PG_VER}"
                ln -snf "${CLUSTER_DIR}/conf" "/etc/postgresql/${PG_VER}/${CLUSTER_NAME}"
            fi
            # Enable concrete instance unit so systemctl3.py starts both 14-main and 14-apps at boot
            mkdir -p /etc/systemd/system/multi-user.target.wants
            ln -snf /usr/lib/systemd/system/postgresql@.service "/etc/systemd/system/multi-user.target.wants/postgresql@${PG_VER}-${CLUSTER_NAME}.service"
        )
    done

    info "Starting PostgreSQL ${PG_VER}-main temporarily for role & DB pre-seeding..."
    pg_ctlcluster "${PG_VER}" main start || true
    for role in "ulp-go" "unifi" "unifi-core" "ucs-agent" "uid"; do
        su - postgres -c "psql -p 5432 -tc \"SELECT 1 FROM pg_roles WHERE rolname='${role}'\" | grep -q 1 || createuser -p 5432 -s '${role}'" 2>/dev/null || true
    done
    for dbname in "ulp-go" "ulp-go-syslog" "uid" "ucs-agent" "unifi-directory" "unifi-identity-update" "unifi" "unifi-core"; do
        su - postgres -c "psql -p 5432 -tc \"SELECT 1 FROM pg_database WHERE datname='${dbname}'\" | grep -q 1 || createdb -p 5432 -O unifi '${dbname}'" 2>/dev/null || true
    done
    pg_ctlcluster "${PG_VER}" main stop || true
    info "PostgreSQL pre-seeding completed cleanly."
else
    PG_DATA="/var/lib/postgresql/${PG_VER}/main"
    PG_BIN="/usr/lib/postgresql/${PG_VER}/bin"
    if [ ! -d "$PG_DATA" ] && [ -x "$PG_BIN/initdb" ]; then
        info "Initializing fresh PostgreSQL ${PG_VER} cluster in ${PG_DATA}..."
        mkdir -p "/var/lib/postgresql/${PG_VER}"
        chown -R postgres:postgres /var/lib/postgresql
        su - postgres -c "$PG_BIN/initdb -D '$PG_DATA' --encoding=UTF8 --locale=C.UTF-8"
    fi
    if [ -d "$PG_DATA" ] && [ -x "$PG_BIN/pg_ctl" ]; then
        su - postgres -c "$PG_BIN/pg_ctl -D '$PG_DATA' -l /tmp/pg_init.log -w start" || true
        for role in "ulp-go" "unifi" "unifi-core" "ucs-agent" "uid"; do
            su - postgres -c "$PG_BIN/psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${role}'\" | grep -q 1 || $PG_BIN/createuser -s '${role}'" 2>/dev/null || true
        done
        for dbname in "ulp-go" "ulp-go-syslog" "uid" "ucs-agent" "unifi-directory" "unifi-identity-update" "unifi" "unifi-core"; do
            su - postgres -c "$PG_BIN/psql -tc \"SELECT 1 FROM pg_database WHERE datname='${dbname}'\" | grep -q 1 || $PG_BIN/createdb -O unifi '${dbname}'" 2>/dev/null || true
        done
        su - postgres -c "$PG_BIN/pg_ctl -D '$PG_DATA' -w stop" || true
    fi
fi

# 10. Provide lightweight /dev/log syslog sink (or logger fallback), D-Bus system daemon, systemd1 D-Bus shim
if [ ! -S /dev/log ]; then
    if [ -w /dev ] && command -v python3 >/dev/null 2>&1; then
        python3 -c '
import os, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind("/dev/log")
os.chmod("/dev/log", 0o666)
while True:
    s.recv(8192)
' >/dev/null 2>&1 &
        for _ in $(seq 1 10); do
            [ -S /dev/log ] && break
            sleep 0.1
        done
    elif [ -x /usr/bin/logger ] && [ ! -x /usr/bin/logger.real ]; then
        mv /usr/bin/logger /usr/bin/logger.real
        printf '#!/bin/sh\n/usr/bin/logger.real "$@" 2>/dev/null || true\n' > /usr/bin/logger
        chmod 755 /usr/bin/logger
    fi
fi
if command -v dbus-daemon >/dev/null 2>&1; then
    mkdir -p /run/dbus /var/run/dbus
    rm -f /run/dbus/pid /run/dbus/messagebus.pid
    dbus-daemon --system --fork || true
    if [ -x /usr/local/bin/systemd-dbus-shim.py ]; then
        /usr/bin/python3 /usr/local/bin/systemd-dbus-shim.py >/var/log/systemd-dbus-shim.log 2>&1 &
        for _ in $(seq 1 20); do
            if dbus-send --system --dest=org.freedesktop.DBus --type=method_call --print-reply \
                /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.freedesktop.systemd1 2>/dev/null | grep -q "boolean true"; then
                break
            fi
            sleep 0.2
        done
    fi
fi

if [ -x /usr/local/bin/uos-supervisor-shim.mjs ] && [ -x /usr/bin/node24 ]; then
    /usr/bin/node24 /usr/local/bin/uos-supervisor-shim.mjs >/var/log/uos-supervisor-shim.log 2>&1 &
fi

notice "Starting UniFi OS Server services via supervisor..."

if [ "$SHOW_JOURNAL" = "true" ]; then
    exec /usr/bin/python3 /usr/bin/systemctl --init
else
    exec /usr/bin/python3 /usr/bin/systemctl --init >/dev/null 2>&1
fi
