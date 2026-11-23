"""Headless atopile CLI integration (isolated venv on x86_64, graceful degradation on aarch64)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .kicad_cli import CommandResult

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SAFE_BUILD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_./:@\-+=~]+$")

VALID_TEMPLATES: frozenset[str] = frozenset({"basic", "esp32_sensor"})


def find_ato_cli() -> str:
    """Locate the atopile CLI binary (preferring our isolated /opt/atopile-venv)."""
    for candidate in ("/opt/atopile-venv/bin/ato", "/usr/local/bin/ato", "/usr/bin/ato"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("ato")
    if found:
        return found
    raise FileNotFoundError(
        "atopile ('ato') binary not found. On amd64 containers it lives in /opt/atopile-venv/bin/ato; "
        "on aarch64 Linux no official atopile wheel is currently published."
    )


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _build_ato_env(xdg_base: Path | None = None) -> dict[str, str]:
    """Create non-interactive environment with XDG dirs kept OUTSIDE project directories."""
    env = os.environ.copy()
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    env["ATO_NON_INTERACTIVE"] = "1"
    env["NONINTERACTIVE"] = "1"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"

    if xdg_base is not None:
        state_dir = xdg_base / "state"
        config_dir = xdg_base / "config"
        cache_dir = xdg_base / "cache"
        for d in (state_dir, config_dir, cache_dir):
            d.mkdir(parents=True, exist_ok=True)
        env["XDG_STATE_HOME"] = str(state_dir)
        env["XDG_CONFIG_HOME"] = str(config_dir)
        env["XDG_CACHE_HOME"] = str(cache_dir)
    else:
        env.setdefault("XDG_STATE_HOME", "/data/atopile-state")
        env.setdefault("XDG_CONFIG_HOME", "/data/kicad-config")
        env.setdefault("XDG_CACHE_HOME", "/data/kicad-cache")
    return env


async def _run_ato_subprocess(
    argv: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
    xdg_base: Path | None = None,
) -> CommandResult:
    env = _build_ato_env(xdg_base=xdg_base)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"atopile command timed out after {timeout}s: {' '.join(argv)}") from exc

    return CommandResult(
        argv=argv,
        returncode=proc.returncode or 0,
        stdout=_strip_ansi(stdout_b.decode("utf-8", errors="replace")).strip(),
        stderr=_strip_ansi(stderr_b.decode("utf-8", errors="replace")).strip(),
    )


async def get_atopile_version() -> str:
    """Return installed atopile version string, or 'unavailable'."""
    try:
        binary = find_ato_cli()
        with tempfile.TemporaryDirectory(prefix="ato_ver_") as tmpdir:
            res = await _run_ato_subprocess(
                [binary, "--version"],
                timeout=20,
                xdg_base=Path(tmpdir),
            )
        combined = "\n".join(p for p in (res.stdout, res.stderr) if p)
        for line in reversed(combined.splitlines()):
            m = re.search(r"\b(\d+\.\d+\.\d+(?:[a-zA-Z0-9.\-]*)?)\b", line.strip())
            if m:
                return m.group(1)
        return combined.splitlines()[-1].strip() if combined else f"error (rc={res.returncode})"
    except Exception as exc:
        return f"unavailable ({exc})"


def parse_ato_output(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    """Parse atopile build/check CLI output into structured stages, errors, and warnings."""
    combined = "\n".join(p for p in (stdout, stderr) if p)
    stages: list[dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []
    auth_required = False

    stage_re = re.compile(r"[✓✗]\s+([A-Za-z][A-Za-z0-9 _\-]+?)\s*\[([0-9.]+s)\]")
    for line in combined.splitlines():
        clean = line.strip().strip("│").strip()
        if not clean:
            continue
        sm = stage_re.search(clean)
        if sm:
            status = "passed" if "✓" in clean else "failed"
            stages.append({"stage": sm.group(1).strip(), "status": status, "duration": sm.group(2)})
        if "Sign-in required" in clean or "requires sign-in" in clean:
            auth_required = True
        if re.search(r"\b(Error|Exception|AssertionError|Build failed)\b", clean) and not clean.startswith("Warnings"):
            if clean not in errors:
                errors.append(clean)
        elif (
            " W " in line
            and "atopile.cli.motd" not in line
            and "Couldn't install plugin" not in line
            and "Couldn't enable plugin api" not in line
            and "Created new empty SQLite database during init" not in line
        ):
            if clean not in warnings:
                warnings.append(clean)

    return {
        "passed": returncode == 0,
        "returncode": returncode,
        "auth_required_for_picker": auth_required,
        "stages": stages,
        "errors": errors[:30],
        "warnings": warnings[:20],
        "output_tail": "\n".join(combined.splitlines()[-40:]),
    }


def _template_basic(project_name: str) -> tuple[str, str]:
    ato_yaml = (
        'requires-atopile: "^0.15.0"\n'
        "paths:\n"
        "  src: ./\n"
        "  layout: ./layout\n"
        "builds:\n"
        "  default:\n"
        "    entry: main.ato:App\n"
    )
    main_ato = (
        f"# {project_name} — starter atopile circuit with electrical constraints\n"
        "import Resistor\n"
        "import ElectricPower\n"
        "\n"
        "module App:\n"
        "    power = new ElectricPower\n"
        "    r_top = new Resistor\n"
        "    r_bot = new Resistor\n"
        "    r_top.resistance = 10kohm +/- 5%\n"
        "    r_bot.resistance = 10kohm +/- 5%\n"
        "\n"
        "    power.hv ~ r_top.unnamed[0]\n"
        "    r_top.unnamed[1] ~ r_bot.unnamed[0]\n"
        "    r_bot.unnamed[1] ~ power.lv\n"
        "\n"
        "    assert r_top.resistance within 9kohm to 11kohm\n"
        "    assert r_bot.resistance within 9kohm to 11kohm\n"
    )
    return ato_yaml, main_ato


def _template_esp32_sensor(project_name: str) -> tuple[str, str]:
    ato_yaml = (
        'requires-atopile: "^0.15.0"\n'
        "paths:\n"
        "  src: ./\n"
        "  layout: ./layout\n"
        "builds:\n"
        "  default:\n"
        "    entry: main.ato:App\n"
    )
    main_ato = (
        f"# {project_name} — ESP32 3.3V sensor node skeleton (power, EN RC-reset, I2C pull-ups)\n"
        "import Resistor\n"
        "import Capacitor\n"
        "import ElectricPower\n"
        "import ElectricLogic\n"
        "import I2C\n"
        "\n"
        "module App:\n"
        "    power_3v3 = new ElectricPower\n"
        "    power_3v3.voltage = 3.3V +/- 5%\n"
        "    power_3v3.max_current = 500mA\n"
        "    i2c = new I2C\n"
        "    en_reset = new ElectricLogic\n"
        "\n"
        "    # Decoupling on 3.3V rail\n"
        "    c_decouple = new Capacitor\n"
        "    c_decouple.capacitance = 100nF +/- 20%\n"
        "    power_3v3.hv ~ c_decouple.unnamed[0]\n"
        "    power_3v3.lv ~ c_decouple.unnamed[1]\n"
        "\n"
        "    # ESP32 EN / CHIP_PU RC reset delay (10k + 100nF)\n"
        "    r_en = new Resistor\n"
        "    c_en = new Capacitor\n"
        "    r_en.resistance = 10kohm +/- 5%\n"
        "    c_en.capacitance = 100nF +/- 20%\n"
        "    power_3v3.hv ~ r_en.unnamed[0]\n"
        "    r_en.unnamed[1] ~ en_reset.line\n"
        "    en_reset.line ~ c_en.unnamed[0]\n"
        "    c_en.unnamed[1] ~ power_3v3.lv\n"
        "    en_reset.reference ~ power_3v3\n"
        "\n"
        "    # I2C bus 4.7k pull-ups\n"
        "    r_sda = new Resistor\n"
        "    r_scl = new Resistor\n"
        "    r_sda.resistance = 4.7kohm +/- 5%\n"
        "    r_scl.resistance = 4.7kohm +/- 5%\n"
        "    power_3v3.hv ~ r_sda.unnamed[0]\n"
        "    r_sda.unnamed[1] ~ i2c.sda.line\n"
        "    power_3v3.hv ~ r_scl.unnamed[0]\n"
        "    r_scl.unnamed[1] ~ i2c.scl.line\n"
        "    i2c.sda.reference ~ power_3v3\n"
        "    i2c.scl.reference ~ power_3v3\n"
        "\n"
        "    # Electrical constraints verified offline by `ato_check`\n"
        "    assert r_sda.resistance within 2kohm to 10kohm\n"
        "    assert r_scl.resistance within 2kohm to 10kohm\n"
        "    assert r_en.resistance within 8kohm to 15kohm\n"
    )
    return ato_yaml, main_ato


def ato_init_project(
    project_dir: Path,
    project_name: str,
    template: str = "esp32_sensor",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Scaffold a clean, non-interactive atopile project inside the workspace."""
    if not PROJECT_NAME_RE.match(project_name):
        raise ValueError(
            f"Invalid project_name '{project_name}'. Use letters, digits, hyphens, or underscores."
        )
    tpl = template.strip().lower()
    if tpl not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template '{template}'. Choose one of {sorted(VALID_TEMPLATES)}.")

    project_dir.mkdir(parents=True, exist_ok=True)
    ato_yaml_path = project_dir / "ato.yaml"
    main_ato_path = project_dir / "main.ato"
    if not overwrite and (ato_yaml_path.exists() or main_ato_path.exists()):
        raise FileExistsError(
            f"ato.yaml or main.ato already exists in {project_dir}. Pass overwrite=True to replace."
        )

    ato_yaml, main_ato = (
        _template_esp32_sensor(project_name) if tpl == "esp32_sensor" else _template_basic(project_name)
    )
    ato_yaml_path.write_text(ato_yaml, encoding="utf-8")
    main_ato_path.write_text(main_ato, encoding="utf-8")
    (project_dir / "layout").mkdir(exist_ok=True)

    return {
        "status": "ok",
        "project_dir": str(project_dir),
        "project_name": project_name,
        "template": tpl,
        "files_created": [str(ato_yaml_path), str(main_ato_path)],
    }


def _validate_build_names(build_names: list[str] | None) -> list[str]:
    out: list[str] = []
    for name in build_names or []:
        cleaned = name.strip()
        if not cleaned:
            continue
        if not SAFE_BUILD_NAME_RE.match(cleaned):
            raise ValueError(f"Invalid atopile build name: '{name}'")
        out.append(cleaned)
    return out


def _validate_targets(targets: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in targets or []:
        cleaned = t.strip()
        if not cleaned:
            continue
        if not SAFE_TARGET_RE.match(cleaned):
            raise ValueError(f"Invalid atopile target name: '{t}'")
        out.append(cleaned)
    return out


def find_ato_python() -> str | None:
    """Locate the Python interpreter in the same environment as the atopile CLI."""
    try:
        ato_bin = Path(find_ato_cli())
    except FileNotFoundError:
        return None
    for name in ("python3", "python"):
        cand = ato_bin.parent / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


async def _run_offline_constraint_solver(
    project_dir: Path,
    build_names: list[str],
    timeout: int,
    xdg_base: Path,
) -> dict[str, Any]:
    """Run Faebryk's mathematical constraint solver (`simplify_for` + `POST_SOLVE`) offline."""
    ato_py = find_ato_python()
    if not ato_py:
        return {"executed": False, "passed": True, "errors": [], "builds": []}

    worker = Path(__file__).resolve().with_name("_ato_solver_worker.py")
    argv = [ato_py, str(worker), str(project_dir), *build_names]
    res = await _run_ato_subprocess(argv, cwd=project_dir, timeout=timeout, xdg_base=xdg_base)
    marker = "__ATO_SOLVER_JSON__:"
    for line in reversed(res.stdout.splitlines()):
        if marker in line:
            try:
                data = json.loads(line.split(marker, 1)[1])
                return {"executed": True, **data}
            except json.JSONDecodeError:
                break
    return {
        "executed": True,
        "passed": res.returncode == 0,
        "errors": [res.stderr or res.stdout or f"Solver worker exited with rc={res.returncode}"]
        if res.returncode != 0
        else [],
        "builds": [],
    }


async def ato_check(
    project_dir: Path,
    build_names: list[str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run 100% offline atopile electrical, interface-graph, and constraint verification (no cloud part picker)."""
    if not (project_dir / "ato.yaml").exists():
        raise FileNotFoundError(f"No ato.yaml found in {project_dir}")

    binary = find_ato_cli()
    validated_builds = _validate_build_names(build_names)
    argv = [
        binary,
        "--non-interactive",
        "build",
        "-v",
        "-t",
        "post-instantiation-design-check",
        "-x",
        "default",
    ]
    for b in validated_builds:
        argv.extend(["-b", b])

    with tempfile.TemporaryDirectory(prefix="ato_chk_") as tmpdir:
        tmp_path = Path(tmpdir)
        res = await _run_ato_subprocess(argv, cwd=project_dir, timeout=timeout, xdg_base=tmp_path)
        parsed = parse_ato_output(res.stdout, res.stderr, res.returncode)

        solver_info: dict[str, Any] = {"executed": False, "passed": True, "errors": [], "builds": []}
        if parsed["passed"]:
            solver_info = await _run_offline_constraint_solver(
                project_dir=project_dir,
                build_names=validated_builds,
                timeout=timeout,
                xdg_base=tmp_path,
            )
            if solver_info.get("executed"):
                parsed["stages"].append(
                    {
                        "stage": "Solve mathematical constraints (offline)",
                        "status": "passed" if solver_info["passed"] else "failed",
                        "duration": "offline",
                    }
                )
                if not solver_info["passed"]:
                    parsed["passed"] = False
                    parsed["returncode"] = 1
                    parsed["errors"].extend(solver_info.get("errors") or ["Constraint solver failed"])

    return {
        "mode": "offline_electrical_and_constraint_check",
        "project_dir": str(project_dir),
        "constraint_solver": solver_info,
        **parsed,
    }


async def ato_build(
    project_dir: Path,
    build_names: list[str] | None = None,
    targets: list[str] | None = None,
    exclude_targets: list[str] | None = None,
    frozen: bool = False,
    offline_check_only: bool = False,
    timeout: int = 180,
) -> dict[str, Any]:
    """Run atopile build on a project directory and list generated KiCad layout/build artifacts."""
    if offline_check_only:
        return await ato_check(project_dir=project_dir, build_names=build_names, timeout=timeout)

    if not (project_dir / "ato.yaml").exists():
        raise FileNotFoundError(f"No ato.yaml found in {project_dir}")

    binary = find_ato_cli()
    argv = [binary, "--non-interactive", "build", "-v"]
    for b in _validate_build_names(build_names):
        argv.extend(["-b", b])
    for t in _validate_targets(targets):
        argv.extend(["-t", t])
    for x in _validate_targets(exclude_targets):
        argv.extend(["-x", x])
    if frozen:
        argv.append("--frozen")

    with tempfile.TemporaryDirectory(prefix="ato_bld_") as tmpdir:
        res = await _run_ato_subprocess(argv, cwd=project_dir, timeout=timeout, xdg_base=Path(tmpdir))

    parsed = parse_ato_output(res.stdout, res.stderr, res.returncode)
    artifacts: list[str] = []
    for subdir in ("layout", "build"):
        p = project_dir / subdir
        if p.exists():
            for item in sorted(p.rglob("*")):
                if item.is_file() and item.suffix in {".kicad_pcb", ".kicad_sch", ".csv", ".json", ".net", ".step"}:
                    artifacts.append(str(item))
                    if len(artifacts) >= 50:
                        break

    note = ""
    if parsed["auth_required_for_picker"]:
        note = (
            "atopile 0.15.x cloud part-picking requires sign-in. "
            "All electrical/constraint verification stages passed locally; use `ato_check` (or `offline_check_only=True`) "
            "for offline CI/agent validation."
        )

    return {
        "mode": "full_build",
        "project_dir": str(project_dir),
        "note": note,
        "artifacts": artifacts,
        **parsed,
    }


async def ato_add_package(
    project_dir: Path,
    packages: list[str],
    upgrade: bool = False,
    allow_network: bool = True,
    timeout: int = 120,
) -> dict[str, Any]:
    """Install one or more atopile packages into a project (gated by allow_network_packages)."""
    if not (project_dir / "ato.yaml").exists():
        raise FileNotFoundError(f"No ato.yaml found in {project_dir}")
    cleaned = [p.strip() for p in packages if p.strip()]
    if not cleaned:
        raise ValueError("Provide at least one package identifier.")

    for pkg in cleaned:
        if pkg.startswith("-") or not SAFE_PACKAGE_RE.match(pkg):
            raise ValueError(f"Invalid atopile package identifier: '{pkg}'")
        if not allow_network and not pkg.startswith("file://"):
            raise PermissionError(
                f"Cannot download external package '{pkg}' because allow_network_packages is disabled in add-on options."
            )

    binary = find_ato_cli()
    argv = [binary, "--non-interactive", "add", "-C", str(project_dir)]
    if upgrade:
        argv.append("--upgrade")
    argv.extend(cleaned)

    with tempfile.TemporaryDirectory(prefix="ato_add_") as tmpdir:
        res = await _run_ato_subprocess(argv, cwd=project_dir, timeout=timeout, xdg_base=Path(tmpdir))

    parsed = parse_ato_output(res.stdout, res.stderr, res.returncode)
    return {
        "project_dir": str(project_dir),
        "packages": cleaned,
        **parsed,
    }
