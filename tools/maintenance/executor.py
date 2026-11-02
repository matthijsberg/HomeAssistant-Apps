"""
Maintenance execution pipeline for HomeAssistant-Apps.
Handles branching, version bumping, smoke testing/mock run, OKF & doc sync, and git commits.
"""
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Optional, Tuple
from .config import AppMaintenanceConfig, load_app_maintenance_config
from .smoke_test import run_app_mock_and_smoke_test, SmokeTestResult
from .checkers.security import run_mantis_diff_review
from .docs_manager import sync_manifest_version, prepend_changelog_entry, sync_readme_version
from .okf_manager import append_okf_maintenance_log, validate_okf_bundle

@dataclass
class ExecutionResult:
    app_name: str
    target_version: str
    success: bool
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    error_message: Optional[str] = None
    smoke_test: Optional[SmokeTestResult] = None

def _run_git(args: list, cwd: Path) -> Tuple[int, str, str]:
    res = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def execute_app_update(app_dir: Path, target_version: str, summary: str, urgency: str = "LOW") -> ExecutionResult:
    config = load_app_maintenance_config(app_dir)
    repo_root = app_dir.parent.parent
    branch_name = f"maint/{config.slug}-v{target_version}"

    # 1. Create maintenance branch
    code, out, err = _run_git(["checkout", "-b", branch_name], repo_root)
    if code != 0:
        # If branch already exists, checkout
        _run_git(["checkout", branch_name], repo_root)

    # 2. Bump version in manifest
    if not sync_manifest_version(app_dir, target_version):
        _run_git(["checkout", "main"], repo_root)
        return ExecutionResult(
            app_name=config.app_name,
            target_version=target_version,
            success=False,
            error_message="Failed to update version in config.yaml"
        )

    # Reload config with new version
    config = load_app_maintenance_config(app_dir)

    # 3. Run mock and smoke tests
    smoke_res = run_app_mock_and_smoke_test(config)
    if not smoke_res.passed:
        # Revert changes and clean up
        _run_git(["checkout", "--", str(app_dir)], repo_root)
        _run_git(["checkout", "main"], repo_root)
        return ExecutionResult(
            app_name=config.app_name,
            target_version=target_version,
            success=False,
            branch_name=branch_name,
            error_message=f"Pre-flight mock run failed:\n{smoke_res.output}",
            smoke_test=smoke_res
        )

    # 4. Mantis Security Review pass (Gemini 4 Argon)
    mantis_summary = ""
    if config.security.mantis_review:
        code, diff_out, _ = _run_git(["diff", "HEAD", "--", str(app_dir)], repo_root)
        if diff_out:
            mantis_ok, mantis_msg, _ = run_mantis_diff_review(
                diff_text=diff_out,
                context=f"Home Assistant add-on {config.app_name} on HAOS, behind Ingress, internal network only",
                model=config.security.mantis_model
            )
            if not mantis_ok:
                _run_git(["checkout", "--", str(app_dir)], repo_root)
                _run_git(["checkout", "main"], repo_root)
                return ExecutionResult(
                    app_name=config.app_name,
                    target_version=target_version,
                    success=False,
                    branch_name=branch_name,
                    error_message=f"Mantis security review failed: {mantis_msg}"
                )
            mantis_summary = f"Security: {mantis_msg}"

    # 5. Synchronize documentation & OKF bundle
    full_summary = f"{summary}. {mantis_summary}".strip()
    prepend_changelog_entry(app_dir, target_version, full_summary)
    sync_readme_version(app_dir, target_version)
    if config.docs.sync_okf:
        append_okf_maintenance_log(app_dir, target_version, summary, urgency)
        okf_ok, okf_err = validate_okf_bundle(app_dir)
        if not okf_ok:
            _run_git(["checkout", "--", str(app_dir)], repo_root)
            _run_git(["checkout", "main"], repo_root)
            return ExecutionResult(
                app_name=config.app_name,
                target_version=target_version,
                success=False,
                error_message=f"OKF validation failed after doc sync: {okf_err}"
            )

    # 5. Commit changes to maintenance branch
    _run_git(["add", str(app_dir)], repo_root)
    commit_msg = f"chore({config.slug}): upgrade to v{target_version} [verified]"
    code, out, err = _run_git(["commit", "-m", commit_msg], repo_root)
    
    code, sha, _ = _run_git(["rev-parse", "--short", "HEAD"], repo_root)

    return ExecutionResult(
        app_name=config.app_name,
        target_version=target_version,
        success=True,
        branch_name=branch_name,
        commit_sha=sha if code == 0 else "unknown",
        smoke_test=smoke_res
    )
