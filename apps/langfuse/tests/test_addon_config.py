import os
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
BUILD_PATH = REPO_ROOT / "build.yaml"


def test_config_yaml_structure():
    assert CONFIG_PATH.exists()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert cfg["name"] == "Langfuse"
    assert cfg["slug"] == "langfuse"
    assert cfg["version"].startswith("4.")
    assert cfg["init"] is False
    assert "amd64" in cfg["arch"]
    assert cfg["ingress"] is True
    assert cfg["ingress_port"] == 8099
    assert cfg["timeout"] == 120
    assert cfg["backup"] == "cold"


def test_dynamic_port_mapping():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    ports = cfg.get("ports", {})
    assert "3000/tcp" in ports
    assert ports["3000/tcp"] is None, "3000/tcp must be null by default to allow optional LAN mapping"


def test_build_yaml_structure():
    assert BUILD_PATH.exists()
    with open(BUILD_PATH, "r", encoding="utf-8") as f:
        bld = yaml.safe_load(f)

    assert "build_from" in bld
    assert "amd64" in bld["build_from"]
    assert "LANGFUSE_VERSION" in bld.get("args", {})
    assert "CLICKHOUSE_VERSION" in bld.get("args", {})
    assert "SEAWEEDFS_VERSION" in bld.get("args", {})


def test_translations_en():
    trans_path = REPO_ROOT / "translations" / "en.yaml"
    assert trans_path.exists()
    with open(trans_path, "r", encoding="utf-8") as f:
        trans = yaml.safe_load(f)
    assert "configuration" in trans
    assert "admin_email" in trans["configuration"]
    assert "retention_days" in trans["configuration"]


def test_clickhouse_memory_limits_configured():
    config_mem_xml = REPO_ROOT / "rootfs" / "etc" / "clickhouse-server" / "config.d" / "01-memory.xml"
    users_mem_xml = REPO_ROOT / "rootfs" / "etc" / "clickhouse-server" / "users.d" / "01-memory.xml"
    init_config_sh = REPO_ROOT / "rootfs" / "usr" / "bin" / "init_config.sh"
    ch_deps = REPO_ROOT / "rootfs" / "etc" / "s6-overlay" / "s6-rc.d" / "clickhouse" / "dependencies"
    worker_run = REPO_ROOT / "rootfs" / "etc" / "s6-overlay" / "s6-rc.d" / "langfuse-worker" / "run"

    assert config_mem_xml.exists(), "01-memory.xml must exist in config.d"
    with open(config_mem_xml, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<max_server_memory_usage>" in content
    assert "<max_server_memory_usage_to_ram_ratio>0.0" in content

    assert users_mem_xml.exists(), "01-memory.xml must exist in users.d"
    with open(users_mem_xml, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<max_memory_usage>" in content

    with open(init_config_sh, "r", encoding="utf-8") as f:
        sh_content = f.read()
    assert "max_server_memory_usage" in sh_content
    assert "CH_MEM_BYTES" in sh_content

    with open(ch_deps, "r", encoding="utf-8") as f:
        deps_content = f.read()
    assert "init-config" in deps_content, "clickhouse must depend on init-config"

    with open(worker_run, "r", encoding="utf-8") as f:
        worker_content = f.read()
    assert "ha_sensor_reporter.js &" not in worker_content, "worker run must not background ha_sensor_reporter"

