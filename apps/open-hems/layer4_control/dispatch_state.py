"""
Layer 4: Persistent Dispatch State
==================================
Small, thread-safe, atomically written key/value store for actuator ownership facts that
must survive an add-on restart, e.g. "Open HEMS switched the CV master off" or the room
thermostat baseline. Without it a restart mid-run either latches a forced state or loses the
user's own setpoint.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_STATE_FILE = Path("/config/open_hems_dispatch_state.json")


class PersistentState:
    def __init__(self, path: Optional[Path] = DEFAULT_STATE_FILE):
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self._path or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[WARN] PersistentState: cannot read {self._path}: {e}")
            return {}

    def _save(self) -> None:
        if not self._path:
            return
        tmp = f"{self._path}.tmp.{os.getpid()}"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            print(f"[WARN] PersistentState: cannot write {self._path}: {e}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            val = self._data.get(key, default)
            return json.loads(json.dumps(val)) if isinstance(val, (dict, list)) else val

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
            self._save()


_DEFAULT_STATE: Optional[PersistentState] = None
_DEFAULT_LOCK = threading.Lock()


def get_dispatch_state() -> PersistentState:
    global _DEFAULT_STATE
    with _DEFAULT_LOCK:
        if _DEFAULT_STATE is None:
            _DEFAULT_STATE = PersistentState(DEFAULT_STATE_FILE)
        return _DEFAULT_STATE
