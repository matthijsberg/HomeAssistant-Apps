"""Unit tests validating Home Assistant add-on manifests and configurations."""

import os
from pathlib import Path

APP_ROOT = Path(__file__).parent.parent
CONFIG_PATH = APP_ROOT / "config.yaml"
BUILD_PATH = APP_ROOT / "build.yaml"
TRANSLATIONS_PATH = APP_ROOT / "translations" / "en.yaml"
DOCKERFILE_PATH = APP_ROOT / "Dockerfile"
RUN_SH_PATH = APP_ROOT / "run.sh"


def test_config_yaml_manifest(config_yaml):
    assert config_yaml["name"] == "Ollama (Vulkan)"
    assert config_yaml["slug"] == "ollama_vulkan"
    assert config_yaml["version"] == "0.8.0"
    assert "amd64" in config_yaml["arch"]
    assert config_yaml["startup"] == "application"
    assert config_yaml["boot"] == "auto"

    # Ingress checks
    assert config_yaml.get("ingress") is True
    assert config_yaml.get("ingress_port") == 8099
    assert config_yaml.get("ingress_entry") == "/"

    # Hardware devices check: /dev/dri passthrough for Vulkan iGPU
    assert "devices" in config_yaml
    assert any("/dev/dri" in dev for dev in config_yaml["devices"])

    # Ports check: 11434 and 8099 mapped
    assert "ports" in config_yaml
    assert "11434/tcp" in config_yaml["ports"]
    assert "8099/tcp" in config_yaml["ports"]

    # Privileged execution checks for GPU & raw I/O
    assert "privileged" in config_yaml
    assert "SYS_ADMIN" in config_yaml["privileged"]
    assert "SYS_RAWIO" in config_yaml["privileged"]
    assert "SYS_PTRACE" in config_yaml["privileged"]
    assert config_yaml.get("full_access") is True

    # Storage mapping checks
    assert "map" in config_yaml
    assert "share:rw" in config_yaml["map"]

    # Options check
    opts = config_yaml.get("options", {})
    assert "model" in opts
    assert opts.get("keep_alive") == "5m"
    assert opts.get("context_length") == 8192
    assert opts.get("max_loaded_models") == 2
    assert opts.get("enable_vulkan") is True
    assert opts.get("disable_flash_attention") is False

    # Schema check
    schema = config_yaml.get("schema", {})
    assert "model" in schema
    assert "keep_alive" in schema
    assert "num_parallel" in schema
    assert "context_length" in schema
    assert "enable_vulkan" in schema
    assert "disable_flash_attention" in schema


def test_build_yaml_manifest(build_yaml):
    assert "build_from" in build_yaml
    assert "amd64" in build_yaml["build_from"]
    assert "ollama/ollama" in build_yaml["build_from"]["amd64"]
    assert "args" in build_yaml
    assert "BASHIO_VERSION" in build_yaml["args"]


def test_translations_coverage(config_yaml, translations_yaml):
    config_keys = set(config_yaml.get("options", {}).keys())
    trans_keys = set(translations_yaml.get("configuration", {}).keys())

    missing = config_keys - trans_keys
    assert not missing, f"Missing English translations for options: {missing}"


def test_dockerfile_contents():
    assert DOCKERFILE_PATH.exists()
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "FROM ollama/ollama:latest" in content
    assert "mesa-vulkan-drivers" in content
    assert "vulkan-tools" in content
    assert "bashio" in content
    assert "ENTRYPOINT [\"/run.sh\"]" in content


def test_run_script_attributes_and_invariants():
    assert RUN_SH_PATH.exists()
    assert os.access(RUN_SH_PATH, os.X_OK), "run.sh must be executable"
    content = RUN_SH_PATH.read_text(encoding="utf-8")

    # Critical Intel Arc Vulkan workarounds & performance optimizations
    assert "GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1" in content
    assert "GGML_VK_DISABLE_COOPMAT=1" in content
    assert "GGML_VK_PREFER_HOST_MEMORY=1" in content
    assert "VK_DRIVER_FILES" in content
    assert "MESA_SHADER_CACHE_DIR" in content
    assert "ANV_ENABLE_PIPELINE_CACHE=1" in content
    assert "OLLAMA_IGPU_ENABLE=1" in content
    assert "OLLAMA_FLASH_ATTENTION" in content
    assert "OLLAMA_KV_CACHE_TYPE=q8_0" in content
    assert "OLLAMA_NEW_ENGINE=1" in content

    # Watchdog invariants
    assert "WATCHDOG_MAX_TRIGGERS=3" in content
    assert "WATCHDOG_WINDOW=1800" in content
