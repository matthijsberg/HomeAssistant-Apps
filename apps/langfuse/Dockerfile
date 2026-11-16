ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:trixie
FROM ghcr.io/langfuse/langfuse:4.81.0 AS langfuse-web-source
FROM ghcr.io/langfuse/langfuse-worker:4.81.0 AS langfuse-worker-source
FROM chrislusf/seaweedfs:4.53 AS seaweedfs-source
FROM clickhouse/clickhouse-server:26.3-alpine AS clickhouse-source

FROM --platform=$BUILDPLATFORM golang:1.27.4-trixie AS migrate-builder
ARG TARGETARCH
RUN mkdir -p /out && git clone --branch v4.20.1 --depth 1 https://github.com/golang-migrate/migrate.git /src \
    && cd /src \
    && case "${TARGETARCH:-amd64}" in \
         aarch64) goarch=arm64 ;; \
         *) goarch="${TARGETARCH:-amd64}" ;; \
       esac \
    && CGO_ENABLED=0 GOOS=linux GOARCH="${goarch}" go build -ldflags='-s -w -X main.Version=4.20.1' -tags 'clickhouse file' -o /out/migrate ./cmd/migrate

FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies in Debian: Node.js, PostgreSQL 16 (via official pgdg repo), Redis, Nginx, gosu, tools
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    lsb-release \
    ca-certificates \
    jq \
    openssl \
    redis-server \
    nginx \
    gosu \
    bash \
    procps \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    nodejs \
    postgresql-16 \
    postgresql-contrib-16 \
    && ln -s /usr/sbin/gosu /usr/local/bin/su-exec \
    && ln -s /usr/lib/postgresql/16/bin/* /usr/local/bin/ \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy golang-migrate CLI (built from source with Go 1.27.4, clickhouse + file drivers only)
COPY --from=migrate-builder /out/migrate /usr/local/bin/migrate
RUN chmod +x /usr/local/bin/migrate

# Copy binaries and global node modules (Prisma CLI) from Langfuse Web
COPY --from=langfuse-web-source /usr/local/bin /usr/local/bin
COPY --from=langfuse-web-source /usr/local/lib/node_modules /usr/local/lib/node_modules

# Copy ClickHouse binary and config from clickhouse-source (native glibc binary)
COPY --from=clickhouse-source /usr/bin/clickhouse /usr/bin/clickhouse
RUN ln -s /usr/bin/clickhouse /usr/bin/clickhouse-server \
    && ln -s /usr/bin/clickhouse /usr/bin/clickhouse-client \
    && mkdir -p /etc/clickhouse-server /var/lib/clickhouse /var/log/clickhouse-server
COPY --from=clickhouse-source /etc/clickhouse-server /etc/clickhouse-server

# Copy SeaweedFS binary
COPY --from=seaweedfs-source /usr/bin/weed /usr/bin/weed

# Copy Langfuse Web assets to pristine location (for runtime base-path substitution)
COPY --from=langfuse-web-source /app /opt/langfuse-web-pristine

# Copy Langfuse Worker
COPY --from=langfuse-worker-source /app /opt/langfuse-worker

ENV PATH="/usr/local/bin:/usr/lib/postgresql/16/bin:/opt/langfuse-web/node_modules/.bin:$PATH"

# Setup directory structure
RUN mkdir -p /data /opt/langfuse-web /run /var/log/nginx

# Copy rootfs containing S6-overlay services and scripts
COPY rootfs /

EXPOSE 8099 3000
