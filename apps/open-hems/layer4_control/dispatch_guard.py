"""
Layer 4: Dispatch Guard (plan freshness & current-slot resolution)
==================================================================
The dispatcher must only execute a slot that actually covers "now" and only from a plan that
is recent. Otherwise it falls back to the Elephant baseline (SG2, normal) instead of replaying
a stale slot (e.g. a frozen plan during a DST transition or a failing planner).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

DEFAULT_MAX_PLAN_AGE_SECONDS = 15 * 60


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_current_slot(
    plan: Any,
    now: Optional[datetime] = None,
    max_plan_age_seconds: float = DEFAULT_MAX_PLAN_AGE_SECONDS,
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Returns (slot, None) for the slot whose [dt, dt+resolution) interval contains `now`, or
    (None, reason) when the plan is missing, stale, or has no slot covering now.
    All comparisons are done on absolute (UTC) instants.
    """
    now = now or datetime.now(timezone.utc)
    if plan is None or not getattr(plan, "slots", None):
        return None, "Geen actief plan"

    generated = _parse(getattr(plan, "generated_at", None))
    if generated is None:
        return None, "Plan zonder geldige generatietijd"
    age = (now - generated).total_seconds()
    if age > max_plan_age_seconds:
        return None, f"Plan is {int(age // 60)} min oud (max {int(max_plan_age_seconds // 60)} min)"

    step = timedelta(minutes=float(getattr(plan, "resolution_mins", 15) or 15))
    for slot in plan.slots:
        start = _parse(getattr(slot, "dt_iso", None))
        if start is not None and start <= now < start + step:
            return slot, None
    return None, "Geen planslot dekt het huidige tijdstip"


def count_run_minutes_from(plan: Any, slot: Any, force_modes: set) -> float:
    """Minutes of the contiguous forced-DHW run starting at `slot` (for commitment expiry)."""
    if plan is None or slot is None:
        return 0.0
    step = float(getattr(plan, "resolution_mins", 15) or 15)
    try:
        start_idx = plan.slots.index(slot)
    except ValueError:
        return 0.0
    n = 0
    for s in plan.slots[start_idx:]:
        mode = str(getattr(getattr(s, "mode_code", ""), "value", getattr(s, "mode_code", ""))).lower()
        if mode in force_modes:
            n += 1
        else:
            break
    return n * step
