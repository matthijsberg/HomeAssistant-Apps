"""
Layer 2: Floor (Screed) State Estimator
=======================================
Turns the underfloor-heating manifold loop temperatures into an estimate of the screed temperature:
the thermal storage state that SpaceHeatingPolicy starts its simulation from.

Measured behaviour (winter 2025-26 and 2026-09-28..10-12, knowledge/architecture/floor-state-estimation.md):
- The manifold has its own circulation pump that always runs. Without heat-pump supply the loop water
  equilibrates with the screed: all loop sensors agree within ~0.1 K and read the screed temperature.
- After CV heat stops, the supply water fades out in ~30-40 min (2-3.5 K/h at first); after that the
  reading is floor-dominated (winter: 0.45-0.6 K/h cooling right after a run).
- While the heat pump delivers CV heat, the loops carry supply-dominated water that sits roughly
  R_w x Q_th above the screed (R_w median 0.18 K/kW over 114 winter stops).

Estimation rules, evaluated once per planning tick (pure and deterministic; the caller keeps `previous`):
- settled:    no CV heat for >= settle_minutes -> the reading IS the screed temperature (Quality.GOOD).
- corrected:  CV heat flowing -> smooth towards reading - R_w * Q_th. The screed does not cool while heat
              flows in and is never warmer than the water passing through it (Quality.ESTIMATED).
- held:       transitional (settle window, DHW run, unknown state) -> previous estimate capped at the
              reading, for at most max_hold_minutes after the last settled/corrected anchor (INTERPOLATED).
              Without CV heat the held value relaxes towards the room temperature (winter: ~0.5 K/h).
- tracking:   hold expired -> slow smoothing towards the best available reading (Quality.STALE).
- cold_start: no usable previous estimate -> best available reading (Quality.STALE).
Without any valid reading the previous estimate is held within max_hold_minutes; otherwise None.
Nothing is invented: every value derives from a manifold reading and carries its provenance.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Sequence

from models.canonical import Quality


@dataclass(frozen=True)
class FloorEstimatorParams:
    settle_minutes: float = 60.0            # supply water faded out; reading is floor-dominated (winter: 30-40 min + margin)
    water_offset_k_per_kw: float = 0.18     # R_w: water-above-screed offset per kW_th (winter median, 114 stops)
    heat_flow_threshold_kw: float = 1.0     # "heat flowing" when the compressor state is unknown
    tracking_tau_minutes: float = 15.0      # smoothing of the noisy corrected reading while heating
    stale_tau_minutes: float = 60.0         # slower smoothing once the hold has expired
    hold_cooling_tau_minutes: float = 360.0  # pipe-level screed relaxing towards the room after a run (winter)
    max_hold_minutes: float = 180.0         # longest bridge after the last settled/corrected anchor
    cold_start_gap_minutes: float = 360.0   # a previous estimate older than this is discarded
    min_plausible_c: float = 10.0
    max_plausible_c: float = 45.0


@dataclass(frozen=True)
class FloorCircuitObservation:
    """Entity-free snapshot of the floor heating circuit. None means: not measured (never invented)."""
    timestamp: datetime
    manifold_temps_c: Sequence[Optional[float]]
    compressor_on: Optional[bool]
    dhw_active: bool
    minutes_since_state_change: Optional[float]  # since the compressor or DHW state last changed
    heat_output_kw: Optional[float]              # measured thermal output of the heat pump
    room_temp_c: Optional[float] = None          # the room reference the heat pump controls on (Madoka)


@dataclass(frozen=True)
class FloorStateEstimate:
    temp_c: float
    source: str                    # settled | corrected | held | tracking | cold_start
    quality: Quality
    updated_at: datetime
    anchored_at: Optional[datetime]  # last settled/corrected measurement; bounds how long we may hold
    manifold_reading_c: Optional[float]


def manifold_reading_c(obs: FloorCircuitObservation, params: Optional[FloorEstimatorParams] = None) -> Optional[float]:
    """Mean of the plausible loop readings, or None when no loop sensor is usable."""
    p = params or FloorEstimatorParams()
    valid = [
        float(t) for t in obs.manifold_temps_c
        if t is not None and math.isfinite(t) and p.min_plausible_c <= t <= p.max_plausible_c
    ]
    return sum(valid) / len(valid) if valid else None


def _minutes_since(now: datetime, earlier: Optional[datetime]) -> float:
    if earlier is None:
        return math.inf
    return max(0.0, (now - earlier).total_seconds() / 60.0)


def estimate_floor_state(
    obs: FloorCircuitObservation,
    previous: Optional[FloorStateEstimate] = None,
    params: Optional[FloorEstimatorParams] = None,
) -> Optional[FloorStateEstimate]:
    """Estimates the screed temperature from one observation and the previous estimate (see module doc)."""
    p = params or FloorEstimatorParams()
    now = obs.timestamp
    reading = manifold_reading_c(obs, p)
    q_kw = obs.heat_output_kw
    heat_flowing = q_kw is not None and q_kw >= p.heat_flow_threshold_kw

    # CV heat flows when the compressor runs and the 3-way valve is not on the tank. The measured heat output
    # only decides when the compressor state is unknown: the P1P2 value can stay frozen at its last reading
    # after the compressor stops (winter 2025-26: non-zero in 89 % of idle minutes).
    if obs.compressor_on is not None:
        cv_active: Optional[bool] = bool(obs.compressor_on and not obs.dhw_active)
    elif q_kw is not None:
        cv_active = bool(heat_flowing and not obs.dhw_active)
    else:
        cv_active = None

    prev = previous
    if prev is not None and _minutes_since(now, prev.updated_at) > p.cold_start_gap_minutes:
        prev = None
    hold_valid = prev is not None and _minutes_since(now, prev.anchored_at) <= p.max_hold_minutes

    if reading is None:
        if prev is not None and hold_valid:
            return replace(prev, source="held", quality=Quality.INTERPOLATED, updated_at=now, manifold_reading_c=None)
        return None

    # During a DHW run the measured heat goes to the tank, so the loops settle on the screed as well
    settled = (
        cv_active is not None and not cv_active
        and obs.minutes_since_state_change is not None
        and obs.minutes_since_state_change >= p.settle_minutes
    )
    if settled:
        return FloorStateEstimate(reading, "settled", Quality.GOOD, now, now, reading)

    q_cv = max(0.0, q_kw) if (cv_active and q_kw is not None) else 0.0
    target = reading - p.water_offset_k_per_kw * q_cv
    if prev is None:
        return FloorStateEstimate(target, "cold_start", Quality.STALE, now, None, reading)

    elapsed = _minutes_since(now, prev.updated_at)
    if cv_active and q_kw is not None:
        alpha = 1.0 - math.exp(-elapsed / p.tracking_tau_minutes)
        value = prev.temp_c + alpha * (target - prev.temp_c)
        value = max(value, min(prev.temp_c, reading))  # the screed does not cool while CV heat flows in
        return FloorStateEstimate(min(value, reading), "corrected", Quality.ESTIMATED, now, now, reading)

    if hold_valid:
        held = prev.temp_c
        if cv_active is not None and not cv_active and obs.room_temp_c is not None and held > obs.room_temp_c:
            # No CV heat: the screed near the pipes keeps cooling towards the room while we wait for settling
            held = obs.room_temp_c + (held - obs.room_temp_c) * math.exp(-elapsed / p.hold_cooling_tau_minutes)
        return FloorStateEstimate(min(held, reading), "held", Quality.INTERPOLATED, now, prev.anchored_at, reading)

    alpha = 1.0 - math.exp(-elapsed / p.stale_tau_minutes)
    value = prev.temp_c + alpha * (target - prev.temp_c)
    return FloorStateEstimate(min(value, reading), "tracking", Quality.STALE, now, prev.anchored_at, reading)
