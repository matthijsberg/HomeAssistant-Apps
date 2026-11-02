"""
Maintenance configuration data model and loader for HomeAssistant-Apps.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

@dataclass
class UpstreamConfig:
    github_repo: Optional[str] = None
    docker_image: Optional[str] = None
    base_image: Optional[str] = None
    pip_file: Optional[str] = None
    package_json: Optional[str] = None

@dataclass
class HealthcheckConfig:
    port: int = 8000
    endpoint: str = "/health"
    timeout_seconds: int = 30
    ingress: bool = False

@dataclass
class SecurityConfig:
    cve_check: bool = True
    secret_scan: bool = True
    okf_required: bool = True

@dataclass
class DocsConfig:
    sync_changelog: bool = True
    sync_readme: bool = True
    sync_docs: bool = True
    sync_okf: bool = True

@dataclass
class AppMaintenanceConfig:
    app_name: str
    app_dir: Path
    slug: str
    current_version: str
    app_type: str = "local_app"  # "local_app", "upstream_wrapper", "infra"
    status: str = "active"       # "active", "disabled"
    upstream: UpstreamConfig = field(default_factory=UpstreamConfig)
    healthcheck: HealthcheckConfig = field(default_factory=HealthcheckConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)
    test_commands: List[str] = field(default_factory=list)

def _read_manifest(app_dir: Path) -> Dict[str, Any]:
    cfg_file = app_dir / "config.yaml"
    if not cfg_file.exists():
        cfg_file = app_dir / "config.yaml.disabled"
    if not cfg_file.exists():
        return {}
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def load_app_maintenance_config(app_dir: Path) -> AppMaintenanceConfig:
    manifest = _read_manifest(app_dir)
    slug = manifest.get("slug", app_dir.name.replace("-", "_"))
    current_version = str(manifest.get("version", "0.0.0"))
    app_name = manifest.get("name", app_dir.name)
    status = "disabled" if (app_dir / "config.yaml.disabled").exists() else "active"

    maint_file = app_dir / "maintenance.yaml"
    if maint_file.exists():
        try:
            with open(maint_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    else:
        data = {}

    up_data = data.get("upstream", {})
    upstream = UpstreamConfig(
        github_repo=up_data.get("github_repo"),
        docker_image=up_data.get("docker_image"),
        base_image=up_data.get("base_image"),
        pip_file=up_data.get("pip_file", "requirements.txt" if (app_dir / "requirements.txt").exists() else None),
        package_json=up_data.get("package_json", "package.json" if (app_dir / "package.json").exists() else None)
    )

    hc_data = data.get("healthcheck", {})
    healthcheck = HealthcheckConfig(
        port=int(hc_data.get("port", manifest.get("ingress_port", 8000))),
        endpoint=str(hc_data.get("endpoint", "/health")),
        timeout_seconds=int(hc_data.get("timeout_seconds", 30)),
        ingress=bool(manifest.get("ingress", False))
    )

    sec_data = data.get("security", {})
    security = SecurityConfig(
        cve_check=bool(sec_data.get("cve_check", True)),
        secret_scan=bool(sec_data.get("secret_scan", True)),
        okf_required=bool(sec_data.get("okf_required", (app_dir / "knowledge").exists()))
    )

    docs_data = data.get("docs", {})
    docs = DocsConfig(
        sync_changelog=bool(docs_data.get("sync_changelog", True)),
        sync_readme=bool(docs_data.get("sync_readme", True)),
        sync_docs=bool(docs_data.get("sync_docs", True)),
        sync_okf=bool(docs_data.get("sync_okf", (app_dir / "knowledge").exists()))
    )

    test_commands = data.get("test_commands", [])
    if not test_commands:
        if (app_dir / "tests").exists():
            test_commands.append("pytest tests/")
        if (app_dir / "scripts" / "validate_okf.sh").exists():
            test_commands.append("./scripts/validate_okf.sh")

    app_type = data.get("app_type", "upstream_wrapper" if upstream.docker_image or upstream.github_repo and not (app_dir / "tests").exists() else "local_app")

    return AppMaintenanceConfig(
        app_name=app_name,
        app_dir=app_dir,
        slug=slug,
        current_version=current_version,
        app_type=app_type,
        status=status,
        upstream=upstream,
        healthcheck=healthcheck,
        security=security,
        docs=docs,
        test_commands=test_commands
    )
