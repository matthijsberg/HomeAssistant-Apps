from datetime import datetime, timezone, timedelta
from layer4_control.preflight.coordinator import PreflightCoordinator, extract_lockout_horizon
from layer4_control.preflight.models import SubsystemLiveState
from unittest.mock import MagicMock
from models.canonical import StandardizedState, DispatchPlanSlot, CanonicalDispatchPlan


def _make_slot(idx: int, dt: datetime, mode: StandardizedState) -> DispatchPlanSlot:
    return DispatchPlanSlot(
        slot_idx=idx,
        time_label=dt.strftime("%H:%M"),
        dt_iso=dt.isoformat(),
        price_eur=0.25,
        solar_kw=0.0,
        unallocated_kw=0.3,
        heating_kw=0.0,
        dhw_kw=0.0,
        net_import_kw=0.3,
        mode_code=mode,
        mode_label=mode.value
    )


def test_extract_lockout_horizon_from_slots():
    now = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)
    slots = [
        _make_slot(0, now, StandardizedState.NORMAL),
        _make_slot(1, now + timedelta(minutes=15), StandardizedState.NORMAL),
        _make_slot(2, now + timedelta(minutes=30), StandardizedState.FORCED_OFF),
        _make_slot(3, now + timedelta(minutes=45), StandardizedState.FORCED_OFF),
    ]
    plan = CanonicalDispatchPlan(
        generated_at=now.isoformat(),
        horizon_hours=24.0,
        resolution_mins=15,
        is_fresh=True,
        freshness_age_seconds=0.0,
        slots=slots,
        dhw_summary=MagicMock(),
        dynamic_peaks=[]
    )

    horizon = extract_lockout_horizon(plan, now=now)
    assert horizon.minutes_until_lockout == 30.0
    assert horizon.lockout_duration_hours == 0.5


def test_coordinator_orchestrates_all_subsystems():
    coord = PreflightCoordinator()
    state = SubsystemLiveState(dhw_temp_c=48.0, outdoor_temp_c=10.0)
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    slots = [
        _make_slot(0, now, StandardizedState.NORMAL)
    ]
    plan = CanonicalDispatchPlan(
        generated_at=now.isoformat(),
        horizon_hours=24.0,
        resolution_mins=15,
        is_fresh=True,
        freshness_age_seconds=0.0,
        slots=slots,
        dhw_summary=MagicMock(),
        dynamic_peaks=[]
    )

    summary = coord.evaluate_all(state, plan, now=now)
    assert "dhw" in summary
    assert "heating" in summary
    assert "battery" in summary
    assert summary["dhw"].action in ("IDLE", "NORMAL")
