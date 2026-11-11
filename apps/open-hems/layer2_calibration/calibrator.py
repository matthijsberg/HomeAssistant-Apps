#!/usr/bin/env python3
"""
Model Calibration & Adaptive Offset Engine
==========================================
Self-learning empirical feedback loop for HEMS predictive modeling.

Solves:
  1. Solar Orientation, Tilt & Shading Profile:
     Replaces generic flat-plate assumptions with an hourly empirical yield coefficient K(h)
     derived from actual inverter production vs. global radiation. Accounts for roof tilt,
     southwest orientation, and morning/afternoon shading.
  2. Domestic Hot Water (DHW) Energy & Loss Model:
     Calibrates standby tank cooling losses (Q_standby) and empirical COP from actual heat pump runs.
  3. Space Heating Building Envelope (UA & Infiltration):
     Performs multi-variable Ordinary Least Squares (OLS) regression over thermal heat output,
     indoor/outdoor temperature delta, wind speed, and passive solar gains.
"""

import os
import json
import math
from datetime import datetime
from typing import Optional

CONFIG_PATH = "/config/heatpump_config.json"
MODEL_PARAMS_PATH = "/config/heatpump_model_parameters.json"


class ModelCalibrationEngine:
    def __init__(self, config_path: str = CONFIG_PATH, params_path: str = MODEL_PARAMS_PATH):
        self.config_path = config_path
        self.params_path = params_path
        self.config = self._load_json(self.config_path)
        self.params = self._load_json(self.params_path)

    def _load_json(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not read {path}: {e}")
        return {}

    def _save_params(self):
        """Merges this engine's parameters into the on-disk file under the parameter-store lock."""
        from layer2_calibration.params_store import update_params
        snapshot = dict(self.params or {})
        try:
            def _merge(data):
                data.update(snapshot)
            self.params = update_params(_merge, self.params_path)
        except Exception as e:
            print(f"Warning: Could not save model parameters: {e}")

    def is_sample_excluded(self, sensor_name: str, ts) -> bool:
        """Checks if a sample timestamp falls inside any configured data exclusion window."""
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        elif isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts[:19])
            except ValueError:
                return False
        else:
            dt = ts

        d_str = dt.strftime("%Y-%m-%d")
        for win in self.config.get("data_exclusion_windows", []):
            win_sensor = win.get("sensor")
            if win_sensor and (win_sensor == sensor_name or win_sensor in sensor_name):
                start = win.get("start", "1970-01-01")
                end = win.get("end", "2099-12-31")
                if start <= d_str <= end:
                    return True
        return False

    # =========================================================================
    # GUARDRAILS & CLAMPING CONFIGURATION
    # =========================================================================
    GUARDRAILS = {
        "solar_factor_min": 0.50,
        "solar_factor_max": 2.50,
        "solar_step_limit_pct": 0.20,      # Max 20% shift per calibration run
        "dhw_standby_min_kwh": 0.80,
        "dhw_standby_max_kwh": 2.50,
        "dhw_daily_min_kwh": 3.00,
        "dhw_daily_max_kwh": 9.50,
        "ua_base_min": 6.00,
        "ua_base_max": 11.00,
        "ua_step_limit_pct": 0.15,         # Max 15% shift per calibration run
        "c_wind_min": 0.001,
        "c_wind_max": 0.080,
        "min_heating_samples_required": 10
    }

    def apply_smoothed_clamping(self, old_val: float, new_val: float, min_val: float, max_val: float, max_shift_pct: float = 0.20) -> float:
        """
        Dampens updates using Exponential Moving Average and clamps to physical boundaries.
        Prevents sensor glitches, outlier days, or cloudy weeks from skewing the model.
        """
        if old_val is None or old_val <= 0:
            return round(max(min_val, min(max_val, new_val)), 5)

        # 1. Dampen using 80% historical + 20% new observation
        smoothed = (0.80 * old_val) + (0.20 * new_val)

        # 2. Limit step change to max_shift_pct from old value
        max_allowed = old_val * (1.0 + max_shift_pct)
        min_allowed = old_val * (1.0 - max_shift_pct)
        stepped = max(min_allowed, min(max_allowed, smoothed))

        # 3. Hard physical boundary clamping
        final_val = max(min_val, min(max_val, stepped))
        return round(final_val, 5)

    # =========================================================================
    # 1. SOLAR ORIENTATION, TILT & SHADING PROFILE
    # =========================================================================
    def calculate_hourly_solar_profile(self, actual_pv_hourly: dict, radiation_hourly: dict, kwp: float = 5.5) -> dict:
        """
        Computes the hourly tilt & shading correction factor K(h) for each hour (0..23).
        actual_pv_hourly: {timestamp: kWh}
        radiation_hourly: {timestamp: W/m²}
        Returns: {hour (0..23): correction_factor (float)}
        """
        common_ts = sorted(list(set(actual_pv_hourly.keys()) & set(radiation_hourly.keys())))
        hourly_samples = {h: [] for h in range(24)}

        for ts in common_ts:
            dt = datetime.fromtimestamp(ts)
            pv_kwh = actual_pv_hourly[ts]
            rad_wm2 = radiation_hourly[ts]

            # Only analyze hours with meaningful sunlight (> 50 W/m2 and positive production)
            if rad_wm2 >= 50.0 and pv_kwh > 0.0:
                # Theoretical horizontal output for 5.5 kWp
                ideal_flat_kwh = (rad_wm2 / 1000.0) * kwp
                if ideal_flat_kwh > 0.05:
                    ratio = pv_kwh / ideal_flat_kwh
                    # Bound individual sample ratios to prevent extreme sunrise/sunset noise
                    clamped_ratio = max(0.2, min(3.5, ratio))
                    hourly_samples[dt.hour].append(clamped_ratio)

        # Build 24-hour calibrated profile
        calibrated_profile = {}
        for h in range(24):
            samples = hourly_samples[h]
            if len(samples) >= 3:
                # Robust median/mean
                avg_factor = round(sum(samples) / len(samples), 3)
                calibrated_profile[h] = avg_factor
            elif 9 <= h <= 17:
                # Reasonable default for midday hours without enough samples
                calibrated_profile[h] = 1.05
            else:
                # Sunrise/sunset defaults
                calibrated_profile[h] = 0.85

        return calibrated_profile

    # =========================================================================
    # 2. DHW STANDBY LOSS & TAPWATER ENERGY CONSUMPTION PROFILE
    # =========================================================================
    def calculate_dhw_empirical_parameters(self, actual_dhw_thermal_daily: dict, tank_volume: float = 350.0) -> dict:
        """
        Calculates average daily thermal energy demand and standby cooling losses.
        actual_dhw_thermal_daily: {timestamp: kWh}
        Returns: {
            "avg_daily_dhw_thermal_kwh": float,
            "standby_cooling_loss_kwh": float,
            "samples_count": int
        }
        """
        vals = [v for v in actual_dhw_thermal_daily.values() if v is not None and v > 0.5]
        if not vals:
            return {
                "avg_daily_dhw_thermal_kwh": 4.10,
                "standby_cooling_loss_kwh": 1.20,
                "samples_count": 0
            }

        # Average thermal energy delivered per day
        avg_dhw = round(sum(vals) / len(vals), 2)
        # Standby cooling loss is estimated as the minimum non-zero topup day (no shower day)
        standby_loss = round(min(vals), 2) if min(vals) < 2.5 else 1.20

        return {
            "avg_daily_dhw_thermal_kwh": avg_dhw,
            "standby_cooling_loss_kwh": standby_loss,
            "samples_count": len(vals)
        }

    # =========================================================================
    # 3. SPACE HEATING OLS REGRESSION (UA_base, c_wind, c_solar)
    # =========================================================================
    def solve_ols_3x3(self, X: list, Y: list) -> Optional[list]:
        """
        Solves Ordinary Least Squares: Beta = (X^T X)^(-1) X^T Y for 3 features.
        Returns None when there are too few samples or the design matrix is (near-)singular
        (e.g. collinear regressors). Callers must treat None as "no calibration update" — never
        substitute default coefficients for a failed fit.
        """
        n = len(Y)
        if n < 5:
            return None

        ATA = [[0.0] * 3 for _ in range(3)]
        ATY = [0.0] * 3

        for row_x, y in zip(X, Y):
            for i in range(3):
                ATY[i] += row_x[i] * y
                for j in range(3):
                    ATA[i][j] += row_x[i] * row_x[j]

        scale = max(abs(ATA[i][i]) for i in range(3)) or 1.0
        # Gauss-Jordan elimination on 3x4 augmented matrix [ATA | ATY]
        M = [ATA[i] + [ATY[i]] for i in range(3)]
        for i in range(3):
            pivot = M[i][i]
            if abs(pivot) < 1e-9 * scale:
                return None
            for j in range(i, 4):
                M[i][j] /= pivot
            for k in range(3):
                if k != i:
                    factor = M[k][i]
                    for j in range(i, 4):
                        M[k][j] -= factor * M[i][j]

        return [round(M[0][3], 5), round(M[1][3], 5), round(M[2][3], 5)]

    # =========================================================================
    # ACCURACY METRICS: MAE, RMSE & BIAS
    # =========================================================================
    def calculate_accuracy_metrics(self, actuals: list, predictions: list) -> dict:
        """Computes Mean Absolute Error, Root Mean Squared Error, and Mean Percentage Bias."""
        if not actuals or len(actuals) != len(predictions):
            return {"mae": 0.0, "rmse": 0.0, "bias_pct": 0.0, "n": 0}

        diffs = [p - a for a, p in zip(actuals, predictions)]
        abs_diffs = [abs(d) for d in diffs]
        sq_diffs = [d ** 2 for d in diffs]

        n = len(actuals)
        mae = sum(abs_diffs) / n
        rmse = math.sqrt(sum(sq_diffs) / n)

        mean_actual = sum(actuals) / n if sum(actuals) != 0 else 1.0
        bias_pct = (sum(diffs) / n) / mean_actual * 100.0

        return {
            "mae": round(mae, 3),
            "rmse": round(rmse, 3),
            "bias_pct": round(bias_pct, 2),
            "n": n
        }
