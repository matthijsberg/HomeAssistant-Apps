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
    check_app_upstream,
    inspect_container_dependencies,
)
from tools.maintenance.checkers.security import (
    Vulnerability,
    SecurityCheckResult,
    _dedupe_vulns,
    _version_in_range,
    audit_dockerfile_and_build,
    check_app_code_scanning_alerts,
    check_app_dependabot_alerts,
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

    def test_ubiquiti_fus_upstream_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "config.yaml").write_text("name: UOS\nversion: '6.0.21-1'\nslug: unifi_os_server\n", encoding="utf-8")
            (app_dir / "build.yaml").write_text(
                "args:\n  UOS_SERVER_VERSION: '6.0.21'\n  UNIFI_NETWORK_TARGET: '10.6.109'\n",
                encoding="utf-8",
            )
            (app_dir / "maintenance.yaml").write_text(
                "upstream:\n"
                "  ubiquiti_products:\n"
                "    - product: unifi-os-server\n"
                "      label: UniFi OS Server\n"
                "      platform: linux-x64\n"
                "      build_arg: UOS_SERVER_VERSION\n"
                "    - product: unifi\n"
                "      label: UniFi Network\n"
                "      platform: uos-deb13-amd64\n"
                "      build_arg: UNIFI_NETWORK_TARGET\n",
                encoding="utf-8",
            )
            cfg = load_app_maintenance_config(app_dir)

            def fake_fus(url, timeout=10):
                if "unifi-os-server" in url:
                    return {"_embedded": {"firmware": [{"version": "v5.1.42", "_links": {"data": {"href": "https://example.com/uos"}}}]}}
                if "product~~unifi" in url:
                    return {"_embedded": {"firmware": [{"version": "v11.0.99-37236-1", "_links": {"data": {"href": "https://example.com/net.deb"}}}]}}
                return None

            with patch("tools.maintenance.checkers.upstream._http_get_json", side_effect=fake_fus):
                res = check_app_upstream(cfg)
            self.assertTrue(res.update_available)
            self.assertEqual(res.update_type, "major")
            self.assertIn("UniFi Network", " ".join(res.details))
            self.assertNotIn("5.1.42 ->", " ".join(res.details))

    def test_dependabot_and_code_scanning_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "apps" / "mantis-security-agent"
            app_dir.mkdir(parents=True)
            (app_dir / "config.yaml").write_text(
                "name: Mantis Security Agent\nversion: '1.1.2'\nslug: mantis_security_agent\n",
                encoding="utf-8",
            )
            cfg = load_app_maintenance_config(app_dir)

            dep_alerts = [
                {
                    "dependency": {
                        "manifest_path": "apps/mantis-security-agent/requirements.txt",
                        "package": {"name": "fastapi", "ecosystem": "pip"},
                    },
                    "security_advisory": {
                        "ghsa_id": "GHSA-aaaa-bbbb-cccc",
                        "cve_id": "CVE-2026-55555",
                        "severity": "high",
                        "summary": "FastAPI header parsing issue",
                    },
                    "security_vulnerability": {
                        "severity": "high",
                        "vulnerable_version_range": "== 0.115.0",
                        "first_patched_version": {"identifier": "0.115.5"},
                    },
                },
                {
                    "dependency": {
                        "manifest_path": "apps/other-app/requirements.txt",
                        "package": {"name": "requests", "ecosystem": "pip"},
                    },
                    "security_advisory": {"ghsa_id": "GHSA-other", "severity": "high", "summary": "Other"},
                    "security_vulnerability": {"severity": "high"},
                },
                {
                    "dependency": {
                        "manifest_path": "apps/mantis-security-agent/requirements.txt",
                        "package": {"name": "urllib3", "ecosystem": "pip"},
                    },
                    "security_advisory": {"ghsa_id": "GHSA-low", "severity": "low", "summary": "Low"},
                    "security_vulnerability": {"severity": "low"},
                },
            ]
            with patch("tools.maintenance.checkers.security.fetch_repo_dependabot_alerts", return_value=dep_alerts):
                ok, vulns = check_app_dependabot_alerts(cfg, "owner/repo")
            self.assertTrue(ok)
            self.assertEqual(len(vulns), 1)
            self.assertEqual(vulns[0].package, "fastapi")
            self.assertEqual(vulns[0].fixed_version, "0.115.5")
            self.assertIn("CVE-2026-55555", vulns[0].vuln_id)

            # Deduplication between OSV and Dependabot for the same CVE/GHSA
            dup = Vulnerability("fastapi", "0.115.0", "GHSA-aaaa-bbbb-cccc", "Dup", "HIGH", "PyPI", "0.115.5")
            self.assertEqual(len(_dedupe_vulns([dup, vulns[0]])), 1)

            cs_alerts = [
                {
                    "rule": {"id": "CVE-2026-99999", "security_severity_level": "critical", "description": "Critical OpenSSL flaw"},
                    "most_recent_instance": {
                        "category": "trivy-image-mantis-security-agent",
                        "location": {"path": "usr/lib/libssl.so.3"},
                    },
                },
                {
                    "rule": {"id": "DS-0026", "security_severity_level": "low", "description": "Add HEALTHCHECK"},
                    "most_recent_instance": {
                        "category": "trivy-fs-apps",
                        "location": {"path": "mantis-security-agent/Dockerfile"},
                    },
                },
            ]
            with patch("tools.maintenance.checkers.security.fetch_repo_code_scanning_alerts", return_value=cs_alerts):
                cs_ok, cs_vulns = check_app_code_scanning_alerts(cfg, "owner/repo")
            self.assertTrue(cs_ok)
            self.assertEqual(len(cs_vulns), 1)
            self.assertEqual(cs_vulns[0].vuln_id, "CVE-2026-99999")

            # Telegram plan renders repo-level Dependabot PRs
            prop = AppMaintenanceProposal(
                config=cfg,
                upstream_result=UpstreamCheckResult(app_name=cfg.app_name, current_version="1.1.2"),
                security_result=SecurityCheckResult(app_name=cfg.app_name),
                urgency="UP_TO_DATE",
                summary="Up to date",
                target_version="1.1.2",
                requires_approval=False,
            )
            fake_overview = {
                "repo_slug": "owner/repo",
                "prs": [{"number": 42, "title": "chore(ci): bump actions/checkout from 4 to 6", "html_url": "https://github.com/owner/repo/pull/42"}],
                "repo_alerts": [],
            }
            with patch("tools.maintenance.planner.get_repo_dependabot_overview", return_value=fake_overview):
                msg = format_telegram_plan([prop])
            self.assertIn("GitHub Dependabot", msg)
            self.assertIn("PR #42", msg)
            self.assertIn("actions/checkout", msg)


if __name__ == "__main__":
    unittest.main()
