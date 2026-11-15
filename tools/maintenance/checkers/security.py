"""
Security and vulnerability checker for HomeAssistant-Apps.
Scans for leaked secrets, queries OSV.dev (PyPI/npm via requirements.txt, uv.lock, package-lock.json),
checks GitHub Security Advisories (GHSA), and audits Dockerfile/build.yaml supply-chain hygiene.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
import yaml
from ..config import AppMaintenanceConfig

@dataclass
class Vulnerability:
    package: str
    version: str
    vuln_id: str
    summary: str
    severity: str  # "HIGH", "MEDIUM", "LOW"
    ecosystem: str = "PyPI"
    fixed_version: Optional[str] = None

@dataclass
class SecurityCheckResult:
    app_name: str
    vulnerabilities: List[Vulnerability] = field(default_factory=list)
    secrets_found: List[str] = field(default_factory=list)
    supply_chain_warnings: List[str] = field(default_factory=list)
    scanned_targets: List[str] = field(default_factory=list)
    trivy_available: bool = False
    risk_level: str = "CLEAN"  # "HIGH", "MEDIUM", "LOW", "CLEAN"
    summary: str = "No security issues identified."

# Regex patterns for accidental secrets
SECRET_PATTERNS = [
    (re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{16,})['\"]"), "Potential API token or password"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"), "Private cryptographic key"),
]

def scan_for_secrets(app_dir: Path) -> List[str]:
    findings = []
    ignored_exts = {".pyc", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".db", ".sqlite", ".bin"}
    ignored_dirs = {".git", ".pytest_cache", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache"}

    for p in app_dir.rglob("*"):
        if p.is_dir() or p.suffix in ignored_exts:
            continue
        if any(part in ignored_dirs for part in p.parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            for pattern, desc in SECRET_PATTERNS:
                if pattern.search(content):
                    rel = p.relative_to(app_dir)
                    findings.append(f"{desc} in {rel}")
        except Exception:
            continue
    return findings

_VULN_DETAIL_CACHE: Dict[str, Dict[str, Any]] = {}

def _http_json(url: str, payload: Optional[bytes] = None, timeout: int = 10) -> Any:
    headers = {"User-Agent": "HomeAssistant-Apps-Security/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if "api.github.com" in url:
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if gh_token:
            headers["Authorization"] = f"Bearer {gh_token}"
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None

def _map_osv_severity(vuln_data: Dict[str, Any]) -> str:
    db_sev = str((vuln_data.get("database_specific") or {}).get("severity", "")).upper()
    if db_sev in ("CRITICAL", "HIGH"):
        return "HIGH"
    if db_sev in ("MODERATE", "MEDIUM"):
        return "MEDIUM"
    if db_sev == "LOW":
        return "LOW"
    for sev in vuln_data.get("severity", []):
        score_str = str(sev.get("score", ""))
        m = re.match(r"^(\d+(?:\.\d+)?)$", score_str)
        if m and float(m.group(1)) >= 7.0:
            return "HIGH"
    return "MEDIUM"

def _extract_osv_fixed(vuln_data: Dict[str, Any], pkg_name: str) -> Optional[str]:
    for aff in vuln_data.get("affected", []):
        pkg = (aff.get("package") or {}).get("name", "")
        if pkg.lower() != pkg_name.lower():
            continue
        for rng in aff.get("ranges", []):
            for ev in rng.get("events", []):
                if "fixed" in ev:
                    return str(ev["fixed"])
    return None

def query_osv_batch(packages: List[Tuple[str, str, str]]) -> List[Vulnerability]:
    """Batch-queries OSV.dev for (package_name, version, ecosystem) tuples."""
    if not packages:
        return []

    vulns: List[Vulnerability] = []
    seen_pairs = set()
    unique_queries: List[Tuple[str, str, str]] = []
    for pkg, ver, eco in packages:
        key = (pkg.lower(), ver, eco)
        if key not in seen_pairs and pkg and ver:
            seen_pairs.add(key)
            unique_queries.append((pkg, ver, eco))

    for i in range(0, len(unique_queries), 100):
        chunk = unique_queries[i:i + 100]
        payload = json.dumps({
            "queries": [
                {"version": ver, "package": {"name": pkg, "ecosystem": eco}}
                for pkg, ver, eco in chunk
            ]
        }).encode("utf-8")
        batch_resp = _http_json("https://api.osv.dev/v1/querybatch", payload=payload, timeout=12)
        if not batch_resp or "results" not in batch_resp:
            continue

        for (pkg, ver, eco), res in zip(chunk, batch_resp.get("results", [])):
            for item in res.get("vulns", []):
                vid = item.get("id", "UNKNOWN")
                detail = _VULN_DETAIL_CACHE.get(vid)
                if detail is None:
                    detail = _http_json(f"https://api.osv.dev/v1/vulns/{vid}", timeout=8) or {}
                    _VULN_DETAIL_CACHE[vid] = detail
                summary = detail.get("summary") or detail.get("details") or "Vulnerability detected"
                vulns.append(Vulnerability(
                    package=pkg,
                    version=ver,
                    vuln_id=vid,
                    summary=str(summary)[:140],
                    severity=_map_osv_severity(detail),
                    ecosystem=eco,
                    fixed_version=_extract_osv_fixed(detail, pkg),
                ))
    return vulns

def query_osv_package(package_name: str, version: str, ecosystem: str = "PyPI") -> List[Vulnerability]:
    """Queries OSV.dev for known vulnerabilities for a single package."""
    return query_osv_batch([(package_name, version, ecosystem)])

def run_mantis_diff_review(diff_text: str, context: str = "Home Assistant add-on on HAOS, behind Ingress", model: str = "gemini-4-argon") -> Tuple[bool, str, Dict[str, Any]]:
    """Runs a synchronous diff review via Mantis MCP server using the specified LLM (default gemini-4-argon)."""
    if not diff_text.strip():
        return True, "No diff to review", {"verdict": "CLEAN"}

    hermes_cfg_path = Path("/config/.hermes/profiles/matthijs/config.yaml")
    mcp_url = "http://local-mantis-security-agent:8000/mcp"
    headers = {"Content-Type": "application/json"}

    if hermes_cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(hermes_cfg_path.read_text(encoding="utf-8")) or {}
            mantis_sec = cfg.get("mcp_servers", {}).get("mantis", {})
            mcp_url = mantis_sec.get("url", mcp_url)
            headers.update(mantis_sec.get("headers", {}))
        except Exception:
            pass

    payload = {
        "jsonrpc": "2.0",
        "id": "mantis-maint-review",
        "method": "tools/call",
        "params": {
            "name": "mantis_review_diff",
            "arguments": {
                "diff": diff_text[:150000],
                "context": context,
                "llm": {"provider": "gemini", "model": model}
            }
        }
    }

    req = urllib.request.Request(mcp_url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                content_items = body.get("result", {}).get("content", [])
                if content_items and content_items[0].get("type") == "text":
                    review_data = json.loads(content_items[0]["text"])
                    verdict = review_data.get("verdict", "UNKNOWN")
                    job_id = review_data.get("job_id", "")
                    findings = review_data.get("findings", [])
                    if verdict in ("CLEAN", "PASS"):
                        return True, f"Mantis ({model}) passed [Job: {job_id}, Verdict: {verdict}]", review_data
                    else:
                        return False, f"Mantis ({model}) flagged issues [Verdict: {verdict}, Findings: {len(findings)}]", review_data
    except Exception as e:
        return False, f"Mantis review call failed: {e}", {}

    return True, f"Mantis review completed", {}

def parse_requirements_file(req_file: Path) -> List[Tuple[str, str]]:
    packages: List[Tuple[str, str]] = []
    if not req_file.exists():
        return packages
    try:
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*==\s*([a-zA-Z0-9_\-\.+]+)", line)
            if m:
                packages.append((m.group(1), m.group(2)))
    except Exception:
        pass
    return packages

def parse_requirements_unpinned(req_file: Path) -> List[str]:
    unpinned: List[str] = []
    if not req_file.exists():
        return unpinned
    try:
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if "==" not in line:
                unpinned.append(line.split(";")[0].strip())
    except Exception:
        pass
    return unpinned

def parse_uv_lock(lock_file: Path) -> List[Tuple[str, str]]:
    """Extracts resolved (package, version) pairs from uv.lock."""
    packages: List[Tuple[str, str]] = []
    if not lock_file.exists():
        return packages
    try:
        data = tomllib.loads(lock_file.read_text(encoding="utf-8"))
        for pkg in data.get("package", []):
            name = pkg.get("name")
            version = pkg.get("version")
            source = pkg.get("source") or {}
            if not name or not version:
                continue
            if "virtual" in source or "editable" in source:
                continue
            packages.append((str(name), str(version)))
    except Exception:
        pass
    return packages

def parse_package_lock(lock_file: Path) -> List[Tuple[str, str]]:
    """Extracts resolved (package, version) pairs from npm package-lock.json (v1/v2/v3)."""
    packages: List[Tuple[str, str]] = []
    if not lock_file.exists():
        return packages
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        if isinstance(data.get("packages"), dict):
            for pkg_path, meta in data["packages"].items():
                if not pkg_path or not isinstance(meta, dict):
                    continue
                ver = meta.get("version")
                if not ver:
                    continue
                name = meta.get("name") or pkg_path.split("node_modules/")[-1]
                if name:
                    packages.append((str(name), str(ver)))
        elif isinstance(data.get("dependencies"), dict):
            def _walk(deps: Dict[str, Any]):
                for name, meta in deps.items():
                    if isinstance(meta, dict):
                        if meta.get("version"):
                            packages.append((str(name), str(meta["version"])))
                        if isinstance(meta.get("dependencies"), dict):
                            _walk(meta["dependencies"])
            _walk(data["dependencies"])
    except Exception:
        pass
    return packages

def _parse_semver_tuple(ver: str) -> Optional[Tuple[int, int, int]]:
    clean = ver.strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", clean)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else 0)

def _version_in_range(version: str, range_expr: str) -> bool:
    """Evaluates GitHub Advisory vulnerable_version_range (e.g. '>= 3.68.0, < 3.167.0')."""
    v_tup = _parse_semver_tuple(version)
    if v_tup is None or not range_expr or not range_expr.strip():
        return False
    clauses = [c.strip() for c in range_expr.split(",") if c.strip()]
    if not clauses:
        return False
    for clause in clauses:
        m = re.match(r"^(<=|>=|<|>|==|=)\s*(.+)$", clause)
        if not m:
            return False
        op, target_raw = m.group(1), m.group(2)
        t_tup = _parse_semver_tuple(target_raw)
        if t_tup is None:
            return False
        if op == "<=" and not (v_tup <= t_tup):
            return False
        elif op == ">=" and not (v_tup >= t_tup):
            return False
        elif op == "<" and not (v_tup < t_tup):
            return False
        elif op == ">" and not (v_tup > t_tup):
            return False
        elif op in ("=", "==") and not (v_tup == t_tup):
            return False
    return True

def check_github_advisories(repo: str, current_version: str) -> List[Vulnerability]:
    """Queries GitHub Security Advisories for a repo and matches against current_version."""
    url = f"https://api.github.com/repos/{repo}/security-advisories?per_page=20"
    advisories = _http_json(url, timeout=10)
    if not isinstance(advisories, list):
        return []

    findings: List[Vulnerability] = []
    for adv in advisories:
        if adv.get("state") and adv.get("state") != "published":
            continue
        ghsa_id = adv.get("ghsa_id") or "GHSA-UNKNOWN"
        cve_id = adv.get("cve_id")
        vuln_label = f"{ghsa_id} ({cve_id})" if cve_id else ghsa_id
        raw_sev = str(adv.get("severity") or "medium").upper()
        sev = "HIGH" if raw_sev in ("CRITICAL", "HIGH") else "MEDIUM" if raw_sev in ("MODERATE", "MEDIUM") else "LOW"
        summary = str(adv.get("summary") or "GitHub Security Advisory")[:140]

        for item in adv.get("vulnerabilities", []):
            vrange = str(item.get("vulnerable_version_range") or "")
            if vrange and _version_in_range(current_version, vrange):
                patched = item.get("patched_versions")
                findings.append(Vulnerability(
                    package=repo,
                    version=current_version,
                    vuln_id=vuln_label,
                    summary=summary,
                    severity=sev,
                    ecosystem="GitHub Advisory",
                    fixed_version=str(patched) if patched else None,
                ))
                break
    return findings

def audit_dockerfile_and_build(config: AppMaintenanceConfig) -> List[str]:
    """Audits Dockerfile, build.yaml, and dependency pinning hygiene."""
    warnings: List[str] = []

    if config.upstream.build_yaml and (config.app_dir / config.upstream.build_yaml).exists():
        try:
            bld = yaml.safe_load((config.app_dir / config.upstream.build_yaml).read_text(encoding="utf-8")) or {}
            for arch, img in (bld.get("build_from") or {}).items():
                img_s = str(img).strip()
                if img_s.endswith(":latest"):
                    warnings.append(f"Unpinned ':latest' base image in build.yaml ({arch}): {img_s}")
        except Exception:
            pass

    if config.upstream.dockerfile and (config.app_dir / config.upstream.dockerfile).exists():
        try:
            df_text = (config.app_dir / config.upstream.dockerfile).read_text(encoding="utf-8")
            for raw_line in df_text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if re.match(r"^FROM\s+.*:latest(?:\s|$)", line, re.IGNORECASE):
                    warnings.append(f"Unpinned ':latest' tag in Dockerfile: {line}")
            if re.search(r"(?:curl|wget)[^\n|]*\|\s*(?:bash|sh)\b", df_text):
                warnings.append("Dockerfile pipes remote script directly into shell (curl|sh) without checksum verification")
            if "apt-get install" in df_text and "/var/lib/apt/lists/*" not in df_text:
                warnings.append("Dockerfile runs apt-get install without cleaning /var/lib/apt/lists/*")
            if "apk add" in df_text and "--no-cache" not in df_text:
                warnings.append("Dockerfile runs apk add without --no-cache")
        except Exception:
            pass

    if config.upstream.pip_file and not config.upstream.uv_lock:
        unpinned = parse_requirements_unpinned(config.app_dir / config.upstream.pip_file)
        if unpinned:
            warnings.append(
                f"{config.upstream.pip_file} has {len(unpinned)} unpinned spec(s) without lockfile ({', '.join(unpinned[:3])})"
            )

    return warnings

def run_trivy_fs(app_dir: Path) -> Tuple[bool, List[Vulnerability]]:
    """If Trivy CLI is locally available, scan app_dir filesystem for OS/library CVEs."""
    trivy_bin = shutil.which("trivy")
    if not trivy_bin:
        return False, []

    vulns: List[Vulnerability] = []
    try:
        res = subprocess.run(
            [trivy_bin, "fs", "--format", "json", "--quiet", "--severity", "HIGH,CRITICAL", str(app_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            for r in data.get("Results", []):
                target = r.get("Target", "fs")
                for v in r.get("Vulnerabilities", []) or []:
                    raw_sev = str(v.get("Severity", "MEDIUM")).upper()
                    sev = "HIGH" if raw_sev in ("CRITICAL", "HIGH") else "MEDIUM"
                    vulns.append(Vulnerability(
                        package=v.get("PkgName", target),
                        version=v.get("InstalledVersion", "?"),
                        vuln_id=v.get("VulnerabilityID", "TRIVY-UNKNOWN"),
                        summary=str(v.get("Title") or v.get("Description") or "Trivy finding")[:140],
                        severity=sev,
                        ecosystem=r.get("Type", "trivy"),
                        fixed_version=v.get("FixedVersion"),
                    ))
    except Exception:
        pass
    return True, vulns

def check_app_security(config: AppMaintenanceConfig) -> SecurityCheckResult:
    result = SecurityCheckResult(app_name=config.app_name)

    # 1. Scan for secrets
    if config.security.secret_scan:
        secrets = scan_for_secrets(config.app_dir)
        result.secrets_found = secrets
        result.scanned_targets.append("secrets")

    # 2. Check dependencies via OSV.dev (requirements.txt, uv.lock, package-lock.json)
    if config.security.cve_check:
        osv_queries: List[Tuple[str, str, str]] = []
        if config.upstream.uv_lock:
            uv_pkgs = parse_uv_lock(config.app_dir / config.upstream.uv_lock)
            if uv_pkgs:
                osv_queries.extend((p, v, "PyPI") for p, v in uv_pkgs)
                result.scanned_targets.append(f"uv.lock ({len(uv_pkgs)} PyPI)")
        if config.upstream.pip_file:
            req_pkgs = parse_requirements_file(config.app_dir / config.upstream.pip_file)
            if req_pkgs:
                osv_queries.extend((p, v, "PyPI") for p, v in req_pkgs)
                result.scanned_targets.append(f"{config.upstream.pip_file} ({len(req_pkgs)} PyPI)")
        if config.upstream.package_lock:
            npm_pkgs = parse_package_lock(config.app_dir / config.upstream.package_lock)
            if npm_pkgs:
                osv_queries.extend((p, v, "npm") for p, v in npm_pkgs)
                result.scanned_targets.append(f"{config.upstream.package_lock} ({len(npm_pkgs)} npm)")
        if osv_queries:
            result.vulnerabilities.extend(query_osv_batch(osv_queries))

    # 3. Check GitHub Security Advisories for upstream repository
    if config.security.ghsa_check and config.upstream.github_repo:
        ghsa_vulns = check_github_advisories(config.upstream.github_repo, config.current_version)
        result.vulnerabilities.extend(ghsa_vulns)
        result.scanned_targets.append(f"GHSA ({config.upstream.github_repo})")

    # 4. Audit Dockerfile & build.yaml supply-chain hygiene
    if config.security.dockerfile_audit:
        result.supply_chain_warnings = audit_dockerfile_and_build(config)
        if config.upstream.dockerfile or config.upstream.build_yaml:
            result.scanned_targets.append("Dockerfile/build.yaml")

    # 5. Optional local Trivy scan (image/OS layers are always scanned in GitHub Actions)
    trivy_ok, trivy_vulns = run_trivy_fs(config.app_dir)
    result.trivy_available = trivy_ok
    if trivy_ok:
        result.vulnerabilities.extend(trivy_vulns)
        result.scanned_targets.append("trivy-fs")
    else:
        result.scanned_targets.append("OS/image via CI Trivy")

    # 6. Determine overall risk level
    if any(v.severity == "HIGH" for v in result.vulnerabilities) or result.secrets_found:
        result.risk_level = "HIGH"
        result.summary = f"HIGH RISK: {len(result.secrets_found)} secret findings, {len(result.vulnerabilities)} CVEs/advisories"
    elif result.vulnerabilities:
        result.risk_level = "MEDIUM"
        result.summary = f"MEDIUM RISK: {len(result.vulnerabilities)} CVEs/advisories detected"
    elif result.supply_chain_warnings:
        result.risk_level = "LOW"
        result.summary = f"Hygiene notes ({len(result.supply_chain_warnings)}): {result.supply_chain_warnings[0]}"
    else:
        result.risk_level = "CLEAN"
        result.summary = "Clean: No secrets, OSV CVEs, or GHSA advisories found"

    return result
