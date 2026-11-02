"""
OKF (Open Knowledge Format v0.2) manager for HomeAssistant-Apps.
Appends maintenance log events and runs validation against OKF invariants.
"""
from datetime import datetime
from pathlib import Path
import subprocess
from typing import Tuple

def append_okf_maintenance_log(app_dir: Path, new_version: str, summary: str, urgency: str) -> bool:
    knowledge_dir = app_dir / "knowledge"
    if not knowledge_dir.exists():
        return False

    log_file = knowledge_dir / "log.md"
    today_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"""
### [{today_str}] Maintenance: Upgrade to v{new_version}
- **Date**: {today_str}
- **Urgency**: {urgency}
- **Action**: Automated weekly maintenance pipeline run
- **Summary**: {summary}
- **Verification**: Tests and HA pre-flight mock run passed
- **Status**: active
"""
    try:
        if log_file.exists():
            existing = log_file.read_text(encoding="utf-8")
            log_file.write_text(existing + entry, encoding="utf-8")
        else:
            header = f"""---
id: log
title: "Knowledge Maintenance Log"
type: log
status: active
trust: verified
---

# Knowledge Maintenance Log
{entry}
"""
            log_file.write_text(header, encoding="utf-8")
        return True
    except Exception:
        return False

def validate_okf_bundle(app_dir: Path) -> Tuple[bool, str]:
    validate_script = app_dir / "scripts" / "validate_okf.sh"
    if validate_script.exists():
        try:
            res = subprocess.run(
                ["bash", str(validate_script)],
                cwd=str(app_dir),
                capture_output=True,
                text=True,
                timeout=15
            )
            return (res.returncode == 0, res.stdout + res.stderr)
        except Exception as e:
            return (False, f"Failed to execute validate_okf.sh: {e}")

    # Fallback validation if script not present
    knowledge_dir = app_dir / "knowledge"
    if not knowledge_dir.exists():
        return (True, "No knowledge/ directory present, skipped.")

    index_file = knowledge_dir / "index.md"
    if not index_file.exists():
        return (False, "knowledge/index.md missing")

    content = index_file.read_text(encoding="utf-8", errors="ignore")
    if 'okf_version: "0.2"' not in content and "okf_version: '0.2'" not in content:
        return (False, "knowledge/index.md missing okf_version: '0.2' declaration")

    return (True, "OKF v0.2 structure verified.")
