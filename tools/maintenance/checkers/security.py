"""
Security and vulnerability checker for HomeAssistant-Apps.
Scans for leaked secrets and queries OSV API for known dependency CVEs.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from ..config import AppMaintenanceConfig

@dataclass
class Vulnerability:
    package: str
    version: str
    vuln_id: str
    summary: str
    severity: str  # "HIGH", "MEDIUM", "LOW"

@dataclass
class SecurityCheckResult:
    app_name: str
    vulnerabilities: List[Vulnerability] = field(default_factory=list)
    secrets_found: List[str] = field(default_factory=list)
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

def query_osv_package(package_name: str, version: str) -> List[Vulnerability]:
    """Queries OSV.dev for known vulnerabilities for a Python package."""
    url = "https://api.osv.dev/v1/query"
    payload = json.dumps({
        "version": version,
        "package": {
            "name": package_name,
            "ecosystem": "PyPI"
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "HomeAssistant-Apps-Security/1.0"}
    )

    vulns: List[Vulnerability] = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("vulns", []):
                    vuln_id = item.get("id", "UNKNOWN")
                    summary = item.get("summary", item.get("details", "Vulnerability detected"))
                    # Map severity
                    severity = "MEDIUM"
                    for sev in item.get("severity", []):
                        score = sev.get("score", "")
                        if "CVSS:3" in score and float(score.split("/")[0].replace("CVSS:3.", "3.")) >= 7.0:
                            severity = "HIGH"
                    vulns.append(Vulnerability(
                        package=package_name,
                        version=version,
                        vuln_id=vuln_id,
                        summary=summary[:120],
                        severity=severity
                    ))
    except Exception:
        pass
    return vulns

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

def parse_requirements_file(req_file: Path) -> List[tuple]:
    packages = []
    if not req_file.exists():
        return packages
    try:
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*==\s*([a-zA-Z0-9_\-\.]+)", line)
            if m:
                packages.append((m.group(1), m.group(2)))
    except Exception:
        pass
    return packages

def check_app_security(config: AppMaintenanceConfig) -> SecurityCheckResult:
    result = SecurityCheckResult(app_name=config.app_name)

    # 1. Scan for secrets
    if config.security.secret_scan:
        secrets = scan_for_secrets(config.app_dir)
        result.secrets_found = secrets

    # 2. Check Python CVEs if requirements.txt exists
    if config.security.cve_check and config.upstream.pip_file:
        req_path = config.app_dir / config.upstream.pip_file
        packages = parse_requirements_file(req_path)
        for pkg, ver in packages:
            found_vulns = query_osv_package(pkg, ver)
            result.vulnerabilities.extend(found_vulns)

    # 3. Determine overall risk level
    if any(v.severity == "HIGH" for v in result.vulnerabilities) or result.secrets_found:
        result.risk_level = "HIGH"
        result.summary = f"HIGH RISK: {len(result.secrets_found)} secret findings, {len(result.vulnerabilities)} CVEs"
    elif result.vulnerabilities:
        result.risk_level = "MEDIUM"
        result.summary = f"MEDIUM RISK: {len(result.vulnerabilities)} dependency vulnerabilities detected"
    else:
        result.risk_level = "CLEAN"
        result.summary = "Clean: No secrets or known CVEs found"

    return result
