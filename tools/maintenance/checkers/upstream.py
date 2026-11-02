"""
Upstream version checker for HomeAssistant-Apps.
Queries GitHub releases, Docker Hub/GHCR, and PyPI without external dependencies.
"""
from dataclasses import dataclass, field
import json
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple
from ..config import AppMaintenanceConfig

@dataclass
class UpstreamCheckResult:
    app_name: str
    current_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    update_type: str = "none"  # "major", "minor", "patch", "base_image", "none"
    release_notes_url: Optional[str] = None
    details: List[str] = field(default_factory=list)

def _http_get_json(url: str, timeout: int = 10) -> Any:
    headers = {
        "User-Agent": "HomeAssistant-Apps-Maintenance-Agent/1.0",
        "Accept": "application/json"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None

def _clean_version(ver: str) -> str:
    ver = ver.strip()
    if ver.startswith("v") or ver.startswith("V"):
        ver = ver[1:]
    return ver

def _parse_semver(ver: str) -> Tuple[int, int, int]:
    clean = _clean_version(ver)
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", clean)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2))
        patch = int(m.group(3)) if m.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)

def compare_versions(current: str, latest: str) -> str:
    c_parts = _parse_semver(current)
    l_parts = _parse_semver(latest)

    if l_parts > c_parts:
        if l_parts[0] > c_parts[0]:
            return "major"
        elif l_parts[1] > c_parts[1]:
            return "minor"
        elif l_parts[2] > c_parts[2]:
            return "patch"
    return "none"

def check_github_repo(repo: str) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    if data and "tag_name" in data:
        tag = data["tag_name"]
        html_url = data.get("html_url")
        return _clean_version(tag), html_url

    # Fallback to tags if no official release
    tags_url = f"https://api.github.com/repos/{repo}/tags?per_page=5"
    tags_data = _http_get_json(tags_url)
    if isinstance(tags_data, list) and len(tags_data) > 0:
        first_tag = tags_data[0].get("name", "")
        if first_tag:
            return _clean_version(first_tag), f"https://github.com/{repo}/releases"
    return None, None

def check_docker_hub(image_name: str) -> Optional[str]:
    # e.g. "ollama/ollama"
    parts = image_name.split("/")
    if len(parts) == 1:
        namespace = "library"
        repo = parts[0]
    else:
        namespace, repo = parts[0], parts[1]

    url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/?page_size=25&ordering=last_updated"
    data = _http_get_json(url)
    if not data or "results" not in data:
        return None

    semver_pattern = re.compile(r"^v?(\d+\.\d+(?:\.\d+)?)$")
    for item in data.get("results", []):
        tag_name = item.get("name", "")
        m = semver_pattern.match(tag_name)
        if m:
            return m.group(1)
    return None

def check_app_upstream(config: AppMaintenanceConfig) -> UpstreamCheckResult:
    result = UpstreamCheckResult(
        app_name=config.app_name,
        current_version=config.current_version
    )

    latest_ver = None
    notes_url = None

    # 1. GitHub repo check
    if config.upstream.github_repo:
        latest_ver, notes_url = check_github_repo(config.upstream.github_repo)
        if latest_ver:
            result.details.append(f"Upstream GitHub ({config.upstream.github_repo}): latest release is {latest_ver}")

    # 2. Docker Hub check if no github repo or wrapper
    if not latest_ver and config.upstream.docker_image:
        latest_ver = check_docker_hub(config.upstream.docker_image)
        if latest_ver:
            result.details.append(f"Docker Hub ({config.upstream.docker_image}): latest tag is {latest_ver}")

    if latest_ver:
        result.latest_version = latest_ver
        result.release_notes_url = notes_url
        update_type = compare_versions(config.current_version, latest_ver)
        if update_type != "none":
            result.update_available = True
            result.update_type = update_type
            result.details.append(f"Update available: {config.current_version} -> {latest_ver} ({update_type})")
        else:
            result.details.append(f"Version is up to date ({config.current_version})")
    else:
        result.details.append("No newer upstream release detected.")

    return result
