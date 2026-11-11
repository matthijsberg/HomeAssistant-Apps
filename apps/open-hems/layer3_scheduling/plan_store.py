"""
Layer 3: Plan Store & Recommendation Registry
==============================================
The single authoritative store and publication channel for HEMS plans.
Can be instantiated as an injected dependency for tests or accessed via
the singleton convenience method `get_plan_store()`.
Supports atomic local disk snapshot persistence for cold-boot resilience.

Concurrency contract:
- Published plans are immutable: `publish_plan()` stores a private deep copy, so a caller
  that keeps mutating its object can never change what readers see.
- Readers must treat the object returned by `get_plan()` as read-only.
- The in-flight DHW run commitment has exactly one writer (Layer 4 DhwRunSupervisor);
  planners only read it. Every commitment carries an expiry so it can never latch.
"""

import copy
import threading
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from dataclasses import asdict
from models.canonical import CanonicalDispatchPlan

DEFAULT_IN_FLIGHT_MAX_MINUTES = 150.0


class PlanStore:
    """Thread-safe store serving the active canonical dispatch plan."""

    _instance: Optional["PlanStore"] = None
    _class_lock = threading.Lock()

    def __init__(self, persistence_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._persist_lock = threading.Lock()
        self._current_plan: Optional[CanonicalDispatchPlan] = None
        self._last_updated: Optional[datetime] = None
        self._plan_version: int = 0
        self._publication_history: List[Dict[str, Any]] = []
        self._persistence_path = persistence_path
        self._in_flight_dhw_run: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # In-flight DHW run commitment (single writer: Layer 4 supervisor)
    # ------------------------------------------------------------------
    def register_in_flight_run(
        self,
        target_temp_c: float,
        mode: str,
        started_at: Optional[datetime] = None,
        max_duration_min: float = DEFAULT_IN_FLIGHT_MAX_MINUTES,
        source: str = "dispatcher",
    ) -> None:
        """Register an active DHW run commitment. It expires after `max_duration_min`."""
        start = started_at or datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        expires = start + timedelta(minutes=float(max_duration_min))
        with self._lock:
            self._in_flight_dhw_run = {
                "active": True,
                "target_temp_c": float(target_temp_c),
                "mode": str(getattr(mode, "value", mode)),
                "started_at": start.isoformat(),
                "expires_at": expires.isoformat(),
                "source": source,
            }

    def clear_in_flight_run(self) -> None:
        """Clear the active in-flight run."""
        with self._lock:
            self._in_flight_dhw_run = None

    def get_in_flight_run(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Return the current in-flight run commitment, or None if absent or expired."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            run = self._in_flight_dhw_run
            if not run:
                return None
            exp_raw = run.get("expires_at")
            if exp_raw:
                try:
                    if now >= datetime.fromisoformat(exp_raw):
                        self._in_flight_dhw_run = None
                        return None
                except (TypeError, ValueError):
                    self._in_flight_dhw_run = None
                    return None
            return dict(run)

    # ------------------------------------------------------------------
    # Plan publication
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls, persistence_path: Optional[Path] = None) -> "PlanStore":
        with cls._class_lock:
            if cls._instance is None:
                default_path = persistence_path or Path("/config/open_hems_plan_snapshot.json")
                cls._instance = cls(persistence_path=default_path)
            return cls._instance

    def publish_plan(self, plan: CanonicalDispatchPlan) -> None:
        """Publish a newly computed canonical dispatch plan (stored as a private copy)."""
        frozen = copy.deepcopy(plan)
        with self._lock:
            self._current_plan = frozen
            self._last_updated = datetime.now(timezone.utc)
            self._plan_version += 1
            self._publication_history.append({
                "version": self._plan_version,
                "timestamp": self._last_updated.isoformat(),
                "slot_count": len(frozen.slots),
                "is_fresh": frozen.is_fresh,
                "dhw_mode": frozen.dhw_summary.planned_mode if frozen.dhw_summary else None,
                "dynamic_peaks_count": len(frozen.dynamic_peaks)
            })
            if len(self._publication_history) > 50:
                self._publication_history = self._publication_history[-50:]
            version = self._plan_version

        # Disk persistence outside the read lock; the frozen copy is never mutated.
        if self._persistence_path:
            self._persist(frozen, version)

    def _persist(self, plan: CanonicalDispatchPlan, version: int) -> None:
        target = self._persistence_path
        if target is None:
            return
        with self._persist_lock:
            with self._lock:
                if version != self._plan_version:
                    return  # a newer plan was published meanwhile; it persists itself
            try:
                tmp_file = target.with_suffix(".tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(asdict(plan), f, indent=2, default=str)
                tmp_file.replace(target)
            except Exception:
                # Persistence failure must not crash the memory pipeline
                pass

    def get_plan(self) -> Optional[CanonicalDispatchPlan]:
        """Get the active canonical dispatch plan (read-only: do not mutate)."""
        with self._lock:
            return self._current_plan

    def get_plan_dict(self) -> Optional[Dict[str, Any]]:
        """Get the active canonical dispatch plan as a JSON-serializable dictionary."""
        with self._lock:
            plan = self._current_plan
        return asdict(plan) if plan is not None else None

    def get_last_updated(self) -> Optional[datetime]:
        with self._lock:
            return self._last_updated

    def get_version(self) -> int:
        with self._lock:
            return self._plan_version

    def get_audit_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._publication_history)


# Convenient module-level access
def get_plan_store(persistence_path: Optional[Path] = None) -> PlanStore:
    return PlanStore.get_instance(persistence_path=persistence_path)
