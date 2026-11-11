"""
Dynamic Price Peak Detection & Chart Range Extraction
=====================================================
Layer 3 Business & Scheduling Logic:
  - Dynamic price peak detection on 15-minute resolution with winter comfort safeguards.
  - Spitsblok (forced_off) range extraction for chart overlays.
  - Active heating (dhw / space_heating) range extraction for chart overlays.
"""

import math
from datetime import timedelta
from typing import List, Dict, Any, Tuple, Optional, Set


def calc_percentile(data: List[float], p: float) -> float:
    """Calculates percentile from list of floats (pure python, deterministic)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return float(s[int(f)] * (c - k) + s[int(c)] * (k - f))


# In-memory deterministic cache keyed by price series signature and parameters.
# Since EPEX Day-Ahead prices are published once per day and remain static,
# this guarantees zero schedule drift across repeated planning calls.
_PEAK_CACHE: Dict[Tuple[Any, ...], Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]] = {}

DEFAULT_REF_MOD_POWER_KW = 0.75          # Reference modulated heat pump load (750 W) for whole-block saving evaluation
DEFAULT_MIN_LOCKOUT_SAVING_EUR = 0.05    # Minimum whole-block electricity saving (€) required to justify a hard SG1 lockout


def detect_dynamic_price_peaks(
    timeline_items: List[Dict[str, Any]],
    step_mins: int = 15,
    max_lockout_mins: int = 120,
    past_continuous_lockout_mins: int = 0,
    mins_since_last_lockout: int = 999,
    min_lockout_saving_eur: float = DEFAULT_MIN_LOCKOUT_SAVING_EUR,
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """
    Verfijnde Dynamische Spitsdetector op kwartierbasis met Winter Comfort Safeguard:
      1. Micro-piek filter: Negeert rimpels korter dan 30 min (filtert pendelstops weg).
      2. Piek-Kam Prominentie: Een continue harde blokkade wordt gecapt op maximaal 150 min (2,5 uur)
         op de absolute top van de prijsgolf om afkoeling van de vloer/woning in de winter te voorkomen.
      3. Flank-degradatie: Schouder-uren buiten de 2,5u top-kam worden 'Economisch Blokadvies' (⚠️),
         waarin de warmtepomp op minimale modulatie (950W) mag doorpruttelen indien nodig.
      4. Strikte Spitsuren Afbakening: Alleen echte Ochtendspits (06:00-10:00) en Avondspits (17:00-22:00)
         mogen een harde blokkade vormen. Nachtelijke uren (22:00-06:00) worden nooit hard geblokkeerd.
      5. Historie- en Dwell-bewust: Houdt rekening met reeds verstreken blokkadeduren en dwingt minimaal
         120 min hersteltijd af tussen twee opeenvolgende blokkades.
    """
    if not timeline_items:
        return [], {}

    # Check cache when slot 0 is not in an in-flight lockout transition
    can_cache = (past_continuous_lockout_mins == 0 and mins_since_last_lockout >= 120)
    cache_key = None
    if can_cache:
        import copy
        dt0 = timeline_items[0].get("dt")
        dt0_str = dt0.isoformat() if (dt0 is not None and hasattr(dt0, "isoformat")) else str(dt0)
        cache_key = (
            dt0_str,
            tuple(round(float(it.get("price", 0.0)), 4) for it in timeline_items),
            step_mins,
            max_lockout_mins
        )
        if cache_key in _PEAK_CACHE:
            cached_peaks, cached_map = _PEAK_CACHE[cache_key]
            return copy.deepcopy(cached_peaks), copy.deepcopy(cached_map)

    prices = [float(it.get("price", 0.0)) for it in timeline_items]
    p_med = calc_percentile(prices, 50)
    p75 = calc_percentile(prices, 75)
    p85 = calc_percentile(prices, 85)

    # 1. Kandidaat slots: moet significant boven mediaan liggen en in hoogste kwartiel
    is_cand = []
    for it in timeline_items:
        p = float(it.get("price", 0.0))
        cand = (p >= p75) and ((p - p_med) >= 0.035)
        is_cand.append(cand)

    # 2. Overbrug 1-slot dipjes binnen een bredere piek
    n = len(is_cand)
    bridged = list(is_cand)
    p70 = calc_percentile(prices, 70)
    for i in range(1, n - 1):
        if not bridged[i] and bridged[i-1] and bridged[i+1]:
            if float(timeline_items[i].get("price", 0.0)) >= p70:
                bridged[i] = True

    # 3. Cluster aaneengesloten pieken
    raw_events = []
    in_event = False
    start_idx = 0
    for i in range(n):
        if bridged[i] and not in_event:
            in_event = True
            start_idx = i
        elif not bridged[i] and in_event:
            in_event = False
            raw_events.append((start_idx, i - 1))
    if in_event:
        raw_events.append((start_idx, n - 1))

    # 3b. Macro-clustering: overbrug korte rimpels/gaten (gap <= 4 slots / 60 min) binnen hetzelfde spitsvenster
    # Voorkomt gefragmenteerde "uit / aan / uit" cycli en garandeert één coherente spitsblokkade per dagdeel.
    events = []
    for ev in raw_events:
        if not events:
            events.append(ev)
        else:
            prev_start, prev_end = events[-1]
            cur_start, cur_end = ev
            gap = cur_start - prev_end - 1
            h_prev = timeline_items[prev_start]["dt"].hour
            h_cur = timeline_items[cur_start]["dt"].hour
            same_window = (
                ((6 <= h_prev < 11) and (6 <= h_cur < 11)) or
                ((16 <= h_prev < 22) and (16 <= h_cur < 22))
            )
            if gap <= 4 and same_window:
                events[-1] = (prev_start, cur_end)
            else:
                events.append(ev)

    # 4. Formuleer Peak Events met Duur-Cap en Crest Focus
    peak_objects = []
    slot_lockout_map = {}
    last_hard_end_slot = -999
    if past_continuous_lockout_mins > 0:
        last_hard_end_slot = -1
    elif 0 < mins_since_last_lockout < 120:
        last_hard_end_slot = -int(mins_since_last_lockout / step_mins)

    for s_idx, e_idx in events:
        cluster_len = e_idx - s_idx + 1
        dur_mins = cluster_len * step_mins

        # Micro-peak filter: negeer pieken korter dan 30 min (2 kwartieren)
        if dur_mins < 30:
            continue

        cluster_prices = [float(timeline_items[k].get("price", 0.0)) for k in range(s_idx, e_idx + 1)]
        max_p = max(cluster_prices)
        avg_p = sum(cluster_prices) / cluster_len
        dt_start = timeline_items[s_idx]["dt"]
        dt_end = timeline_items[e_idx]["dt"] + timedelta(minutes=step_mins)

        # Check of het cluster (of de piek daarbinnen) in een spitsvenster valt:
        # Ochtendspits: 06:00 - 11:00
        # Avondspits: 16:00 - 22:00 (vroege flank kan al om 16:30/16:45 beginnen)
        cluster_hours = {timeline_items[k]["dt"].hour for k in range(s_idx, e_idx + 1)}
        peak_k = s_idx + cluster_prices.index(max_p)
        peak_h = timeline_items[peak_k]["dt"].hour

        is_ochtend = (6 <= peak_h < 11) or any(6 <= ch < 11 for ch in cluster_hours)
        is_avond = (16 <= peak_h < 22) or any(16 <= ch < 22 for ch in cluster_hours)
        is_spits_window = is_ochtend or is_avond

        if (16 <= peak_h < 22) or is_avond:
            name = "Avondspits"
        elif (6 <= peak_h < 11) or is_ochtend:
            name = "Ochtendspits"
        elif 11 <= peak_h < 16:
            name = "Middagpiek"
        else:
            name = "Nachttarief"

        # Bepaal of deze piek een harde blokkade rechtvaardigt
        is_hard_cluster = (max_p >= p85) and ((max_p - p_med) >= 0.050) and is_spits_window

        # Dwell time safeguard: als de vorige blokkade korter dan 120 minuten geleden eindigde,
        # mag er niet direct opnieuw een harde blokkade starten (afkoelbeveiliging)
        if s_idx == 0 and 0 < mins_since_last_lockout < 120 and past_continuous_lockout_mins == 0:
            is_hard_cluster = False

        # Cumulatieve duur-cap met verleden: als dit cluster aansluit op een al lopende blokkade
        is_in_flight_continuation = (s_idx == 0 and past_continuous_lockout_mins > 0)
        effective_max_mins = max_lockout_mins
        if is_in_flight_continuation:
            effective_max_mins = max(0, max_lockout_mins - past_continuous_lockout_mins)
            if effective_max_mins < 15:  # minder dan 1 kwartier resterend = direct opheffen
                is_hard_cluster = False

        max_slots_cap = (
            max(0, (effective_max_mins + step_mins - 1) // step_mins)
            if is_in_flight_continuation
            else max(0, effective_max_mins // step_mins)
        )

        # Vind de top-kam binnen het cluster (bij een al lopende blokkade op slot 0 blijft de kam verankerd op slot 0)
        if is_hard_cluster and max_slots_cap > 0 and cluster_len > max_slots_cap:
            if is_in_flight_continuation:
                hard_start_idx = 0
                hard_end_idx = min(e_idx, max_slots_cap - 1)
            else:
                best_sub_start = s_idx
                best_sub_avg = -1.0
                for w_start in range(s_idx, e_idx - max_slots_cap + 2):
                    w_end = w_start + max_slots_cap
                    sub_avg = sum(float(timeline_items[k].get("price", 0.0)) for k in range(w_start, w_end)) / max_slots_cap
                    if sub_avg > best_sub_avg:
                        best_sub_avg = sub_avg
                        best_sub_start = w_start
                hard_start_idx = best_sub_start
                hard_end_idx = best_sub_start + max_slots_cap - 1
        else:
            hard_start_idx = s_idx if (is_hard_cluster and max_slots_cap > 0) else -1
            hard_end_idx = e_idx if (is_hard_cluster and max_slots_cap > 0) else -1

        # Inter-event dwell time safeguard: dwing minimaal 120 min hersteltijd af tussen harde blokkades
        # Whole-block economic saving evaluation: only interrupt a running modulated heat pump
        # (HARD_LOCKOUT / SG1) when the entire crest block saves at least min_lockout_saving_eur.
        if is_hard_cluster and hard_start_idx >= 0:
            crest_prices = [float(timeline_items[k].get("price", 0.0)) for k in range(hard_start_idx, hard_end_idx + 1)]
            crest_avg_p = sum(crest_prices) / len(crest_prices) if crest_prices else avg_p
            h_dur_hours = ((hard_end_idx - hard_start_idx + 1) * step_mins) / 60.0
            expected_saving_eur = round(max(0.0, crest_avg_p - p_med) * DEFAULT_REF_MOD_POWER_KW * h_dur_hours, 4)
            if expected_saving_eur < min_lockout_saving_eur and not (is_in_flight_continuation and hard_start_idx == 0):
                is_hard_cluster = False
                hard_start_idx = -1
                hard_end_idx = -1
        else:
            expected_saving_eur = round(max(0.0, avg_p - p_med) * DEFAULT_REF_MOD_POWER_KW * (dur_mins / 60.0), 4)

        # Controleer 2 uur hersteltijd tussen harde blokkades
        # (een al lopende blokkade op slot 0 mag nooit zichzelf als een tweede blokkade annuleren)
        if is_hard_cluster and hard_start_idx >= 0:
            if is_in_flight_continuation and hard_start_idx == 0:
                last_hard_end_slot = hard_end_idx
            elif (hard_start_idx - last_hard_end_slot) * step_mins < 120:
                is_hard_cluster = False
                hard_start_idx = -1
                hard_end_idx = -1
            else:
                last_hard_end_slot = hard_end_idx

        h_start_lbl = timeline_items[hard_start_idx]["dt"].strftime("%H:%M") if hard_start_idx >= 0 else None
        h_end_lbl = (timeline_items[hard_end_idx]["dt"] + timedelta(minutes=step_mins)).strftime("%H:%M") if hard_end_idx >= 0 else None
        h_dur_mins = (hard_end_idx - hard_start_idx + 1) * step_mins if hard_start_idx >= 0 else 0

        peak_obj = {
            "start_idx": s_idx,
            "end_idx": e_idx,
            "start_time": dt_start.strftime("%H:%M"),
            "end_time": dt_end.strftime("%H:%M"),
            "duration_mins": dur_mins,
            "slots_count": cluster_len,
            "name": name,
            "severity": "HARD_LOCKOUT" if (is_hard_cluster and hard_start_idx >= 0) else "SOFT_ADVICE",
            "severity_label": "Harde Spitsblokkade 🔒" if (is_hard_cluster and hard_start_idx >= 0) else "Economisch Blokadvies ⚠️",
            "is_hard_lockout": (is_hard_cluster and hard_start_idx >= 0),
            # Canonical crest window as slot indices (-1 = no hard window). Consumers that need
            # per-slot lockout truth must use these, never the cluster start_idx/end_idx.
            "hard_start_idx": hard_start_idx if (is_hard_cluster and hard_start_idx >= 0) else -1,
            "hard_end_idx": hard_end_idx if (is_hard_cluster and hard_start_idx >= 0) else -1,
            "hard_start_time": h_start_lbl,
            "hard_end_time": h_end_lbl,
            "hard_duration_mins": h_dur_mins,
            "max_price": round(max_p, 4),
            "avg_price": round(avg_p, 4),
            "delta_median": round(max_p - p_med, 4),
            "expected_saving_eur": expected_saving_eur,
        }
        peak_objects.append(peak_obj)

        for k in range(s_idx, e_idx + 1):
            is_hard = (hard_start_idx <= k <= hard_end_idx and hard_start_idx >= 0)
            slot_entry = dict(peak_obj)
            slot_entry["is_hard_lockout"] = is_hard
            slot_entry["severity"] = "HARD_LOCKOUT" if is_hard else "SOFT_ADVICE"
            slot_entry["severity_label"] = "Harde Spitsblokkade 🔒" if is_hard else "Economisch Blokadvies ⚠️"
            slot_entry["peak_obj"] = peak_obj
            slot_lockout_map[k] = slot_entry

    if can_cache and cache_key is not None:
        import copy
        _PEAK_CACHE[cache_key] = (copy.deepcopy(peak_objects), copy.deepcopy(slot_lockout_map))
        if len(_PEAK_CACHE) > 50:
            _PEAK_CACHE.pop(next(iter(_PEAK_CACHE)))

    return peak_objects, slot_lockout_map


def hard_lockout_slot_indices(dynamic_peaks: List[Any], n_slots: Optional[int] = None) -> Set[int]:
    """
    Resolves the set of hard-lockout slot indices from any supported peak representation:
      - per-slot dicts {"slot_idx": k, "is_hard_lockout": True}
      - peak objects from detect_dynamic_price_peaks (uses hard_start_idx..hard_end_idx)
      - objects exposing the same attributes
    """
    result: Set[int] = set()
    for pk in dynamic_peaks or []:
        get = pk.get if isinstance(pk, dict) else (lambda k, d=None, _pk=pk: getattr(_pk, k, d))
        if not get("is_hard_lockout", False):
            continue
        slot_idx = get("slot_idx", None)
        if slot_idx is not None:
            result.add(int(slot_idx))
            continue
        hs = get("hard_start_idx", None)
        he = get("hard_end_idx", None)
        if hs is not None and he is not None and int(hs) >= 0 and int(he) >= int(hs):
            result.update(range(int(hs), int(he) + 1))
    if n_slots is not None:
        result = {k for k in result if 0 <= k < n_slots}
    return result


def extract_plan_spitsblok_ranges(slots: List[Any], history_count: int = 0, is_15m: bool = True) -> List[Dict[str, Any]]:
    """
    Unified Single Source of Truth builder for chart spitsblok overlays.
    Extracts contiguous hard lockout windows (mode_code == 'forced_off') directly from canonical plan slots.
    Guarantees 100% mathematical and visual alignment across ALL charts.
    """
    ranges = []
    in_block = False
    start_idx = 0
    # Auto-detect if slots are already hourly (e.g. len <= 48) vs 15m quarters (> 48)
    needs_downsample = (not is_15m) and len(slots) > 48
    n = len(slots) // 4 if needs_downsample else len(slots)
    for i in range(n):
        if not needs_downsample:
            is_locked = (slots[i].mode_code == "forced_off") or getattr(slots[i], "is_lockout", False)
        else:
            is_locked = any(
                (slots[i * 4 + k].mode_code == "forced_off" or getattr(slots[i * 4 + k], "is_lockout", False))
                for k in range(4) if (i * 4 + k) < len(slots)
            )
        if is_locked and not in_block:
            in_block = True
            start_idx = i
        elif not is_locked and in_block:
            in_block = False
            s_lbl = slots[start_idx * 4 if needs_downsample else start_idx].time_label
            e_lbl = slots[(i - 1) * 4 if needs_downsample else (i - 1)].time_label
            ranges.append({
                "start_idx": history_count + start_idx,
                "end_idx": history_count + i - 1,
                "start_label": s_lbl,
                "end_label": e_lbl,
                "name": "SPITSBLOK"
            })
    if in_block:
        s_lbl = slots[start_idx * 4 if needs_downsample else start_idx].time_label
        e_lbl = slots[-1].time_label
        ranges.append({
            "start_idx": history_count + start_idx,
            "end_idx": history_count + n - 1,
            "start_label": s_lbl,
            "end_label": e_lbl,
            "name": "SPITSBLOK"
        })
    return ranges


def extract_plan_soft_advice_ranges(slots: List[Any], history_count: int = 0, is_15m: bool = True) -> List[Dict[str, Any]]:
    """
    Unified Single Source of Truth builder for chart soft advice (advised_off) overlays.
    Extracts contiguous shoulder windows (mode_code == 'advised_off') directly from canonical plan slots.
    """
    ranges = []
    in_block = False
    start_idx = 0
    # Auto-detect if slots are already hourly (e.g. len <= 48) vs 15m quarters (> 48)
    needs_downsample = (not is_15m) and len(slots) > 48
    n = len(slots) // 4 if needs_downsample else len(slots)
    for i in range(n):
        if not needs_downsample:
            is_soft = (slots[i].mode_code == "advised_off") or getattr(slots[i], "is_advised_off", False)
        else:
            is_soft = any(
                (slots[i * 4 + k].mode_code == "advised_off" or getattr(slots[i * 4 + k], "is_advised_off", False))
                for k in range(4) if (i * 4 + k) < len(slots)
            )
        if is_soft and not in_block:
            in_block = True
            start_idx = i
        elif not is_soft and in_block:
            in_block = False
            s_lbl = slots[start_idx * 4 if needs_downsample else start_idx].time_label
            e_lbl = slots[(i - 1) * 4 if needs_downsample else (i - 1)].time_label
            ranges.append({
                "start_idx": history_count + start_idx,
                "end_idx": history_count + i - 1,
                "start_label": s_lbl,
                "end_label": e_lbl,
                "name": "P75_ADVIES"
            })
    if in_block:
        s_lbl = slots[start_idx * 4 if needs_downsample else start_idx].time_label
        e_lbl = slots[-1].time_label
        ranges.append({
            "start_idx": history_count + start_idx,
            "end_idx": history_count + n - 1,
            "start_label": s_lbl,
            "end_label": e_lbl,
            "name": "P75_ADVIES"
        })
    return ranges


def extract_plan_heating_ranges(slots: List[Any], history_count: int = 0, is_15m: bool = True, domain: str = "both") -> List[Dict[str, Any]]:
    """
    Unified Single Source of Truth builder for chart active heating overlays.
    Extracts contiguous heating windows (dhw_kw > 0 or heating_kw > 0) directly from canonical plan slots.
    """
    ranges = []
    in_block = False
    start_idx = 0
    n = len(slots) if is_15m else len(slots) // 4
    for i in range(n):
        if is_15m:
            s = slots[i]
            if domain == "dhw":
                is_h = getattr(s, "dhw_kw", 0.0) > 0.05
            elif domain == "space_heating":
                is_h = getattr(s, "heating_kw", 0.0) > 0.05
            else:
                is_h = (getattr(s, "dhw_kw", 0.0) > 0.05) or (getattr(s, "heating_kw", 0.0) > 0.05)
        else:
            if domain == "dhw":
                is_h = any(getattr(slots[i * 4 + k], "dhw_kw", 0.0) > 0.05 for k in range(4) if (i * 4 + k) < len(slots))
            elif domain == "space_heating":
                is_h = any(getattr(slots[i * 4 + k], "heating_kw", 0.0) > 0.05 for k in range(4) if (i * 4 + k) < len(slots))
            else:
                is_h = any((getattr(slots[i * 4 + k], "dhw_kw", 0.0) > 0.05 or getattr(slots[i * 4 + k], "heating_kw", 0.0) > 0.05) for k in range(4) if (i * 4 + k) < len(slots))

            # In 1-hour mode, enforce strict overlay non-overlap: Spitsblok (forced_off) takes priority over heating
            is_locked_hour = any(
                (slots[i * 4 + k].mode_code == "forced_off" or getattr(slots[i * 4 + k], "is_lockout", False))
                for k in range(4) if (i * 4 + k) < len(slots)
            )
            if is_locked_hour:
                is_h = False

        if is_h and not in_block:
            in_block = True
            start_idx = i
        elif not is_h and in_block:
            in_block = False
            s_lbl = slots[start_idx * 4 if not is_15m else start_idx].time_label
            e_lbl = slots[(i - 1) * 4 if not is_15m else (i - 1)].time_label
            block_slots = slots[start_idx:i] if is_15m else [slots[idx_w] for idx_w in range(start_idx * 4, min(len(slots), i * 4))]
            is_openhems = any(
                str(getattr(s_item, "mode_code", "")).lower() in [
                    "forced_on", "max_on", "advised_on",
                    "forced_standard_50", "forced_night_50", "forced_solar_boost_60",
                    "standardizedstate.forced_on", "standardizedstate.max_on", "standardizedstate.advised_on"
                ]
                or getattr(s_item, "is_orchestrated", False)
                for s_item in block_slots
            )
            ranges.append({
                "start_idx": history_count + start_idx,
                "end_idx": history_count + i - 1,
                "start_label": s_lbl,
                "end_label": e_lbl,
                "name": "VERWARMT",
                "initiator": "openhems" if is_openhems else "heatpump",
                "is_autonomous": not is_openhems
            })
    if in_block:
        s_lbl = slots[start_idx * 4 if not is_15m else start_idx].time_label
        e_lbl = slots[-1].time_label
        block_slots = slots[start_idx:n] if is_15m else [slots[idx_w] for idx_w in range(start_idx * 4, len(slots))]
        is_openhems = any(
            str(getattr(s_item, "mode_code", "")).lower() in [
                "forced_on", "max_on", "advised_on",
                "forced_standard_50", "forced_night_50", "forced_solar_boost_60",
                "standardizedstate.forced_on", "standardizedstate.max_on", "standardizedstate.advised_on"
            ]
            or getattr(s_item, "is_orchestrated", False)
            for s_item in block_slots
        )
        ranges.append({
            "start_idx": history_count + start_idx,
            "end_idx": history_count + n - 1,
            "start_label": s_lbl,
            "end_label": e_lbl,
            "name": "VERWARMT",
            "initiator": "openhems" if is_openhems else "heatpump",
            "is_autonomous": not is_openhems
        })
    return ranges
