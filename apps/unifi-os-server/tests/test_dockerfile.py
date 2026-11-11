"""Pytest suite for UniFi OS Server Dockerfile and entrypoint blueprint."""

from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE_PATH = ADDON_ROOT / "Dockerfile"
RUN_SH_PATH = ADDON_ROOT / "rootfs" / "run.sh"
DIAG_PATH = ADDON_ROOT / "rootfs" / "usr" / "local" / "bin" / "uos-diagnostics"


def test_dockerfile_structure():
    assert DOCKERFILE_PATH.exists(), "Dockerfile must exist"
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "AS extractor" in content, "Dockerfile must use a multi-stage extractor"
    assert "FROM scratch" in content, "Final stage must be clean scratch"
    assert "6.0.19" in content, "Dockerfile must reference 6.0.19"
    assert "systemctl3.py" in content, "Dockerfile must install systemctl3.py"
    assert 'ENTRYPOINT ["/run.sh"]' in content


def test_entrypoint_and_diagnostics_scripts():
    assert RUN_SH_PATH.exists(), "rootfs/run.sh must exist"
    assert (RUN_SH_PATH.stat().st_mode & 0o111) != 0, "rootfs/run.sh must be executable"
    run_content = RUN_SH_PATH.read_text(encoding="utf-8")
    assert "/data/uos_storage" in run_content, "run.sh must persist state to /data/uos_storage"
    assert "postgresql" in run_content
    assert "unifi" in run_content

    assert DIAG_PATH.exists(), "uos-diagnostics must exist"
    assert (DIAG_PATH.stat().st_mode & 0o111) != 0, "uos-diagnostics must be executable"
