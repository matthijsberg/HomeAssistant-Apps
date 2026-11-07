"""
Open HEMS — Daikin-first DHW Policy Plan Adapter (ADR-006)
==========================================================
Layer 3 Scheduling Adapter: turns a DhwPolicyResult into the authoritative DHWPlanSummary.
Keeps the decision_details keys that the API and UI read (status, badge_html, box_title, explanation,
trajectory, unheated_trajectory, comfort_boundary_c, morning_dip_c/time, dynamic_peaks), so presentation
stays a dumb view (invariant 1). No math beyond formatting the policy's own numbers.
"""

from typing import Any, Dict, List, Optional, Set

from models.canonical import DHWPlanSummary, StandardizedState, get_state_metadata
from layer3_scheduling.dhw_policy import DhwPolicyParams, DhwPolicyResult, MODE_MAX_ON
from layer3_scheduling.dhw_specs import DhwTankSpec

PLANNER_NAME = "daikin_first"
SLOTS_24H = 96

_BADGE = (
    '<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold '
    '{bg} {fg} border {border}"><span class="w-1.5 h-1.5 rounded-full {dot}"></span> {text}</span>'
)


def _label(slots: List[Any], idx: int) -> str:
    if 0 <= idx < len(slots):
        return str(getattr(slots[idx], "label", f"slot {idx}"))
    return "later"


def policy_result_to_summary(
    res: DhwPolicyResult,
    slots: List[Any],
    t0_c: float,
    spec: Optional[DhwTankSpec] = None,
    dynamic_peaks: Optional[List[Any]] = None,
    params: Optional[DhwPolicyParams] = None,
    hard_slots: Optional[Set[int]] = None,
) -> DHWPlanSummary:
    spec = spec or DhwTankSpec()
    params = params or DhwPolicyParams()
    peaks = list(dynamic_peaks or [])
    runs_24h = [r for r in res.runs if r.start_idx < SLOTS_24H]

    if runs_24h:
        first = runs_24h[0]
        planned_mode = "max_on" if first.target_temp_c > spec.target_setpoint_c else "forced_on"
        target_c = first.target_temp_c
        run_start = _label(slots, first.start_idx)
        run_end = _label(slots, min(len(slots) - 1, first.end_idx))
        run_minutes = (first.end_idx - first.start_idx) * 15
        run_kw = [res.slot_dhw_kw[k] for k in range(first.start_idx, min(first.end_idx, len(res.slot_dhw_kw)))]
        power_kw = round(max(run_kw), 2) if run_kw else 0.0
    else:
        planned_mode, target_c = "normal", spec.target_setpoint_c
        run_start = run_end = "Geen run"
        run_minutes, power_kw = 0, 0.0

    state = {"normal": StandardizedState.NORMAL, "forced_on": StandardizedState.FORCED_ON,
             "max_on": StandardizedState.MAX_ON}[planned_mode]
    meta = get_state_metadata(state)

    # Status and badge
    active_now = bool(res.slot_modes) and res.slot_modes[0] in ("forced_on", MODE_MAX_ON)
    if active_now:
        status = "ACTIVE_RUN"
        badge = _BADGE.format(bg="bg-amber-950/80", fg="text-amber-300", border="border-amber-800/80",
                              dot="bg-amber-400 animate-pulse", text=f"⚡ Actief verwarmen tot {target_c:.0f}°C")
    elif runs_24h:
        status = "SCHEDULED"
        badge = _BADGE.format(bg="bg-teal-950/80", fg="text-teal-300", border="border-teal-800/80", dot="bg-teal-400",
                              text=f"Gepland: {run_start}–{run_end} tot {target_c:.0f}°C")
    else:
        status = "STANDBY"
        badge = _BADGE.format(bg="bg-slate-900", fg="text-slate-300", border="border-slate-700", dot="bg-slate-400",
                              text="Daikin regelt zelf (geen ingreep)")

    # Lowest temperature without intervention in the next 24 h ("dip")
    auto_24h = res.autonomous_trajectory[: SLOTS_24H + 1]
    dip_idx = min(range(len(auto_24h)), key=lambda i: auto_24h[i]) if auto_24h else 0
    dip_c = round(auto_24h[dip_idx], 1) if auto_24h else round(t0_c, 1)
    dip_time = _label(slots, max(0, dip_idx - 1)) if dip_idx > 0 else _label(slots, 0)

    first_auto = res.first_autonomous_start_idx
    stop_temp_val = spec.target_setpoint_c if (spec and spec.target_setpoint_c is not None) else 50.0
    stop_temp_label = f"{stop_temp_val:.0f} °C"
    if first_auto is not None:
        counterfactual = f"Zonder ingreep warmt de Daikin zelf op rond {_label(slots, first_auto)} (start bij 40 °C, stopt bij {stop_temp_label})."
    else:
        counterfactual = "Zonder ingreep blijft het vat binnen de horizon boven 40 °C; de Daikin hoeft niet te stoken."

    run_explanations = [f"{_label(slots, r.start_idx)}–{_label(slots, min(len(slots) - 1, r.end_idx))}: {r.reason}"
                        for r in runs_24h]
    comfort_text = (f"Vat nu {t0_c:.1f} °C. Laagste temperatuur zonder ingreep komende 24 uur: {dip_c:.1f} °C "
                    f"rond {dip_time}. {counterfactual}")
    finance_text = (f"Geplande runs kosten €{res.total_cost_eur:.2f} ({res.total_kwh_el:.1f} kWh). "
                    f"Besparing t.o.v. alleen de Daikin: €{res.saving_eur:.2f} (gecorrigeerd voor de warmte die in het vat achterblijft).")
    n_hard = len(hard_slots or set())

    details: Dict[str, Any] = {
        "status": status,
        "planner": PLANNER_NAME,
        "planned_mode": planned_mode,
        "box_title": "Daikin-first tapwatersturing",
        "badge_html": badge,
        "comfort_card_title": "1️⃣ Comfort: wanneer stookt de Daikin zelf?",
        "comfort_text": comfort_text,
        "finance_card_title": "2️⃣ Warmteprijs: nu of later stoken?",
        "finance_text": finance_text,
        "bullet_1": run_explanations[0] if run_explanations else "Geen ingreep: de Daikin regelt zelf",
        "bullet_2": run_explanations[1] if len(run_explanations) > 1 else counterfactual,
        "run_explanations": run_explanations,
        "explanation": res.explanation,
        "morning_dip_c": dip_c,
        "morning_dip_time": dip_time,
        "dynamic_peaks": peaks,
        "savings_eur": res.saving_eur,
        "cost_total_eur": res.total_cost_eur,
        "electricity_cost_eur": res.total_cost_eur,
        "autonomous_cost_eur": res.autonomous_cost_eur,
        "target_setpoint_c": spec.target_setpoint_c if spec else 50.0,
        "comfort_boundary_c": round(spec.target_setpoint_c - spec.auto_start_delta_c + params.preheat_margin_c, 1),
        "trajectory": res.trajectory,
        "unheated_trajectory": {"temperatures_c": res.autonomous_trajectory},
        "slot_reasons": res.slot_reasons,
        "validation_issue": None,
    }

    unheated = [{"slot_idx": k, "label": _label(slots, k), "temperature_c": res.autonomous_trajectory[k]}
                for k in range(min(len(slots), len(res.autonomous_trajectory)))]

    return DHWPlanSummary(
        planned_mode=planned_mode,
        planned_mode_label=meta.get("label", "Normaal bedrijf") if runs_24h else "Normaal — Daikin regelt zelf",
        color_hex=meta.get("color_hex", "#94A3B8"),
        tailwind_class=meta.get("tailwind_text", "text-slate-400"),
        target_temp_c=target_c,
        run_start=run_start,
        run_end=run_end,
        run_duration_min=run_minutes,
        power_kw=power_kw,
        total_stroom_kwh=round(sum(r.kwh_el for r in res.runs), 2),
        spits_lockout_hours=round(n_hard * 0.25, 2),
        dynamic_peaks=peaks,
        unheated_trajectory=unheated,
        counterfactual_reason=counterfactual,
        arbitrage_saving_eur=res.saving_eur,
        decision_details=details,
    )
