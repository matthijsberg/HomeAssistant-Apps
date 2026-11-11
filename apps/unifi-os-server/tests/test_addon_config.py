"""Pytest suite for UniFi OS Server Home Assistant App scaffolding, manifest, and OKF v0.2 bundle."""

from pathlib import Path
import yaml

ADDON_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ACTIVE = ADDON_ROOT / "config.yaml"
CONFIG_DISABLED = ADDON_ROOT / "config.yaml.disabled"
BUILD_PATH = ADDON_ROOT / "build.yaml"
TRANSLATIONS_PATH = ADDON_ROOT / "translations" / "en.yaml"
KNOWLEDGE_DIR = ADDON_ROOT / "knowledge"


def _load_manifest() -> dict:
    cfg_path = CONFIG_ACTIVE if CONFIG_ACTIVE.exists() else CONFIG_DISABLED
    assert cfg_path.exists(), "config.yaml or config.yaml.disabled must exist"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_staged_manifest_isolation():
    """Ensure config.yaml is valid and store branding assets exist."""
    assert CONFIG_DISABLED.exists() or CONFIG_ACTIVE.exists()
    cfg = _load_manifest()
    assert cfg["name"] == "UniFi OS Server"
    assert cfg["slug"] == "unifi_os_server"
    assert cfg["init"] is False
    assert cfg["timeout"] == 120
    assert cfg["backup"] == "cold"
    assert set(cfg["arch"]) == {"amd64", "aarch64"}
    assert (ADDON_ROOT / "icon.png").exists(), "icon.png store asset must exist"
    assert (ADDON_ROOT / "logo.png").exists(), "logo.png store asset must exist"


def test_security_posture_and_ports():
    """Verify least-privilege capabilities and ensure unsafe bypass/DB ports are never exposed."""
    cfg = _load_manifest()
    assert set(cfg.get("privileged", [])) == {"NET_ADMIN", "NET_RAW"}
    assert cfg.get("full_access") is not True

    ports = cfg.get("ports", {})
    assert ports.get("11443/tcp") == 11443
    assert ports.get("8080/tcp") == 8080
    assert ports.get("3478/udp") == 3478
    assert "5432/tcp" not in ports, "PostgreSQL must remain localhost-only"
    assert "7443/tcp" not in ports, "Unauthenticated Network App bypass port 7443 must not be exposed"


def test_options_schema_and_translations_parity():
    """Verify 1:1 parity between options, schema, and English translations."""
    cfg = _load_manifest()
    options = cfg.get("options", {})
    schema = cfg.get("schema", {})
    assert set(options.keys()) == set(schema.keys())

    with open(TRANSLATIONS_PATH, "r", encoding="utf-8") as f:
        trans = yaml.safe_load(f)

    trans_cfg = trans.get("configuration", {})
    for key in options:
        assert key in trans_cfg, f"Missing translation for option: {key}"
        assert trans_cfg[key].get("name"), f"Empty translation name for option: {key}"
        assert trans_cfg[key].get("description"), f"Empty translation description for option: {key}"


def test_okf_v02_knowledge_bundle_conformance():
    """Verify OKF v0.2 knowledge bundle structure and frontmatter fields."""
    index_file = KNOWLEDGE_DIR / "index.md"
    assert index_file.exists(), "knowledge/index.md must exist"
    index_text = index_file.read_text(encoding="utf-8")
    assert 'okf_version: "0.2"' in index_text

    concept_files = [
        p for p in KNOWLEDGE_DIR.rglob("*.md") if p.name not in ("index.md", "log.md")
    ]
    assert len(concept_files) >= 4, "Expected at least 4 OKF concept documents"

    for cf in concept_files:
        raw = cf.read_text(encoding="utf-8")
        assert raw.startswith("---\n"), f"{cf.name} must start with YAML frontmatter"
        parts = raw.split("---", 2)
        assert len(parts) >= 3, f"{cf.name} has malformed YAML frontmatter"
        fm = yaml.safe_load(parts[1])
        for req in ("id", "title", "type", "status", "trust", "generated", "sources"):
            assert req in fm, f"{cf.name} missing required OKF v0.2 field '{req}'"
        assert isinstance(fm["sources"], list) and len(fm["sources"]) >= 1
        for src in fm["sources"]:
            assert "resource" in src, f"{cf.name} source entry missing 'resource'"
