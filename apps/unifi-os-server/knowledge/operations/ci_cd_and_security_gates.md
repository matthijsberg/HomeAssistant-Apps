---
id: ci-cd-and-security-gates
title: "Automated CI/CD Release Pipeline and Security Verification Gates"
type: "Operational Playbook"
status: "active"
trust: "human_reviewed"
generated: { by: "hermes/gemini-4-argon", at: "2026-10-16T15:30:00Z" }
verified:
  - { by: "human:matthijs", at: "2026-10-16T15:30:00Z" }
tags: [ci-cd, security, trivy, cve-2026-34908, github-actions]
sources:
  - id: ubiquiti-download-api
    resource: "https://download.svc.ui.com/v1/downloads/products/slugs/unifi-os-server"
    title: "Ubiquiti Official Download Metadata API"
  - id: bishopfox-sab064
    resource: "https://bishopfox.com/blog/popping-root-on-unifi-os-server-unauthenticated-rce-chain-detection-analysis"
    title: "Bishop Fox Analysis of UniFi OS Server SAB-064 (CVE-2026-34908 / 34909 / 34910)"
---

# Automated CI/CD Release Pipeline and Security Verification Gates

## Context & Rationale
UniFi OS Server acts as the central control plane for all switches, access points, and the `UXG-Lite` gateway. Past upstream advisories (such as **SAB-064** / `CVE-2026-34908` unauthenticated RCE on port `11443` and **SAB-067**) demonstrate that rapid, automated patching and pre-publish verification are mandatory.[^bishopfox-sab064]

## Normative Pipeline Gates

1. **Automated Upstream Polling:**
   - Queries `https://download.svc.ui.com/v1/downloads/products/slugs/unifi-os-server` daily.[^ubiquiti-download-api]
   - Validates version strings (`^[0-9]+(\.[0-9]+){2,3}$`) and HTTPS download URLs via environment variables (never inline GitHub Actions shell interpolation).
2. **Live Container Runtime Smoke Gate:**
   - Every image build boots an isolated container in CI and verifies that `postgresql`, `unifi-core`, `unifi`, and `nginx` reach active state and listen on ports `443`, `8080`, and `8443` within 180 seconds.
3. **Security & Attack Surface Hardening:**
   - **No SSO Bypass Port:** Port `7443` (`EXPOSE_NETWORK_APP`) is permanently disabled.
   - **Trivy & SAB-064 Gate:** Scans built images with Trivy and verifies that unauthenticated path traversal requests to `/api/ucore/manifest` or `/proxy/network/` are rejected by nginx.

[^ubiquiti-download-api]: Ubiquiti Official Download Metadata API
[^bishopfox-sab064]: Bishop Fox Analysis of UniFi OS Server SAB-064 (CVE-2026-34908 / 34909 / 34910)
