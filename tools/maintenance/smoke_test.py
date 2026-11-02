"""
Pre-flight smoke test and mock run runner for HomeAssistant-Apps.
Validates HA addon schema, shell scripts, Python syntax, unit tests, and OKF bundle.
"""
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Dict, List, Tuple
import yaml
from .config import AppMaintenanceConfig
from .okf_manager import validate_okf_bundle

@dataclass
class SmokeTestResult:
    app_name: str
    passed: bool = True
    stage_results: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    output: str = ""

def _validate_addon_manifest(app_dir: Path) -> Tuple[bool, str]:
    cfg_file = app_dir / "config.yaml"
    if not cfg_file.exists():
        cfg_file = app_dir / "config.yaml.disabled"
    if not cfg_file.exists():
        return False, "config.yaml not found"

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return False, f"YAML parse error: {e}"

    required = ["name", "version", "slug", "description", "arch"]
    missing = [k for k in required if k not in data]
    if missing:
        return False, f"Missing required HA addon fields: {missing}"

    return True, "Manifest schema valid"

def _check_shell_scripts(app_dir: Path) -> Tuple[bool, str]:
    scripts = list(app_dir.glob("*.sh")) + list((app_dir / "scripts").glob("*.sh"))
    if (app_dir / "rootfs").exists():
        scripts += list((app_dir / "rootfs").rglob("*.sh")) + list((app_dir / "rootfs").rglob("run"))

    for script in scripts:
        if not script.is_file():
            continue
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Shell syntax error in {script.relative_to(app_dir)}: {res.stderr}"
    return True, "Shell scripts syntax verified"

def _check_python_syntax(app_dir: Path) -> Tuple[bool, str]:
    py_files = [p for p in app_dir.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]
    if not py_files:
        return True, "No Python files to compile"

    for py_file in py_files:
        res = subprocess.run(["/usr/bin/python3", "-m", "py_compile", str(py_file)], capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Python compile error in {py_file.relative_to(app_dir)}: {res.stderr}"
    return True, f"Python compile verified across {len(py_files)} files"

def _run_test_suite(config: AppMaintenanceConfig) -> Tuple[bool, str]:
    if not config.test_commands:
        return True, "No custom test commands defined"

    output_lines = []
    for cmd in config.test_commands:
        try:
            # Run via uv if pytest or python tool
            full_cmd = cmd
            if cmd.startswith("pytest"):
                full_cmd = f"uv run --with pytest {cmd}" if Path("/usr/local/bin/uv").exists() else cmd

            res = subprocess.run(
                full_cmd,
                shell=True,
                cwd=str(config.app_dir),
                capture_output=True,
                text=True,
                timeout=90
            )
            output_lines.append(f"Command '{cmd}' exit {res.returncode}:\n{res.stdout}\n{res.stderr}")
            if res.returncode != 0:
                return False, "\n".join(output_lines)
        except subprocess.TimeoutExpired:
            return False, f"Test command '{cmd}' timed out after 90 seconds"
        except Exception as e:
            return False, f"Error running '{cmd}': {e}"

    return True, "\n".join(output_lines)

def run_app_mock_and_smoke_test(config: AppMaintenanceConfig) -> SmokeTestResult:
    result = SmokeTestResult(app_name=config.app_name)
    logs = []

    # 1. Manifest schema
    ok_manifest, msg_manifest = _validate_addon_manifest(config.app_dir)
    result.stage_results["manifest"] = ok_manifest
    logs.append(f"[Manifest] {msg_manifest}")
    if not ok_manifest:
        result.passed = False
        result.errors.append(msg_manifest)

    # 2. Shell scripts
    ok_shell, msg_shell = _check_shell_scripts(config.app_dir)
    result.stage_results["shell"] = ok_shell
    logs.append(f"[Shell] {msg_shell}")
    if not ok_shell:
        result.passed = False
        result.errors.append(msg_shell)

    # 3. Python compilation
    ok_py, msg_py = _check_python_syntax(config.app_dir)
    result.stage_results["python_syntax"] = ok_py
    logs.append(f"[Python] {msg_py}")
    if not ok_py:
        result.passed = False
        result.errors.append(msg_py)

    # 4. OKF Bundle
    if config.security.okf_required:
        ok_okf, msg_okf = validate_okf_bundle(config.app_dir)
        result.stage_results["okf"] = ok_okf
        logs.append(f"[OKF v0.2] {msg_okf}")
        if not ok_okf:
            result.passed = False
            result.errors.append(f"OKF Error: {msg_okf}")

    # 5. Test Suite
    ok_tests, msg_tests = _run_test_suite(config)
    result.stage_results["tests"] = ok_tests
    logs.append(f"[Tests] {msg_tests[:300]}")
    if not ok_tests:
        result.passed = False
        result.errors.append("Unit tests failed")

    result.output = "\n".join(logs)
    return result
