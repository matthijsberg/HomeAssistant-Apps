"""
Upstream version checker for HomeAssistant-Apps.
Queries GitHub releases, Docker Hub/GHCR, and inspects Dockerfile/build.yaml dependencies.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple
import yaml
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
    release_security_mentions: List[str] = field(default_factory=list)
    docker_components: List[Dict[str, str]] = field(default_factory=list)
    unpinned_tags: List[str] = field(default_factory=list)

def _http_get_json(url: str, timeout: int = 10) -> Any:
    headers = {
        "User-Agent": "HomeAssistant-Apps-Maintenance-Agent/1.0",
        "Accept": "application/json"
    }
    if "api.github.com" in url:
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if gh_token:
            headers["Authorization"] = f"Bearer {gh_token}"
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

_SECURITY_ID_RE = re.compile(r"(CVE-\d{4}-\d{4,7}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})", re.IGNORECASE)
_SECURITY_KW_RE = re.compile(
    r"\b(security(?:\s+(?:fix|patch|update|advisory))?|vulnerabilit(?:y|ies)|xss|ssrf|rce|csrf|auth(?:entication)?\s+bypass|sql\s+injection|privilege\s+escalation)\b",
    re.IGNORECASE,
)

def _extract_security_mentions(body: str, tag_ver: str) -> List[str]:
    if not body:
        return []
    mentions: List[str] = []
    seen = set()
    for match in _SECURITY_ID_RE.findall(body):
        ident = match.upper()
        if ident not in seen:
            seen.add(ident)
            mentions.append(f"{tag_ver}: {ident}")
    for line in body.splitlines():
        clean = line.strip(" -*#\t")
        if not clean or len(clean) > 220:
            continue
        if _SECURITY_KW_RE.search(clean):
            if any(k in clean.upper() for k in seen):
                continue
            item = f"{tag_ver}: {clean[:140]}"
            if item not in seen:
                seen.add(item)
                mentions.append(item)
                if len(mentions) >= 5:
                    break
    return mentions

def check_github_repo_detailed(repo: str, current_version: Optional[str] = None) -> Tuple[Optional[str], Optional[str], List[str]]:
    releases_url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
    releases_data = _http_get_json(releases_url)
    security_mentions: List[str] = []

    if isinstance(releases_data, list) and releases_data:
        stable = [r for r in releases_data if not r.get("draft") and not r.get("prerelease")]
        candidates = stable if stable else releases_data
        latest_rel = candidates[0]
        latest_ver = _clean_version(latest_rel.get("tag_name", ""))
        html_url = latest_rel.get("html_url")

        if current_version and latest_ver:
            for rel in candidates:
                rel_ver = _clean_version(rel.get("tag_name", ""))
                if not rel_ver:
                    continue
                if compare_versions(current_version, rel_ver) != "none":
                    security_mentions.extend(_extract_security_mentions(rel.get("body") or "", rel_ver))
        return (latest_ver or None), html_url, security_mentions[:6]

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    if data and "tag_name" in data:
        tag = data["tag_name"]
        html_url = data.get("html_url")
        latest_ver = _clean_version(tag)
        if current_version and compare_versions(current_version, latest_ver) != "none":
            security_mentions.extend(_extract_security_mentions(data.get("body") or "", latest_ver))
        return latest_ver, html_url, security_mentions[:6]

    # Fallback to tags if no official release
    tags_url = f"https://api.github.com/repos/{repo}/tags?per_page=5"
    tags_data = _http_get_json(tags_url)
    if isinstance(tags_data, list) and len(tags_data) > 0:
        first_tag = tags_data[0].get("name", "")
        if first_tag:
            return _clean_version(first_tag), f"https://github.com/{repo}/releases", []
    return None, None, []

def check_github_repo(repo: str) -> Tuple[Optional[str], Optional[str]]:
    ver, url, _ = check_github_repo_detailed(repo)
    return ver, url

def _substitute_vars(value: str, env_vars: Dict[str, str]) -> str:
    def _repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        return env_vars.get(key, match.group(0))
    return re.sub(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)", _repl, value)

def inspect_container_dependencies(
    app_dir: Path,
    build_yaml_name: Optional[str] = "build.yaml",
    dockerfile_name: Optional[str] = "Dockerfile",
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Inspects build.yaml and Dockerfile for base images, multi-stage images, pinned versions, and :latest tags."""
    components: List[Dict[str, str]] = []
    unpinned_tags: List[str] = []
    vars_map: Dict[str, str] = {}

    if build_yaml_name and (app_dir / build_yaml_name).exists():
        try:
            bld = yaml.safe_load((app_dir / build_yaml_name).read_text(encoding="utf-8")) or {}
            build_from = bld.get("build_from") or {}
            if isinstance(build_from, dict):
                for arch, img in build_from.items():
                    img_s = str(img).strip()
                    components.append({"source": f"build.yaml ({arch})", "name": img_s.split(":")[0], "version": img_s.split(":", 1)[1] if ":" in img_s else "untagged"})
                    if img_s.endswith(":latest") or (":" not in img_s and "@" not in img_s and img_s != "scratch"):
                        unpinned_tags.append(f"build.yaml ({arch}): {img_s}")
                if "amd64" in build_from and "BUILD_FROM" not in vars_map:
                    vars_map["BUILD_FROM"] = str(build_from["amd64"]).strip()
            for k, v in (bld.get("args") or {}).items():
                vars_map[str(k)] = str(v)
                components.append({"source": "build.yaml arg", "name": str(k), "version": str(v)})
        except Exception:
            pass

    if dockerfile_name and (app_dir / dockerfile_name).exists():
        try:
            df_text = (app_dir / dockerfile_name).read_text(encoding="utf-8")
            stage_names = set()
            for raw_line in df_text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                arg_m = re.match(r"^ARG\s+([A-Za-z0-9_]+)(?:=(.+))?$", line, re.IGNORECASE)
                if arg_m:
                    k = arg_m.group(1)
                    if arg_m.group(2) is not None and k not in vars_map:
                        val = arg_m.group(2).strip().strip('"').strip("'")
                        vars_map[k] = val
                        if "VERSION" in k.upper():
                            components.append({"source": "Dockerfile ARG", "name": k, "version": val})
                    continue

                from_m = re.match(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
                if from_m:
                    raw_img = from_m.group(1)
                    if from_m.group(2):
                        stage_names.add(from_m.group(2))
                    resolved = _substitute_vars(raw_img, vars_map)
                    if resolved == "scratch" or resolved in stage_names or "${" in resolved:
                        continue
                    img_no_digest = resolved.split("@", 1)[0]
                    name_part = img_no_digest.split(":", 1)[0]
                    tag_part = img_no_digest.split(":", 1)[1] if ":" in img_no_digest else ("sha256" if "@" in resolved else "untagged")
                    components.append({"source": "Dockerfile FROM", "name": name_part, "version": tag_part})
                    if tag_part in ("latest", "untagged") and "@" not in resolved:
                        unpinned_tags.append(f"Dockerfile FROM: {resolved}")

            # Detect GitHub release downloads in Dockerfile
            for gh_m in re.finditer(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/releases/download/([^/\s\"']+)", df_text):
                repo_ref = gh_m.group(1)
                tag_ref = _substitute_vars(gh_m.group(2), vars_map)
                components.append({"source": "Dockerfile binary", "name": repo_ref, "version": _clean_version(tag_ref)})
        except Exception:
            pass

    # Deduplicate unpinned_tags preserving order
    dedup_unpinned = list(dict.fromkeys(unpinned_tags))
    return components, dedup_unpinned

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
    sec_mentions: List[str] = []

    # 1. GitHub repo check
    if config.upstream.github_repo:
        latest_ver, notes_url, sec_mentions = check_github_repo_detailed(
            config.upstream.github_repo,
            current_version=config.current_version
        )
        if latest_ver:
            result.details.append(f"Upstream GitHub ({config.upstream.github_repo}): latest release is {latest_ver}")
        if sec_mentions:
            result.release_security_mentions = sec_mentions
            result.details.append(f"Security mentions in newer releases: {len(sec_mentions)}")

    # 2. Docker Hub check if no github repo or wrapper
    if not latest_ver and config.upstream.docker_image:
        latest_ver = check_docker_hub(config.upstream.docker_image)
        if latest_ver:
            result.details.append(f"Docker Hub ({config.upstream.docker_image}): latest tag is {latest_ver}")

    # 3. Inspect Dockerfile & build.yaml components
    components, unpinned = inspect_container_dependencies(
        config.app_dir,
        build_yaml_name=config.upstream.build_yaml,
        dockerfile_name=config.upstream.dockerfile,
    )
    result.docker_components = components
    result.unpinned_tags = unpinned
    if unpinned:
        result.details.append(f"Unpinned container tags: {', '.join(unpinned)}")

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
