import os
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any


def run_shellcheck(target_dir: Path, timeout: int = 45) -> List[Dict[str, Any]]:
    """
    Run ShellCheck on all shell scripts found in target directory.
    """
    shellcheck_bin = shutil.which("shellcheck")
    if not shellcheck_bin:
        return []

    scripts = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "vendor", "__pycache__")]
        for f in files:
            if f.endswith(".sh") or f in ("run", "finish"):
                s_path = Path(root) / f
                if not s_path.is_symlink():
                    scripts.append(str(s_path))

    if not scripts:
        return []

    results = []
    # SCAN-03: Process in batches of 50 to avoid OS ARG_MAX limits
    batch_size = 50
    for i in range(0, len(scripts), batch_size):
        batch = scripts[i:i + batch_size]
        cmd = [shellcheck_bin, "-f", "json"] + batch
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if res.stdout.strip():
                data = json.loads(res.stdout)
                for c in data:
                    results.append({
                        "source": "shellcheck",
                        "code": f"SC{c.get('code')}",
                        "file": c.get("file"),
                        "start_line": c.get("line"),
                        "end_line": c.get("endLine", c.get("line")),
                        "message": c.get("message"),
                        "severity": c.get("level", "warning").upper(),
                    })
        except Exception:
            # SCAN-02: Do not convert scanner execution errors into findings
            continue

    return results
