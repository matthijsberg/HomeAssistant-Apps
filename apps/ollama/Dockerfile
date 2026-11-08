FROM ollama/ollama:latest

ARG DEBIAN_FRONTEND=noninteractive
ARG BASHIO_VERSION=v0.19.0

# Install base tools and Mesa Vulkan drivers from PPA
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg2 \
    pciutils \
    clinfo \
    jq \
    python3 \
    python3-requests \
    software-properties-common \
    gpg-agent \
    && add-apt-repository ppa:ernstp/mesarc \
    && apt-get update && apt-get install -y --no-install-recommends \
    mesa-vulkan-drivers \
    libvulkan1 \
    vulkan-tools \
    && rm -rf /var/lib/apt/lists/*

# Install Bashio for Home Assistant add-on integration
RUN curl -J -L -o /tmp/bashio.tar.gz \
    "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" && \
    mkdir /tmp/bashio && \
    tar zxvf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio && \
    mv /tmp/bashio/lib /usr/lib/bashio && \
    ln -s /usr/lib/bashio/bashio /usr/bin/bashio && \
    rm -rf /tmp/bashio

COPY run.sh /run.sh
COPY web_server.py /web_server.py
COPY index.html /index.html

RUN chmod a+x /run.sh

ENTRYPOINT ["/run.sh"]
