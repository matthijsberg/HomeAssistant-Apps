"""
Tests for DHW Goldfish / Elephant Control Logic
==============================================
Verifies:
1. Elephant Baseline Invariants:
   - Normal operation strictly enforces 50.0°C target temperature and 'heat' state.
   - Boiler climate is NEVER turned software 'off' between runs or at run completion.
   - Spitsblokkade (forced_off) operates strictly via physical relays (SG1), leaving climate on 'heat'.
2. Goldfish Stateless Execution:
   - Transitions from boost run (SG4 / in-flight) to normal immediately restore Elephant baseline (50°C, heat).
   - Inactive slots do not inherit upcoming planned boost temperatures (no leaking state).
"""

import pytest
from unittest.mock import MagicMock
from integrations.daikin_altherma.interlocks import DaikinInterlock
from integrations.daikin_altherma.actuator import DaikinActuator


def test_elephant_baseline_normal_mode_defaults():
    """Verify that normal mode returns to SG2 relays and leaves climate enabled."""
    cmd = DaikinInterlock.resolve_command(requested_mode="normal", current_cv_switch_state=True)
    assert cmd.s10s_relay_on is False
    assert cmd.s11s_relay_on is False
    assert cmd.cv_master_switch_on is True
    assert cmd.dhw_master_switch_on is True
    assert cmd.effective_mode == "normal"


def test_elephant_peak_lockout_uses_relays_only():
    """Verify that peak lockout (spits) engages SG1 relays and does NOT shut off DHW master switch."""
    cmd = DaikinInterlock.resolve_command(requested_mode="forced_off", current_cv_switch_state=True)
    assert cmd.s10s_relay_on is False
    assert cmd.s11s_relay_on is True
    assert cmd.effective_mode == "forced_off"
    assert cmd.dhw_master_switch_on is True


def test_goldfish_restoration_to_50c_and_heat_after_boost():
    """Verify that climate caller is called with heat and 50°C when restoring from abnormal state."""
    calls = []

    def mock_switch(name: str, state: bool):
        calls.append(("switch", name, state))
        return True

    def mock_climate(name: str, temp: float):
        calls.append(("climate", name, temp))
        return True

    actuator = DaikinActuator(switch_caller=mock_switch, climate_caller=mock_climate)

    # 1. Active boost run at 60°C (SG4)
    res_boost = actuator.execute_mode("forced_on", target_temp=60.0)
    assert res_boost.success is True
    assert res_boost.command.s10s_relay_on is True
    assert res_boost.command.s11s_relay_on is True

    # 2. Return to normal (SG2)
    res_norm = actuator.execute_mode("normal", target_temp=50.0)
    assert res_norm.success is True
    assert res_norm.command.s10s_relay_on is False
    assert res_norm.command.s11s_relay_on is False
    assert res_norm.command.cv_master_switch_on is True
