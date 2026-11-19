#!/usr/bin/env python3
"""Pre-commit secret & sensitive file scanner for KiCad Headless MCP / HomeAssistant-Apps."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SENSITIVE_FILES = [
    r"(^|/)\.env$",
    r"(^|/)options\.json$",
    r"(^|/)bearer_token\.txt$",
    r"(^|/)secrets\.yaml$",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"id_ed25519",
    r"\.ha_api_config\.json$",
    r"google_token\.json$",
    r"client_secret.*\.json$",
]

SECRET_PATTERNS = [
    (r"gh[pousr]_[A-Za-z0-9_]{36,255}", "GitHub Token"),
    (r"github_pat_[A-Za-z0-9_]{82}", "GitHub Fine-Grained Token"),
    (r"eyJhbGciOi[A-Za-z0-9_\-\.]+\.[A-Za-z0-9_\-\.]+\.[A-Za-z0-9_\-\.]+", "JWT / HA Access Token"),
    (r"-----BEGIN (RSA|EC|DSA|OPENSSH|PGP) PRIVATE KEY", "Private Key"),
    (r"\b\d{9,10}:[A-Za-z0-9_-]{35}\b", "Telegram Bot Token"),
    (
        r"(?i)(api[_-]?key|secret|password|passwd|auth[_-]?token|bearer[_-]?token)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.]{24,}['\"]",
        "Hardcoded Secret/Token Assignment",
    ),
]

ALLOWLIST_VALUES = ("change-me", "demo-sandbox", "test-secret-token", "your-token", "example")


def scan_directory(root: Path) -> list[str]:
    """Scan tracked/project files under root for sensitive files and hardcoded secrets."""
    findings: list[str] = []
    skip_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "output", "tests"}
    for path in sorted(root.rglob("*")):
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        for pat in SENSITIVE_FILES:
            if re.search(pat, rel):
                findings.append(f"Sensitive file: {rel} (matched {pat})")
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            lower = line.lower()
            if any(ok in lower for ok in ALLOWLIST_VALUES):
                continue
            for pat, label in SECRET_PATTERNS:
                if re.search(pat, line):
                    findings.append(f"{rel}:{lineno}: {label}")
    return findings


def scan_staged(repo_root: Path) -> list[str]:
    """Scan git staged files and added diff lines."""
    findings: list[str] = []
    staged = subprocess.check_output(
        ["git", "-C", str(repo_root), "diff", "--cached", "--name-only"],
        text=True,
    ).splitlines()
    for f in staged:
        for pat in SENSITIVE_FILES:
            if re.search(pat, f):
                findings.append(f"Staged sensitive file: {f}")

    diff = subprocess.check_output(
        ["git", "-C", str(repo_root), "diff", "--cached", "-U0"],
        text=True,
    )
    current_file = "unknown"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            lower = content.lower()
            if any(ok in lower for ok in ALLOWLIST_VALUES) or "tests/" in current_file:
                continue
            for pat, label in SECRET_PATTERNS:
                if re.search(pat, content):
                    findings.append(f"Staged diff {current_file}: {label}")
    return findings


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dir"
    if mode == "--staged":
        repo_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
        findings = scan_staged(repo_root)
    else:
        target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent
        findings = scan_directory(target)

    if findings:
        print("SECRET SCAN FAILED:")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("Secret scan clean: 0 findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
