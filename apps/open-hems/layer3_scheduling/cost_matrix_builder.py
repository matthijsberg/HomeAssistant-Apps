"""
Open HEMS: Canonical Cost-Matrix & Energy Waterfall Builder (Layer 3)
====================================================================
Builds the deterministic, sheet-grade 9-section cost matrix & waterfall
payload for the interactive UI Heatmap Table across 15m/1h and 24h/48h horizons.

INVARIANTS:
1. Zero Home Assistant entity strings, zero network I/O.
2. Evaluates Heat Cost Decision Matrix (Heating, DHW 48°C, DHW 60°C) against
   the shared solar pool after non-steerable house load (`zon_after_house_kwh`)
   because of the 3-way valve constraint (either Heating or DHW per slot).
3. Evaluates the 5-step Solar Waterfall and 2-sided Battery Waterfall
   (CH_PV, CH_GRID, HOLD, PARTIAL, ZOM, EXPORT) with terminal storage valuation.
"""

from typing import Any, Dict, List, Optional


def build_cost_matrix_payload(
    labels: List[str],
    prices: List[float],
    export_prices: List[float],
    solar_kw: List[float],
    unallocated_kw: List[float],
    boiler_kw: List[float],
    heating_kw: List[float],
    battery_charge_kw: List[float],
    battery_discharge_kw: List[float],
    step_h: float,
    plan: Any = None,
    bat_summary: Any = None,
    forced_off_indices: Optional[set] = None,
) -> Dict[str, Any]:
    """Builds the structured 9-section cost matrix & heatmap payload."""
    n = len(labels)
    if n == 0:
        return {"labels": [], "step_h": step_h, "rows": []}

    lockouts = forced_off_indices or set()
    plan_slots = list(plan.slots) if (plan is not None and getattr(plan, "slots", None)) else []
    heat_slots = (
        list(plan.heating_summary.slots)
        if (plan is not None and getattr(plan, "heating_summary", None) and getattr(plan.heating_summary, "slots", None))
        else []
    )
    dhw_details = (
        (getattr(plan.dhw_summary, "decision_details", None) or {})
        if (plan is not None and getattr(plan, "dhw_summary", None))
        else {}
    )
    dhw_traj = dhw_details.get("trajectory", {}) if isinstance(dhw_details, dict) else {}
    dhw_temps_raw = list(dhw_traj.get("temperatures_c", []))
    dhw_tap_raw = list(dhw_traj.get("demand_kwh_th", []))
    default_dhw_target = float(getattr(plan.dhw_summary, "target_temp_c", 48.0) or 48.0) if (plan and getattr(plan, "dhw_summary", None)) else 48.0
    is_15m = step_h <= 0.3

    # Extract per-slot outdoor temp, boiler temp, room temp, tap demand, and DHW target from canonical plan
    outdoor_temps: List[float] = []
    boiler_temps: List[float] = []
    room_temps: List[float] = []
    tap_kwh_th_list: List[float] = []
    dhw_targets: List[float] = []

    for i in range(n):
        if is_15m:
            hs = heat_slots[i] if i < len(heat_slots) else None
            ps = plan_slots[i] if i < len(plan_slots) else None
            t_out = float(getattr(hs, "outdoor_temp_c", 4.5) if hs else 4.5)
            t_rm = float(getattr(hs, "room_temp_c", 20.0) if hs else 20.0)
            t_dhw = float(dhw_temps_raw[i]) if i < len(dhw_temps_raw) else 48.0
            tap_th = float(dhw_tap_raw[i]) if i < len(dhw_tap_raw) else 0.05
            tgt_c = float(getattr(ps, "target_temp_c", None) or default_dhw_target) if ps else default_dhw_target
        else:
            idx0, idx1 = i * 4, min(max(len(heat_slots), len(plan_slots), len(dhw_temps_raw)), i * 4 + 4)
            h_chunk = heat_slots[idx0:idx1] if idx0 < len(heat_slots) else []
            d_chunk = dhw_temps_raw[idx0:idx1] if idx0 < len(dhw_temps_raw) else []
            t_chunk = dhw_tap_raw[idx0:idx1] if idx0 < len(dhw_tap_raw) else []
            p_chunk = plan_slots[idx0:idx1] if idx0 < len(plan_slots) else []
            t_out = sum(float(getattr(x, "outdoor_temp_c", 4.5)) for x in h_chunk) / len(h_chunk) if h_chunk else 4.5
            t_rm = sum(float(getattr(x, "room_temp_c", 20.0)) for x in h_chunk) / len(h_chunk) if h_chunk else 20.0
            t_dhw = sum(float(x) for x in d_chunk) / len(d_chunk) if d_chunk else 48.0
            tap_th = sum(float(x) for x in t_chunk) if t_chunk else 0.20
            tgt_c = max((float(getattr(x, "target_temp_c", None) or default_dhw_target) for x in p_chunk), default=default_dhw_target)

        outdoor_temps.append(round(t_out, 1))
        boiler_temps.append(round(t_dhw, 1))
        room_temps.append(round(t_rm, 2))
        tap_kwh_th_list.append(round(tap_th, 3))
        dhw_targets.append(round(tgt_c, 1))

    # Arrays per row
    p_buy_arr = [round(float(prices[i]), 4) for i in range(n)]
    p_sell_arr = [round(float(export_prices[i]), 4) for i in range(n)]
    p_solar_arr = list(p_sell_arr)

    sol_kwh_arr = [round(float(solar_kw[i]) * step_h, 3) for i in range(n)]
    bat_dis_kwh_arr = [round(float(battery_discharge_kw[i]) * step_h, 3) for i in range(n)]
    sluip_kwh_arr = [round(min(0.30, float(unallocated_kw[i])) * step_h, 3) for i in range(n)]
    other_kwh_arr = [round(max(0.0, float(unallocated_kw[i]) - 0.30) * step_h, 3) for i in range(n)]
    house_kwh_arr = [round(sluip_kwh_arr[i] + other_kwh_arr[i], 3) for i in range(n)]

    heat_el_kwh_arr = [round(float(heating_kw[i]) * step_h, 3) for i in range(n)]
    dhw_el_kwh_arr = [round(float(boiler_kw[i]) * step_h, 3) for i in range(n)]
    bat_ch_kwh_arr = [round(float(battery_charge_kw[i]) * step_h, 3) for i in range(n)]

    # COPs
    cop_dhw_norm_arr: List[float] = []
    cop_dhw_boost_arr: List[float] = []
    cop_heat_arr: List[float] = []
    for i in range(n):
        to = outdoor_temps[i]
        cop_dhw_norm_arr.append(round(min(3.2, max(1.4, 2.35 + 0.05 * (to - 10.0))), 2))
        cop_dhw_boost_arr.append(round(min(3.2, max(1.4, 1.65 + 0.05 * (to - 10.0))), 2))
        cop_heat_arr.append(round(min(6.0, max(2.2, 4.45 + 0.11 * (to - 5.0))), 2))

    # Thermal production & losses
    wp_dhw_th_arr = [
        round(dhw_el_kwh_arr[i] * (cop_dhw_boost_arr[i] if boiler_temps[i] > 48.5 else cop_dhw_norm_arr[i]), 3)
        for i in range(n)
    ]
    wp_heat_th_arr = [round(heat_el_kwh_arr[i] * cop_heat_arr[i], 3) for i in range(n)]
    dhw_standby_th_arr = [round(0.00238 * max(0.0, boiler_temps[i] - 20.0) * step_h, 3) for i in range(n)]
    heat_loss_th_arr = [
        round(max(0.0, 0.3085 * max(0.0, room_temps[i] - outdoor_temps[i]) * step_h - 0.68 * step_h - 0.15 * sol_kwh_arr[i]), 3)
        for i in range(n)
    ]

    # 5-Step Solar Waterfall (kWh)
    zon_house_arr: List[float] = []
    grid_house_arr: List[float] = []
    zon_after_house_arr: List[float] = []
    zon_heat_arr: List[float] = []
    grid_heat_arr: List[float] = []
    zon_after_heat_arr: List[float] = []
    zon_dhw_arr: List[float] = []
    grid_dhw_arr: List[float] = []
    zon_after_dhw_arr: List[float] = []
    zon_bat_ch_arr: List[float] = []
    grid_bat_ch_arr: List[float] = []
    zon_export_arr: List[float] = []

    for i in range(n):
        avail_0 = sol_kwh_arr[i]
        zh = round(min(avail_0, house_kwh_arr[i]), 3)
        gh = round(max(0.0, house_kwh_arr[i] - avail_0), 3)
        rem_h = round(max(0.0, avail_0 - house_kwh_arr[i]), 3)

        z_cv = round(min(rem_h, heat_el_kwh_arr[i]), 3)
        g_cv = round(max(0.0, heat_el_kwh_arr[i] - rem_h), 3)
        rem_cv = round(max(0.0, rem_h - heat_el_kwh_arr[i]), 3)

        z_dhw = round(min(rem_cv, dhw_el_kwh_arr[i]), 3)
        g_dhw = round(max(0.0, dhw_el_kwh_arr[i] - rem_cv), 3)
        rem_dhw = round(max(0.0, rem_cv - dhw_el_kwh_arr[i]), 3)

        z_bat = round(min(rem_dhw, bat_ch_kwh_arr[i]), 3)
        g_bat = round(max(0.0, bat_ch_kwh_arr[i] - rem_dhw), 3)
        rem_exp = round(max(0.0, rem_dhw - bat_ch_kwh_arr[i]), 3)

        zon_house_arr.append(zh)
        grid_house_arr.append(gh)
        zon_after_house_arr.append(rem_h)
        zon_heat_arr.append(z_cv)
        grid_heat_arr.append(g_cv)
        zon_after_heat_arr.append(rem_cv)
        zon_dhw_arr.append(z_dhw)
        grid_dhw_arr.append(g_dhw)
        zon_after_dhw_arr.append(rem_dhw)
        zon_bat_ch_arr.append(z_bat)
        grid_bat_ch_arr.append(g_bat)
        zon_export_arr.append(rem_exp)

    # Stand-alone Heat Cost Decision Matrix (€/kWh_th against zon_after_house_arr due to 3-way valve!)
    hp_cv_cost_arr: List[float] = []
    hp_dhw_norm_cost_arr: List[float] = []
    hp_dhw_boost_cost_arr: List[float] = []

    ref_cv_el = 0.80 * step_h
    ref_dhw_norm_el = 2.60 * step_h
    ref_dhw_boost_el = 3.40 * step_h

    for i in range(n):
        pool = zon_after_house_arr[i]
        pb, ps = p_buy_arr[i], p_solar_arr[i]

        el_cost_cv = (min(ref_cv_el, pool) * ps + max(0.0, ref_cv_el - pool) * pb) / max(1e-6, ref_cv_el)
        el_cost_dn = (min(ref_dhw_norm_el, pool) * ps + max(0.0, ref_dhw_norm_el - pool) * pb) / max(1e-6, ref_dhw_norm_el)
        el_cost_db = (min(ref_dhw_boost_el, pool) * ps + max(0.0, ref_dhw_boost_el - pool) * pb) / max(1e-6, ref_dhw_boost_el)

        hp_cv_cost_arr.append(round(el_cost_cv / cop_heat_arr[i], 4))
        hp_dhw_norm_cost_arr.append(round(el_cost_dn / cop_dhw_norm_arr[i], 4))
        hp_dhw_boost_cost_arr.append(round((el_cost_db / cop_dhw_boost_arr[i]) * 1.05, 4))

    # Storage kWh_th
    storage_dhw_arr = [round(max(0.0, (boiler_temps[i] - 38.0) * 0.4068), 2) for i in range(n)]
    storage_floor_arr = [round(max(0.0, (room_temps[i] - 19.5) * 5.0), 2) for i in range(n)]

    # 2-Sided Battery Waterfall & Hold Metrics
    bat_slots = list(bat_summary.slots) if (bat_summary is not None and getattr(bat_summary, "slots", None)) else []
    c_deg = 0.074
    p75_zom = round(sorted([max(0.0, p - c_deg) for p in p_buy_arr])[int(0.75 * max(0, n - 1))], 4) if n > 0 else 0.35

    bat_shadow_arr: List[float] = []
    bat_val_zom_arr: List[float] = []
    bat_val_exp_arr: List[float] = []
    bat_dis_zom_arr: List[float] = []
    bat_dis_exp_arr: List[float] = []
    bat_mode_arr: List[str] = []
    bat_soc_kwh_arr: List[float] = []
    bat_wac_arr: List[float] = []
    bat_breakeven_arr: List[float] = []

    for i in range(n):
        vz = round(p_buy_arr[i] - c_deg, 4)
        ve = round(p_sell_arr[i] - c_deg, 4)
        bat_val_zom_arr.append(vz)
        bat_val_exp_arr.append(ve)

        if i < len(bat_slots):
            bs = bat_slots[i]
            sh = float(getattr(bs, "shadow_price_eur", 0.0) or p75_zom)
            dz = round(float(getattr(bs, "dis_zom_kw", 0.0) or 0.0) * step_h, 3)
            de = round(float(getattr(bs, "dis_exp_kw", 0.0) or 0.0) * step_h, 3)
            sk = round(float(getattr(bs, "soc_kwh", 0.0) or 0.0), 2)
            wc = round(float(getattr(bs, "wac_dc_eur", 0.14) or 0.14), 4)
            be = round(float(getattr(bs, "breakeven_lcos_eur", 0.22) or 0.22), 4)
            mc = str(getattr(bs, "mode_code", "STANDBY"))
        else:
            sh = p75_zom
            deficit_kwh = round(grid_house_arr[i] + grid_heat_arr[i] + grid_dhw_arr[i], 3)
            dz = round(min(bat_dis_kwh_arr[i], deficit_kwh), 3)
            de = round(max(0.0, bat_dis_kwh_arr[i] - dz), 3)
            sk = 0.0
            wc = 0.14
            be = 0.224
            if zon_bat_ch_arr[i] > 0.01:
                mc = "CH_PV"
            elif grid_bat_ch_arr[i] > 0.01:
                mc = "CH_GRID"
            elif de > 0.01:
                mc = "EXPORT"
            elif dz > 0.01:
                mc = "ZOM"
            else:
                mc = "HOLD" if vz < sh else "STANDBY"

        bat_shadow_arr.append(round(sh, 4))
        bat_dis_zom_arr.append(dz)
        bat_dis_exp_arr.append(de)
        bat_soc_kwh_arr.append(sk)
        bat_wac_arr.append(wc)
        bat_breakeven_arr.append(be)
        bat_mode_arr.append(mc)

    # Financial Settlement (€)
    cost_house_eur_arr: List[float] = []
    cost_heat_eur_arr: List[float] = []
    cost_dhw_eur_arr: List[float] = []
    rev_export_eur_arr: List[float] = []
    net_invoice_eur_arr: List[float] = []

    for i in range(n):
        pb, ps = p_buy_arr[i], p_sell_arr[i]
        ch_eur = round(grid_house_arr[i] * pb, 4)
        ccv_eur = round(grid_heat_arr[i] * pb + zon_heat_arr[i] * ps, 4)
        cdhw_eur = round(grid_dhw_arr[i] * pb + zon_dhw_arr[i] * ps, 4)
        rexp_eur = round((zon_export_arr[i] + bat_dis_exp_arr[i]) * ps, 4)
        tot_grid_imp = max(0.0, grid_house_arr[i] + grid_heat_arr[i] + grid_dhw_arr[i] + grid_bat_ch_arr[i] - bat_dis_zom_arr[i])
        net_inv = round(tot_grid_imp * pb - rexp_eur, 4)

        cost_house_eur_arr.append(ch_eur)
        cost_heat_eur_arr.append(ccv_eur)
        cost_dhw_eur_arr.append(cdhw_eur)
        rev_export_eur_arr.append(rexp_eur)
        net_invoice_eur_arr.append(net_inv)

    # Active slot flags for Heatmap badges
    chosen_cv_flags = [heat_el_kwh_arr[i] > 0.01 for i in range(n)]
    chosen_dhw_norm_flags = [dhw_el_kwh_arr[i] > 0.01 and dhw_targets[i] <= 51.0 for i in range(n)]
    chosen_dhw_boost_flags = [dhw_el_kwh_arr[i] > 0.01 and dhw_targets[i] > 51.0 for i in range(n)]
    lockout_flags = [i in lockouts for i in range(n)]

    # Terminal storage valuation (End vs Start of horizon)
    avg_dhw_cost = sum(hp_dhw_norm_cost_arr) / n if n else 0.22
    avg_cv_cost = sum(hp_cv_cost_arr) / n if n else 0.10
    delta_dhw_th = (storage_dhw_arr[-1] - storage_dhw_arr[0]) if n > 1 else 0.0
    delta_floor_th = (storage_floor_arr[-1] - storage_floor_arr[0]) if n > 1 else 0.0
    terminal_val_eur = round(delta_dhw_th * avg_dhw_cost + delta_floor_th * avg_cv_cost, 2)
    tot_invoice_eur = round(sum(net_invoice_eur_arr), 2)
    true_economic_eur = round(tot_invoice_eur - terminal_val_eur, 2)

    return {
        "labels": labels,
        "step_h": step_h,
        "lockout_flags": lockout_flags,
        "chosen_cv_flags": chosen_cv_flags,
        "chosen_dhw_norm_flags": chosen_dhw_norm_flags,
        "chosen_dhw_boost_flags": chosen_dhw_boost_flags,
        "terminal_value_delta_eur": terminal_val_eur,
        "total_invoice_eur": tot_invoice_eur,
        "true_economic_cost_eur": true_economic_eur,
        "series": {
            "kwh_buy": p_buy_arr,
            "kwh_sell": p_sell_arr,
            "kwh_solar": p_solar_arr,
            "solar_kwh": sol_kwh_arr,
            "sluip_kwh": sluip_kwh_arr,
            "other_kwh": other_kwh_arr,
            "house_total_kwh": house_kwh_arr,
            "heating_el_kwh": heat_el_kwh_arr,
            "dhw_el_kwh": dhw_el_kwh_arr,
            "dhw_tap_kwh_th": tap_kwh_th_list,
            "dhw_standby_kwh_th": dhw_standby_th_arr,
            "heating_loss_kwh_th": heat_loss_th_arr,
            "wp_prod_dhw_kwh_th": wp_dhw_th_arr,
            "wp_prod_heating_kwh_th": wp_heat_th_arr,
            "zon_house_kwh": zon_house_arr,
            "grid_house_kwh": grid_house_arr,
            "zon_after_house_kwh": zon_after_house_arr,
            "zon_heat_kwh": zon_heat_arr,
            "grid_heat_kwh": grid_heat_arr,
            "zon_after_heat_kwh": zon_after_heat_arr,
            "zon_dhw_kwh": zon_dhw_arr,
            "grid_dhw_kwh": grid_dhw_arr,
            "zon_after_dhw_kwh": zon_after_dhw_arr,
            "zon_export_kwh": zon_export_arr,
            "storage_dhw_kwh_th": storage_dhw_arr,
            "boiler_temp_c": boiler_temps,
            "storage_floor_kwh_th": storage_floor_arr,
            "room_temp_c": room_temps,
            "outdoor_temp_c": outdoor_temps,
            "cop_dhw_norm": cop_dhw_norm_arr,
            "cop_dhw_boost": cop_dhw_boost_arr,
            "cop_heating": cop_heat_arr,
            "heat_price_cv": hp_cv_cost_arr,
            "heat_price_dhw_norm": hp_dhw_norm_cost_arr,
            "heat_price_dhw_boost": hp_dhw_boost_cost_arr,
            "bat_shadow_price": bat_shadow_arr,
            "bat_val_zom": bat_val_zom_arr,
            "bat_val_exp": bat_val_exp_arr,
            "bat_ch_pv_kwh": zon_bat_ch_arr,
            "bat_ch_grid_kwh": grid_bat_ch_arr,
            "bat_dis_zom_kwh": bat_dis_zom_arr,
            "bat_dis_exp_kwh": bat_dis_exp_arr,
            "bat_mode": bat_mode_arr,
            "bat_soc_kwh": bat_soc_kwh_arr,
            "bat_wac_eur": bat_wac_arr,
            "bat_breakeven_eur": bat_breakeven_arr,
            "cost_house_eur": cost_house_eur_arr,
            "cost_heat_eur": cost_heat_eur_arr,
            "cost_dhw_eur": cost_dhw_eur_arr,
            "rev_export_eur": rev_export_eur_arr,
            "net_invoice_eur": net_invoice_eur_arr,
        },
    }
