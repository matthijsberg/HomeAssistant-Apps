"""
Layer 3: Opportunistic In-Flight DHW Run Merger & 50°C vs 60°C Trade-Off Engine
=============================================================================
Detects when the heat pump starts heating domestic hot water autonomously
(e.g. after a family shower) and decides whether to merge an upcoming
thermal storage / solar boost run into the active run or stop at standard comfort.
"""

from typing import Optional, List, Any
from dataclasses import dataclass
from models.canonical import CanonicalDispatchPlan
from layer3_scheduling.dhw_specs import DhwTankSpec
from layer3_scheduling.dhw_financials import calculate_slot_financials


@dataclass
class OpportunisticMergeResult:
    should_merge: bool
    promoted_mode: str
    target_temp_c: float
    reason: str
    decision_explanation: str
    original_slot_idx: Optional[int]
    original_slot_time: Optional[str]
    savings_estimate_eur: float
    cancelled_slots: List[int]
    is_dhw_active: bool = False
    current_tank_temp_c: float = 50.0
    current_power_kw: float = 0.0
    active_target_temp_c: float = 50.0
    active_mode_label: str = "Normaal"


class OpportunisticDHWMerger:
    LOOKAHEAD_SLOTS_MAX = 24  # 6 hours lookahead (covers full daytime solar window)

    @classmethod
    def evaluate_merge(
        cls,
        plan: CanonicalDispatchPlan,
        is_dhw_actively_heating: bool,
        current_tank_temp_c: float,
        current_solar_kw: float,
        current_price_eur: float,
        is_hard_lockout_now: bool = False,
        current_power_kw: float = 0.0,
        lookahead_slots: Optional[int] = None,
        spec: Optional[DhwTankSpec] = None,
        tariff_provider: Optional[Any] = None,
        outdoor_temp_c: Optional[float] = None
    ) -> OpportunisticMergeResult:
        """
        Evaluates whether an active DHW heating run should be promoted to boost temperature (SG4)
        and merged with an upcoming planned run or kept at standard comfort (SG2).
        Uses exact thermodynamic energy and effective tariff comparison (avoided cold restart vs lift cost).
        """
        spec = spec or DhwTankSpec()
        t_set = float(spec.target_setpoint_c)
        t_boost = float(spec.boost_setpoint_c)

        if not is_dhw_actively_heating:
            return OpportunisticMergeResult(
                should_merge=False,
                promoted_mode="normal",
                target_temp_c=t_set,
                reason="Geen actieve tapwaterverwarming gedetecteerd",
                decision_explanation="Warmtepomp is niet actief voor tapwater (stand-by).",
                original_slot_idx=None,
                original_slot_time=None,
                savings_estimate_eur=0.0,
                cancelled_slots=[],
                is_dhw_active=False,
                current_tank_temp_c=current_tank_temp_c,
                current_power_kw=current_power_kw,
                active_target_temp_c=t_set,
                active_mode_label="Standby"
            )

        if is_hard_lockout_now:
            return OpportunisticMergeResult(
                should_merge=False,
                promoted_mode="forced_off",
                target_temp_c=t_set,
                reason="Harde spitsblokkade actief: doorverwarmen geblokkeerd",
                decision_explanation=f"Warmtepomp is actief ({current_power_kw:.2f} kW, {current_tank_temp_c:.1f}°C) maar een harde spitsblokkade is actief. Doorverwarmen naar {t_boost:.0f}°C is niet toegestaan tegen piektarieven.",
                original_slot_idx=None,
                original_slot_time=None,
                savings_estimate_eur=0.0,
                cancelled_slots=[],
                is_dhw_active=True,
                current_tank_temp_c=current_tank_temp_c,
                current_power_kw=current_power_kw,
                active_target_temp_c=t_set,
                active_mode_label="Spitsblokkade (SG1)"
            )

        if not plan or not plan.slots:
            return OpportunisticMergeResult(
                should_merge=False,
                promoted_mode="normal" if current_tank_temp_c >= (t_set - 0.2) else "forced_on",
                target_temp_c=t_set,
                reason="Geen actief dispatch plan beschikbaar",
                decision_explanation="Geen dispatch plan geladen.",
                original_slot_idx=None,
                original_slot_time=None,
                savings_estimate_eur=0.0,
                cancelled_slots=[],
                is_dhw_active=True,
                current_tank_temp_c=current_tank_temp_c,
                current_power_kw=current_power_kw,
                active_target_temp_c=t_set,
                active_mode_label=f"Standaard {t_set:.0f}°C"
            )

        active_lookahead = lookahead_slots if lookahead_slots is not None else cls.LOOKAHEAD_SLOTS_MAX
        tank_target_set_reached = (current_tank_temp_c >= (t_set - 0.2))

        # CASE 0: Active slot (slot 0) is ALREADY a boost thermal storage / solar boost run
        cur_s = plan.slots[0]
        cur_mode = str(getattr(cur_s, "mode_code", "")).lower()
        plan_summary = getattr(plan, "dhw_summary", None)
        cur_is_boost = (
            "max_on" in cur_mode
            or "solar_boost" in cur_mode
            or getattr(cur_s, "target_temp_c", t_set) >= (t_boost - 2.0)
            or (plan_summary and getattr(plan_summary, "target_temp_c", t_set) >= (t_boost - 2.0) and getattr(plan_summary, "run_start", "").startswith("Nu"))
        )

        if cur_is_boost:
            target_boost_reached = (current_tank_temp_c >= (t_boost - 0.3))
            mode_lbl = f"Doel {t_boost:.0f}°C bereikt — Automatisch (SG2)" if target_boost_reached else f"Doorwarmen naar {t_boost:.0f}°C (Zonnebuffer)"
            dec_expl = (
                f"Besluit: Doel {t_boost:.0f}°C bereikt ({current_tank_temp_c:.1f}°C) — Automatisch (SG2). Het boilervat is volledig doorgewarmd tot {t_boost:.0f}°C zonnebuffer. Smart Grid relais zijn vrijgegeven."
                if target_boost_reached else
                f"Besluit: Doorwarmen naar {t_boost:.0f}°C (Zonnebuffer). De warmtepomp is actief ({current_power_kw:.2f} kW, {current_tank_temp_c:.1f}°C) en verwarmt het vat conform plan door tot {t_boost:.0f}°C om zonnestroom te bufferen."
            )
            return OpportunisticMergeResult(
                should_merge=True,
                promoted_mode="normal" if target_boost_reached else "max_on",
                target_temp_c=t_boost,
                reason=f"Geplande {t_boost:.0f}°C zonnebuffer is actief",
                decision_explanation=dec_expl,
                original_slot_idx=0,
                original_slot_time="nu",
                savings_estimate_eur=0.20,
                cancelled_slots=[],
                is_dhw_active=True,
                current_tank_temp_c=current_tank_temp_c,
                current_power_kw=current_power_kw,
                active_target_temp_c=t_boost,
                active_mode_label=mode_lbl
            )

        # Scan upcoming slots within lookahead window
        candidate_slots_boost: List[int] = []
        candidate_slots_set: List[int] = []
        candidate_time_boost = None
        candidate_time_set = None

        lookahead_limit = min(len(plan.slots), active_lookahead + 1)
        for idx in range(1, lookahead_limit):
            s = plan.slots[idx]
            s_mode = str(getattr(s, "mode_code", "")).lower()
            s_target = getattr(s, "target_temp_c", t_set)
            if "max_on" in s_mode or "solar_boost" in s_mode or (s.dhw_kw > 1.0 and s_target >= (t_boost - 2.0)):
                candidate_slots_boost.append(idx)
                if candidate_time_boost is None:
                    candidate_time_boost = s.time_label
            elif "forced_on" in s_mode or "night_50" in s_mode or "standard_50" in s_mode or s.dhw_kw > 1.0:
                candidate_slots_set.append(idx)
                if candidate_time_set is None:
                    candidate_time_set = s.time_label

        # CASE A: A boost run (e.g. 60°C) is planned within the lookahead window
        if candidate_slots_boost:
            cand_idx = candidate_slots_boost[0]
            cand_s = plan.slots[cand_idx]

            # Thermodynamic energy lift: Q = C_vat * (T_boost - T_set)
            c_tank = float(spec.thermal_capacity_kwh_per_k)
            delta_t_boost = max(0.0, t_boost - t_set)
            q_lift_th = c_tank * delta_t_boost

            out_t = outdoor_temp_c
            if out_t is None:
                out_t = float(getattr(cur_s, "outdoor_temp_c", getattr(cur_s, "outdoor_temp", 10.0)))

            cop_nu = max(1.0, float(spec.get_cop(t_boost, outdoor_temp_c=out_t)))
            p_el = max(1.0, float(spec.get_electric_power_kw(t_boost, outdoor_temp_c=out_t)))
            kwh_lift_el = q_lift_th / cop_nu

            # Determine effective prices for current slot and candidate slot (accounting for PV surplus)
            _, _, _, p_eff_nu = calculate_slot_financials(
                solar_kw=current_solar_kw,
                unalloc_kw=float(getattr(cur_s, "unallocated_kw", 0.30)),
                el_demand_kw=p_el,
                price_all_in=current_price_eur,
                tariff_provider=tariff_provider
            )
            _, _, _, p_eff_later = calculate_slot_financials(
                solar_kw=float(getattr(cand_s, "solar_kw", 0.0)),
                unalloc_kw=float(getattr(cand_s, "unallocated_kw", 0.30)),
                el_demand_kw=p_el,
                price_all_in=float(getattr(cand_s, "price_eur", current_price_eur)),
                tariff_provider=tariff_provider
            )

            # Avoided cold start overhead (energy + compressor cycle start penalty) vs extra electricity costs for lift
            e_start_kwh = float(getattr(spec, "startup_overhead_kwh", 0.25))
            c_start_eur = float(getattr(spec, "c_start", 0.08))
            saved_restart_eur = (e_start_kwh * p_eff_later) + c_start_eur
            extra_lift_cost_eur = kwh_lift_el * (p_eff_nu - p_eff_later)
            net_benefit_eur = round(saved_restart_eur - extra_lift_cost_eur, 3)

            is_cost_efficient = (net_benefit_eur > 0.0)

            if is_cost_efficient:
                savings = max(0.05, net_benefit_eur)
                reason = (
                    f"Opportunistische Run-Fusie: Actieve tapwaterverwarming gedetecteerd (tank {current_tank_temp_c:.1f}°C). "
                    f"Geplande {t_boost:.0f}°C zonnebuffer van {candidate_time_boost} direct samengevoegd met de lopende run. "
                    f"Netto besparing: €{net_benefit_eur:.2f} (vermeden koude herstart weegt op tegen energiekosten)."
                )
                decision_expl = (
                    f"Besluit: Doorwarmen naar {t_boost:.0f}°C (Zonnebuffer Fusie). De warmtepomp is reeds op bedrijfstemperatuur ({current_power_kw:.2f} kW, {current_tank_temp_c:.1f}°C). "
                    f"Omdat er om {candidate_time_boost} een {t_boost:.0f}°C run gepland stond en fuseren netto voordeliger is (+€{net_benefit_eur:.2f}), "
                    f"wordt de cyclus direct in één keer doorgewarmd tot {t_boost:.0f}°C. De latere run van {candidate_time_boost} is geannuleerd."
                )
                return OpportunisticMergeResult(
                    should_merge=True,
                    promoted_mode="max_on",
                    target_temp_c=t_boost,
                    reason=reason,
                    decision_explanation=decision_expl,
                    original_slot_idx=cand_idx,
                    original_slot_time=candidate_time_boost,
                    savings_estimate_eur=savings,
                    cancelled_slots=candidate_slots_boost,
                    is_dhw_active=True,
                    current_tank_temp_c=current_tank_temp_c,
                    current_power_kw=current_power_kw,
                    active_target_temp_c=t_boost,
                    active_mode_label=f"Doorwarmen naar {t_boost:.0f}°C (Zonnebuffer Fusie)"
                )
            else:
                fallback_mode = "normal" if tank_target_set_reached else "forced_on"
                fallback_label = f"Doel {t_set:.0f}°C bereikt ({current_tank_temp_c:.1f}°C) — Automatisch (SG2)" if tank_target_set_reached else f"Opwarmen naar {t_set:.0f}°C (Basislading)"
                decision_expl = (
                    f"Besluit: {fallback_label}. Het vat is met {current_tank_temp_c:.1f}°C op doeltemperatuur. "
                    f"Doorwarmen naar {t_boost:.0f}°C wordt nu niet gedaan omdat de geplande zonnebuffer om {candidate_time_boost} aanzienlijk voordeliger is "
                    f"(effectief €{p_eff_later:.3f} vs €{p_eff_nu:.3f}/kWh, meerkosten nu: €{extra_lift_cost_eur:.2f} vs vermeden start €{saved_restart_eur:.2f}). "
                    f"Relais staan in SG2 (Automatisch)."
                ) if tank_target_set_reached else (
                    f"Besluit: Opwarmen naar {t_set:.0f}°C. De warmtepomp herstelt basiscomfort tot {t_set:.0f}°C. "
                    f"Doorwarmen naar {t_boost:.0f}°C wordt bewaard voor het zonnevenster van {candidate_time_boost} (effectief €{p_eff_later:.3f}/kWh)."
                )
                return OpportunisticMergeResult(
                    should_merge=False,
                    promoted_mode=fallback_mode,
                    target_temp_c=t_set,
                    reason=f"Geen fusie: Huidig effectief tarief te hoog (€{p_eff_nu:.3f} vs €{p_eff_later:.3f}/kWh, netto verlies €{-net_benefit_eur:.2f})",
                    decision_explanation=decision_expl,
                    original_slot_idx=cand_idx,
                    original_slot_time=candidate_time_boost,
                    savings_estimate_eur=0.0,
                    cancelled_slots=[],
                    is_dhw_active=True,
                    current_tank_temp_c=current_tank_temp_c,
                    current_power_kw=current_power_kw,
                    active_target_temp_c=t_set,
                    active_mode_label=fallback_label
                )

        # CASE B: Only a standard setpoint run is planned
        if candidate_slots_set:
            fallback_mode = "normal" if tank_target_set_reached else "forced_on"
            fallback_label = f"Doel {t_set:.0f}°C bereikt ({current_tank_temp_c:.1f}°C) — Automatisch (SG2)" if tank_target_set_reached else f"Opwarmen naar {t_set:.0f}°C (Basislading)"
            decision_expl = (
                f"Besluit: {fallback_label}. Het vat is met {current_tank_temp_c:.1f}°C reeds op de gewenste {t_set:.0f}°C. "
                f"De Smart Grid relais zijn vrijgegeven naar Automatisch (SG2), zodat de warmtepomp kan stoppen. De latere run van {candidate_time_set} is vervallen."
            ) if tank_target_set_reached else (
                f"Besluit: Opwarmen naar {t_set:.0f}°C. De warmtepomp is aangeslagen ({current_power_kw:.2f} kW, {current_tank_temp_c:.1f}°C) en maakt de basislading naar {t_set:.0f}°C af. De latere run van {candidate_time_set} is vervallen."
            )
            return OpportunisticMergeResult(
                should_merge=False,
                promoted_mode=fallback_mode,
                target_temp_c=t_set,
                reason=f"Lopende run vervangt geplande {t_set:.0f}°C basisrun",
                decision_explanation=decision_expl,
                original_slot_idx=candidate_slots_set[0],
                original_slot_time=candidate_time_set,
                savings_estimate_eur=0.10,
                cancelled_slots=candidate_slots_set,
                is_dhw_active=True,
                current_tank_temp_c=current_tank_temp_c,
                current_power_kw=current_power_kw,
                active_target_temp_c=t_set,
                active_mode_label=fallback_label
            )

        # CASE C: No upcoming run planned
        fallback_mode = "normal" if tank_target_set_reached else "forced_on"
        fallback_label = f"Doel {t_set:.0f}°C bereikt ({current_tank_temp_c:.1f}°C) — Automatisch (SG2)" if tank_target_set_reached else f"Opwarmen naar {t_set:.0f}°C (Autonoom)"
        decision_expl = (
            f"Besluit: {fallback_label}. Het vat is met {current_tank_temp_c:.1f}°C reeds op gewenste temperatuur (≥ {t_set:.0f}°C). "
            f"Er is geen {t_boost:.0f}°C zonnebuffer vereist. Relais vrijgegeven naar Automatisch (SG2 in rust)."
        ) if tank_target_set_reached else (
            f"Besluit: Opwarmen naar {t_set:.0f}°C (Autonoom). De warmtepomp herstelt het basiscomfort ({current_power_kw:.2f} kW, {current_tank_temp_c:.1f}°C)."
        )
        return OpportunisticMergeResult(
            should_merge=False,
            promoted_mode=fallback_mode,
            target_temp_c=t_set,
            reason=f"Geen {t_boost:.0f}°C zonnebuffer gepland binnen het venster ({active_lookahead // 4} uur)",
            decision_explanation=decision_expl,
            original_slot_idx=None,
            original_slot_time=None,
            savings_estimate_eur=0.0,
            cancelled_slots=[],
            is_dhw_active=True,
            current_tank_temp_c=current_tank_temp_c,
            current_power_kw=current_power_kw,
            active_target_temp_c=t_set,
            active_mode_label=fallback_label
        )
