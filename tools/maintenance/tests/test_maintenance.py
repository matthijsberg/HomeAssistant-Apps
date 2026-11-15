"""Unit tests for HomeAssistant-Apps maintenance checkers, planner, and version sync."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.maintenance.config import load_app_maintenance_config
from tools.maintenance.checkers.upstream import (
    UpstreamCheckResult,
    _extract_security_mentions,
    inspect_container_dependencies,
)
from tools.maintenance.checkers.security import (
    Vulnerability,
    SecurityCheckResult,
    _version_in_range,
    audit_dockerfile_and_build,
    check_github_advisories,
    parse_package_lock,
    parse_requirements_file,
    parse_requirements_unpinned,
    parse_uv_lock,
    query_osv_batch,
)
from tools.maintenance.docs_manager import sync_app_version_references
from tools.maintenance.planner import format_telegram_plan, AppMaintenanceProposal


class TestMaintenanceSecurityAndUpstream(unittest.TestCase):
    def test_parse_uv_lock_and_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "uv.lock").write_text(
                'version = 1\n'
                '[[package]]\nname = "fastapi"\nversion = "0.115.0"\nsource = { registry = "https://pypi.org/simple" }\n'
                '[[package]]\nname = "local-app"\nversion = "0.1.0"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            (app_dir / "requirements.txt").write_text(
                "# comment\nfastapi==0.115.0\nnumpy>=1.24.0\nrequests\n",
                encoding="utf-8",
            )
            uv_pkgs = parse_uv_lock(app_dir / "uv.lock")
            self.assertEqual(uv_pkgs, [("fastapi", "0.115.0")])

            req_pinned = parse_requirements_file(app_dir / "requirements.txt")
            self.assertEqual(req_pinned, [("fastapi", "0.115.0")])

            req_unpinned = parse_requirements_unpinned(app_dir / "requirements.txt")
            self.assertEqual(req_unpinned, ["numpy>=1.24.0", "requests"])

    def test_parse_package_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            lock_data = {
                "name": "app",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "app", "version": "1.0.0"},
                    "node_modules/lodash": {"version": "4.17.21"},
                    "node_modules/@prisma/client": {"version": "5.19.1"},
                },
            }
            (app_dir / "package-lock.json").write_text(json.dumps(lock_data), encoding="utf-8")
            pkgs = parse_package_lock(app_dir / "package-lock.json")
            self.assertIn(("lodash", "4.17.21"), pkgs)
            self.assertIn(("@prisma/client", "5.19.1"), pkgs)

    def test_version_in_range_and_ghsa(self):
        self.assertTrue(_version_in_range("4.76.0", ">= 3.68.0, < 4.80.0"))
        self.assertFalse(_version_in_range("4.80.0", ">= 3.68.0, < 4.80.0"))
        self.assertTrue(_version_in_range("0.40.15", "<= 0.40.15"))
        self.assertFalse(_version_in_range("0.40.16", "<= 0.40.15"))

        mock_advisories = [
            {
                "state": "published",
                "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
                "cve_id": "CVE-2026-9999",
                "severity": "high",
                "summary": "Auth bypass in admin route",
                "vulnerabilities": [
                    {
                        "vulnerable_version_range": ">= 4.70.0, < 4.79.0",
                        "patched_versions": "4.79.0",
                    }
                ],
            },
            {
                "state": "published",
                "ghsa_id": "GHSA-old1-old2-old3",
                "severity": "low",
                "summary": "Old issue",
                "vulnerabilities": [
                    {
                        "vulnerable_version_range": "< 3.0.0",
                        "patched_versions": "3.0.0",
                    }
                ],
            },
        ]
        with patch("tools.maintenance.checkers.security._http_json", return_value=mock_advisories):
            vulns = check_github_advisories("langfuse/langfuse", "4.76.0")
            self.assertEqual(len(vulns), 1)
            self.assertEqual(vulns[0].vuln_id, "GHSA-xxxx-yyyy-zzzz (CVE-2026-9999)")
            self.assertEqual(vulns[0].severity, "HIGH")
            self.assertEqual(vulns[0].fixed_version, "4.79.0")

    def test_query_osv_batch_mocked(self):
        def fake_http(url, payload=None, timeout=10):
            if "querybatch" in url:
                return {"results": [{"vulns": [{"id": "GHSA-test-1234-5678"}]}]}
            if "GHSA-test-1234-5678" in url:
                return {
                    "id": "GHSA-test-1234-5678",
                    "summary": "Test vulnerability",
                    "database_specific": {"severity": "CRITICAL"},
                    "affected": [
                        {
                            "package": {"name": "requests"},
                            "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.4"}]}],
                        }
                    ],
                }
            return None

        with patch("tools.maintenance.checkers.security._http_json", side_effect=fake_http):
            vulns = query_osv_batch([("requests", "2.28.0", "PyPI")])
            self.assertEqual(len(vulns), 1)
            self.assertEqual(vulns[0].severity, "HIGH")
            self.assertEqual(vulns[0].fixed_version, "2.32.4")

    def test_container_inspection_and_hygiene_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "config.yaml").write_text("name: Demo\nversion: '1.0.0'\nslug: demo\n", encoding="utf-8")
            (app_dir / "build.yaml").write_text(
                "build_from:\n  amd64: 'ghcr.io/home-assistant/amd64-base-debian:trixie'\nargs:\n  APP_VERSION: '1.0.0'\n",
                encoding="utf-8",
            )
            (app_dir / "Dockerfile").write_text(
                "ARG BUILD_FROM\n"
                "FROM chrislusf/seaweedfs:latest AS sw\n"
                "FROM ${BUILD_FROM}\n"
                "RUN curl -fsSL https://example.com/install.sh | bash\n",
                encoding="utf-8",
            )
            components, unpinned = inspect_container_dependencies(app_dir)
            self.assertIn("Dockerfile FROM: chrislusf/seaweedfs:latest", unpinned)
            self.assertTrue(any(c["name"] == "ghcr.io/home-assistant/amd64-base-debian" for c in components))

            cfg = load_app_maintenance_config(app_dir)
            warnings = audit_dockerfile_and_build(cfg)
            self.assertTrue(any(":latest" in w for w in warnings))
            self.assertTrue(any("curl|sh" in w for w in warnings))

    def test_sync_app_version_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "Dockerfile").write_text(
                "FROM ghcr.io/langfuse/langfuse:4.76.0 AS web\n"
                "ARG LANGFUSE_VERSION=4.76.0\n",
                encoding="utf-8",
            )
            (app_dir / "build.yaml").write_text(
                "args:\n  LANGFUSE_VERSION: '4.76.0'\n  CLICKHOUSE_VERSION: '26.3'\n",
                encoding="utf-8",
            )
            (app_dir / "pyproject.toml").write_text(
                '[project]\nname = "demo"\nversion = "4.76.0"\n',
                encoding="utf-8",
            )
            modified = sync_app_version_references(app_dir, "4.76.0", "4.80.0")
            self.assertEqual(set(modified), {"Dockerfile", "build.yaml", "pyproject.toml"})
            self.assertIn("langfuse:4.80.0", (app_dir / "Dockerfile").read_text(encoding="utf-8"))
            self.assertIn("LANGFUSE_VERSION: '4.80.0'", (app_dir / "build.yaml").read_text(encoding="utf-8"))
            self.assertIn("CLICKHOUSE_VERSION: '26.3'", (app_dir / "build.yaml").read_text(encoding="utf-8"))
            self.assertIn('version = "4.80.0"', (app_dir / "pyproject.toml").read_text(encoding="utf-8"))

    def test_extract_security_mentions_and_telegram_format(self):
        mentions = _extract_security_mentions(
            "- Security fix: patch CVE-2026-12345 SSRF in webhook\n- Normal feature",
            "4.80.0",
        )
        self.assertTrue(any("CVE-2026-12345" in m for m in mentions))

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "config.yaml").write_text("name: Langfuse\nversion: '4.76.0'\nslug: langfuse\n", encoding="utf-8")
            cfg = load_app_maintenance_config(app_dir)
            prop = AppMaintenanceProposal(
                config=cfg,
                upstream_result=UpstreamCheckResult(
                    app_name="Langfuse",
                    current_version="4.76.0",
                    latest_version="4.80.0",
                    update_available=True,
                    update_type="minor",
                    release_notes_url="https://github.com/langfuse/langfuse/releases/tag/v4.80.0",
                    release_security_mentions=["4.80.0: CVE-2026-12345"],
                ),
                security_result=SecurityCheckResult(
                    app_name="Langfuse",
                    vulnerabilities=[
                        Vulnerability("langfuse/langfuse", "4.76.0", "GHSA-1111", "Bug", "HIGH", "GitHub Advisory", "4.80.0")
                    ],
                    supply_chain_warnings=["Unpinned ':latest' tag in Dockerfile: FROM chrislusf/seaweedfs:latest"],
                    scanned_targets=["secrets", "GHSA (langfuse/langfuse)", "Dockerfile/build.yaml"],
                    risk_level="HIGH",
                    summary="HIGH RISK: 0 secret findings, 1 CVEs/advisories",
                ),
                urgency="HIGH",
                summary="Security: HIGH RISK",
                target_version="4.80.0",
                requires_approval=True,
            )
            msg = format_telegram_plan([prop])
            self.assertIn("Security Scope:", msg)
            self.assertIn("GHSA-1111", msg)
            self.assertIn("Container Hygiene:", msg)
            self.assertIn("CVE-2026-12345", msg)


if __name__ == "__main__":
    unittest.main()
