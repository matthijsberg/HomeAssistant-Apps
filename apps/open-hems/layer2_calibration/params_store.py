"""
Layer 2: Model Parameter Store (single-writer access to heatpump_model_parameters.json)
=====================================================================================
Every writer of the model parameter file (learned forecaster, calibration API, offline
calibration scripts) goes through `update_params()`. It serialises writers with a
process-local lock plus an advisory file lock, re-reads the file from disk, applies the
caller's mutation and writes atomically. This prevents lost updates where one writer
saves a stale in-memory snapshot over changes made by another.
"""

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Union

DEFAULT_PARAMS_FILE = Path("/config/heatpump_model_parameters.json")

_THREAD_LOCK = threading.RLock()


@contextmanager
def _file_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    # Never create the parent directory: a missing /config means "not on the HEMS host" (e.g. CI).
    with open(lock_path, "a+") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def read_params(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """Reads the parameter file; returns {} when missing or unreadable."""
    p = Path(path) if path else DEFAULT_PARAMS_FILE
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] params_store: cannot read {p}: {e}")
        return {}


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        os.chmod(path, 0o644)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def update_params(
    mutator: Callable[[Dict[str, Any]], Optional[bool]],
    path: Union[str, Path, None] = None,
) -> Dict[str, Any]:
    """
    Read-modify-write under lock. `mutator` edits the freshly loaded dict in place.
    Returning False from the mutator skips the write (nothing changed).
    Returns the resulting parameter dict.
    """
    p = Path(path) if path else DEFAULT_PARAMS_FILE
    with _THREAD_LOCK, _file_lock(p):
        data = read_params(p)
        changed = mutator(data)
        if changed is not False:
            _atomic_write(p, data)
        return data


def _get_dotted(d: Dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_dotted(d: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def merge_owned_keys(
    source: Dict[str, Any],
    owned_keys: Iterable[str],
    path: Union[str, Path, None] = None,
) -> Dict[str, Any]:
    """
    Copies only the dotted `owned_keys` (e.g. "building.ua_base_w_per_k") from `source`
    into the on-disk parameters, leaving every other key as currently stored on disk.
    """
    keys = list(owned_keys)

    def _mut(data: Dict[str, Any]) -> bool:
        changed = False
        for k in keys:
            val = _get_dotted(source, k)
            if val is None:
                continue
            if _get_dotted(data, k) != val:
                _set_dotted(data, k, val)
                changed = True
        return changed

    return update_params(_mut, path)
