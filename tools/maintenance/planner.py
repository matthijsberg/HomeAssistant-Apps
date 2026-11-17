"""
Maintenance planner and Telegram report generator for HomeAssistant-Apps.
Evaluates app status, assigns urgency, and produces structured proposals.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from .config import AppMaintenanceConfig, load_app_maintenance_config
from .checkers.upstream import check_app_upstream, UpstreamCheckResult
from .checkers.security import check_app_security, SecurityCheckResult, get_repo_dependabot_overview

@dataclass
class AppMaintenanceProposal:
    config: AppMaintenanceConfig
    upstream_result: UpstreamCheckResult
    security_result: SecurityCheckResult
    urgency: str  # "HIGH", "MEDIUM", "LOW", "UP_TO_DATE"
    summary: str
    target_version: str
    requires_approval: bool = False

def evaluate_app_maintenance(app_dir: Path) -> AppMaintenanceProposal:
    config = load_app_maintenance_config(app_dir)
    up_res = check_app_upstream(config)
    sec_res = check_app_security(config)

    urgency = "UP_TO_DATE"
    summary_parts = []
    target_version = config.current_version
    requires_approval = False

    # Assess security first (highest priority)
    if sec_res.risk_level == "HIGH":
        urgency = "HIGH"
        requires_approval = True
        summary_parts.append(f"Security: {sec_res.summary}")
    elif sec_res.risk_level == "MEDIUM":
        urgency = "MEDIUM"
        requires_approval = True
        summary_parts.append(f"Security: {sec_res.summary}")

    # Assess upstream next
    if up_res.update_available:
        requires_approval = True
        target_version = up_res.latest_version or config.current_version
        if up_res.update_type == "major":
            urgency = "HIGH"
            summary_parts.append(f"Upstream: Major upgrade available ({config.current_version} -> {target_version})")
        elif up_res.update_type == "minor":
            if urgency != "HIGH":
                urgency = "MEDIUM"
            summary_parts.append(f"Upstream: Minor update available ({config.current_version} -> {target_version})")
        elif up_res.update_type == "patch":
            if urgency not in ("HIGH", "MEDIUM"):
                urgency = "LOW"
            summary_parts.append(f"Upstream: Patch update available ({config.current_version} -> {target_version})")
        if up_res.release_security_mentions:
            if urgency == "LOW":
                urgency = "MEDIUM"
            summary_parts.append(f"Release notes security: {up_res.release_security_mentions[0]}")

    if sec_res.supply_chain_warnings:
        summary_parts.append(f"Hygiene: {sec_res.supply_chain_warnings[0]}")

    if not summary_parts:
        summary = "All checks passed. Version and dependencies are up to date."
    else:
        summary = "; ".join(summary_parts)

    return AppMaintenanceProposal(
        config=config,
        upstream_result=up_res,
        security_result=sec_res,
        urgency=urgency,
        summary=summary,
        target_version=target_version,
        requires_approval=requires_approval
    )

def _append_repo_dependabot_section(lines: List[str], proposals: List[AppMaintenanceProposal]) -> None:
    if not proposals:
        return
    overview = get_repo_dependabot_overview(proposals[0].config.app_dir)
    prs = overview.get("prs") or []
    repo_alerts = overview.get("repo_alerts") or []
    if not prs and not repo_alerts:
        return

    lines.append("")
    lines.append("🔄 *GitHub Dependabot & CI Dependencies*")
    for pr in prs[:5]:
        num = pr.get("number")
        title = str(pr.get("title") or "Dependabot PR")
        url = str(pr.get("html_url") or "")
        lines.append(f"• PR #{num}: {title}" + (f" ({url})" if url else ""))
    for alert in repo_alerts[:5]:
        fix_info = f", fix: {alert.fixed_version}" if alert.fixed_version else ""
        lines.append(f"• [{alert.severity}] {alert.vuln_id}: {alert.package}{fix_info} — {alert.summary}")


def format_telegram_plan(proposals: List[AppMaintenanceProposal]) -> str:
    lines = [
        "🛠 *Home Assistant Apps — Weekly Maintenance Report*",
        ""
    ]

    actionable = [p for p in proposals if p.requires_approval]
    up_to_date = [p for p in proposals if not p.requires_approval]

    if not actionable:
        lines.append("✅ All Home Assistant apps are fully up to date and verified clean.")
        lines.append(f"Checked {len(proposals)} apps. No maintenance required.")
        hygiene_apps = [p for p in up_to_date if p.security_result.supply_chain_warnings]
        if hygiene_apps:
            lines.append("")
            lines.append("Hygiene notes:")
            for p in hygiene_apps:
                lines.append(f"• {p.config.app_name}: {'; '.join(p.security_result.supply_chain_warnings)}")
        _append_repo_dependabot_section(lines, proposals)
        return "\n".join(lines)

    lines.append(f"Found {len(actionable)} app(s) requiring maintenance attention:\n")

    urgency_emojis = {
        "HIGH": "🔴 High Urgency",
        "MEDIUM": "🟡 Medium Urgency",
        "LOW": "🟢 Low Urgency"
    }

    for idx, prop in enumerate(actionable, 1):
        app = prop.config
        sec = prop.security_result
        up = prop.upstream_result
        lines.append(f"*{idx}. {app.app_name}* (`{app.slug}`)")
        lines.append(f"• Urgency: {urgency_emojis.get(prop.urgency, prop.urgency)}")
        lines.append(f"• Current Version: `{app.current_version}` ➔ Target: `{prop.target_version}`")
        lines.append(f"• Proposed Changes: {prop.summary}")
        if sec.scanned_targets:
            lines.append(f"• Security Scope: {', '.join(sec.scanned_targets)}")
        if sec.vulnerabilities:
            top_v = sec.vulnerabilities[:3]
            v_str = "; ".join(
                f"{v.vuln_id} ({v.package} {v.version}" + (f", fix: {v.fixed_version}" if v.fixed_version else "") + ")"
                for v in top_v
            )
            lines.append(f"• Advisories/CVEs: {v_str}")
        if up.release_security_mentions:
            lines.append(f"• Release Security Hints: {'; '.join(up.release_security_mentions[:2])}")
        if sec.supply_chain_warnings:
            lines.append(f"• Container Hygiene: {'; '.join(sec.supply_chain_warnings[:2])}")
        if up.release_notes_url:
            lines.append(f"• Release Notes: {up.release_notes_url}")
        lines.append(f"• Approval Request: Reply `Approve {app.slug}` or `Approve all` to execute.")
        lines.append("")

    if up_to_date:
        up_to_date_names = ", ".join(f"`{p.config.app_name}`" for p in up_to_date)
        lines.append(f"✓ Up to date ({len(up_to_date)}): {up_to_date_names}")
        hygiene_notes = [
            f"{p.config.app_name}: {p.security_result.supply_chain_warnings[0]}"
            for p in up_to_date
            if p.security_result.supply_chain_warnings
        ]
        if hygiene_notes:
            lines.append(f"• Hygiene notes: {' | '.join(hygiene_notes)}")

    _append_repo_dependabot_section(lines, proposals)
    return "\n".join(lines)
