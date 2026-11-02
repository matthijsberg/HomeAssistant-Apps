#!/usr/bin/env python3
"""
HomeAssistant-Apps Weekly Maintenance Framework CLI.
Usage:
  python3 main.py check [--app <name>]
  python3 main.py plan [--app <name>]
  python3 main.py test <app_name>
  python3 main.py execute <app_name> --version <v> [--urgency <level>]
"""
import argparse
from pathlib import Path
import sys

from typing import Optional

# Ensure package imports resolve
tools_dir = Path(__file__).resolve().parent
repo_root = tools_dir.parent.parent
sys.path.insert(0, str(repo_root))

from tools.maintenance.config import load_app_maintenance_config
from tools.maintenance.planner import evaluate_app_maintenance, format_telegram_plan
from tools.maintenance.smoke_test import run_app_mock_and_smoke_test
from tools.maintenance.executor import execute_app_update

def get_apps_dirs(specific_app: Optional[str] = None):
    apps_base = repo_root / "apps"
    if specific_app:
        target = apps_base / specific_app
        if not target.is_dir():
            print(f"Error: App directory '{specific_app}' not found in {apps_base}")
            sys.exit(1)
        return [target]
    return sorted([d for d in apps_base.iterdir() if d.is_dir()])

def cmd_check(args):
    app_dirs = get_apps_dirs(args.app)
    print(f"Scanning {len(app_dirs)} Home Assistant app(s)...\n")
    for app_dir in app_dirs:
        proposal = evaluate_app_maintenance(app_dir)
        cfg = proposal.config
        status_icon = "🔴" if proposal.urgency == "HIGH" else "🟡" if proposal.urgency == "MEDIUM" else "🟢" if proposal.urgency == "LOW" else "✅"
        print(f"{status_icon} [{proposal.urgency}] {cfg.app_name} ({cfg.slug})")
        print(f"   Version: {cfg.current_version} -> {proposal.target_version}")
        print(f"   Summary: {proposal.summary}")
        if proposal.security_result.secrets_found:
            print(f"   ⚠️ Secrets: {proposal.security_result.secrets_found}")
        if proposal.security_result.vulnerabilities:
            print(f"   ⚠️ CVEs: {len(proposal.security_result.vulnerabilities)} vulnerabilities found")
        print()

def cmd_plan(args):
    app_dirs = get_apps_dirs(args.app)
    proposals = [evaluate_app_maintenance(d) for d in app_dirs]
    report = format_telegram_plan(proposals)
    print(report)

def cmd_test(args):
    app_dirs = get_apps_dirs(args.app)
    app_dir = app_dirs[0]
    config = load_app_maintenance_config(app_dir)
    print(f"Running pre-flight mock and smoke test for {config.app_name}...\n")
    result = run_app_mock_and_smoke_test(config)
    print(result.output)
    if result.passed:
        print("\n✅ All pre-flight tests and mock runs PASSED.")
    else:
        print(f"\n❌ Pre-flight checks FAILED with errors: {result.errors}")
        sys.exit(1)

def cmd_execute(args):
    app_dirs = get_apps_dirs(args.app)
    app_dir = app_dirs[0]
    config = load_app_maintenance_config(app_dir)
    print(f"Executing maintenance upgrade for {config.app_name} to v{args.version}...")
    res = execute_app_update(
        app_dir=app_dir,
        target_version=args.version,
        summary=args.summary or f"Upgrade to v{args.version}",
        urgency=args.urgency
    )
    if res.success:
        print(f"\n✅ Upgrade complete and verified!")
        print(f"   Branch: {res.branch_name}")
        print(f"   Commit SHA: {res.commit_sha}")
    else:
        print(f"\n❌ Upgrade failed: {res.error_message}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="HomeAssistant-Apps Maintenance Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Check
    p_check = subparsers.add_parser("check", help="Audit upstream and security status")
    p_check.add_argument("--app", help="Check specific app only")
    p_check.set_defaults(func=cmd_check)

    # Plan
    p_plan = subparsers.add_parser("plan", help="Generate Telegram maintenance proposal")
    p_plan.add_argument("--app", help="Plan for specific app only")
    p_plan.set_defaults(func=cmd_plan)

    # Test
    p_test = subparsers.add_parser("test", help="Run pre-flight smoke tests and mock run")
    p_test.add_argument("app", help="App name or directory")
    p_test.set_defaults(func=cmd_test)

    # Execute
    p_exec = subparsers.add_parser("execute", help="Execute approved maintenance update")
    p_exec.add_argument("app", help="App name or directory")
    p_exec.add_argument("--version", required=True, help="Target version to bump to")
    p_exec.add_argument("--urgency", default="LOW", choices=["HIGH", "MEDIUM", "LOW"], help="Urgency tier")
    p_exec.add_argument("--summary", default="", help="Summary of changes")
    p_exec.set_defaults(func=cmd_execute)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
