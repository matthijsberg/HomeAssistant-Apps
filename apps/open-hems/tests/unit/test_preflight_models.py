from datetime import datetime, timezone
from layer4_control.preflight.models import GatekeeperDecision, LockoutHorizon, SubsystemLiveState


def test_gatekeeper_decision_creation():
    d = GatekeeperDecision(
        action="DEFER",
        reason="Spitsblok start over 15 minuten",
        target_mode="normal",
        metrics={"minutes_to_lockout": 15.0}
    )
    assert d.action == "DEFER"
    assert d.is_deferred is True
    assert d.is_start is False
    assert d.metrics["minutes_to_lockout"] == 15.0


def test_lockout_horizon_helper():
    now = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)
    lockout_start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    lockout_end = datetime(2026, 11, 2, 19, 30, tzinfo=timezone.utc)

    horizon = LockoutHorizon(
        evaluated_at=now,
        next_lockout_start=lockout_start,
        next_lockout_end=lockout_end
    )
    assert horizon.minutes_until_lockout == 30.0
    assert horizon.lockout_duration_hours == 2.5
