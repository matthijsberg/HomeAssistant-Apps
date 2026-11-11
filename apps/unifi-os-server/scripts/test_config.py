#!/usr/bin/env python3
"""
Home Assistant Add-on Manifest & Schema Validator for unifi_os_server.
Supports both config.yaml (active) and config.yaml.disabled (staged prior to UniFi OS 6 release).
"""

import sys
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ACTIVE = REPO_ROOT / "config.yaml"
CONFIG_DISABLED = REPO_ROOT / "config.yaml.disabled"
BUILD_PATH = REPO_ROOT / "build.yaml"
TRANSLATIONS_PATH = REPO_ROOT / "translations" / "en.yaml"


def get_config_path() -> Path:
    if CONFIG_ACTIVE.exists():
        return CONFIG_ACTIVE
    if CONFIG_DISABLED.exists():
        return CONFIG_DISABLED
    print(f"❌ Neither config.yaml nor config.yaml.disabled found in {REPO_ROOT}")
    sys.exit(1)


def validate_config() -> None:
    cfg_path = get_config_path()
    print(f"Validating {cfg_path.name}...")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    required_keys = [
        "name",
        "version",
        "slug",
        "description",
        "arch",
        "startup",
        "boot",
        "init",
        "timeout",
        "backup",
        "ports",
        "options",
        "schema",
    ]
    for k in required_keys:
        if k not in cfg:
            print(f"❌ Missing required key in {cfg_path.name}: {k}")
            sys.exit(1)

    assert cfg["slug"] == "unifi_os_server", "slug must be unifi_os_server"
    assert cfg["init"] is False, "init must be false"
    assert cfg["timeout"] == 120, "timeout must be 120 for clean PostgreSQL/MongoDB shutdown"
    assert cfg["backup"] == "cold", "backup must be cold for consistent database snapshots"
    assert set(cfg[" privileged" if " privileged" in cfg else "privileged"]) == {
        "NET_ADMIN",
        "NET_RAW",
    }, "Only NET_ADMIN and NET_RAW capabilities are allowed"

    ports = cfg.get("ports", {})
    assert ports.get("11443/tcp") == 11443, "11443/tcp must map to 11443 for UOS Console & HA integration"
    assert ports.get("8080/tcp") == 8080, "8080/tcp must map to 8080 for seamless device inform"
    assert ports.get("3478/udp") == 3478, "3478/udp must map to 3478 for STUN"
    assert "5432/tcp" not in ports, "PostgreSQL port 5432 must never be exposed externally"
    assert "7443/tcp" not in ports, "SSO bypass port 7443 must never be exposed externally"

    options = cfg.get("options", {})
    schema = cfg.get("schema", {})
    assert set(options.keys()) == set(schema.keys()), "options and schema keys must match 1:1"

    assert TRANSLATIONS_PATH.exists(), "translations/en.yaml must exist"
    with open(TRANSLATIONS_PATH, "r", encoding="utf-8") as f:
        trans = yaml.safe_load(f)

    trans_cfg = trans.get("configuration", {})
    for opt_k in options:
        assert opt_k in trans_cfg, f"Option '{opt_k}' missing from translations/en.yaml"
        assert "name" in trans_cfg[opt_k], f"Option '{opt_k}' missing name in translations/en.yaml"
        assert "description" in trans_cfg[opt_k], f"Option '{opt_k}' missing description in translations/en.yaml"

    print(f"✓ {cfg_path.name} and translations/en.yaml passed all validation checks!")


def validate_build() -> None:
    print(f"Validating {BUILD_PATH.name}...")
    if not BUILD_PATH.exists():
        print(f"❌ build.yaml not found at {BUILD_PATH}")
        sys.exit(1)

    with open(BUILD_PATH, "r", encoding="utf-8") as f:
        bld = yaml.safe_load(f)

    assert "build_from" in bld, "build_from required in build.yaml"
    assert "amd64" in bld["build_from"], "amd64 required in build.yaml"
    assert "aarch64" in bld["build_from"], "aarch64 required in build.yaml"
    args = bld.get("args", {})
    assert "UOS_SERVER_VERSION" in args, "UOS_SERVER_VERSION required in build.yaml args"
    assert "INSTALLER_URL_AMD64" in args, "INSTALLER_URL_AMD64 required in build.yaml args"
    assert "INSTALLER_URL_ARM64" in args, "INSTALLER_URL_ARM64 required in build.yaml args"
    print("✓ build.yaml passed all validation checks!")


if __name__ == "__main__":
    validate_config()
    validate_build()
    print("✓ All Home Assistant Add-on manifest checks passed!")
