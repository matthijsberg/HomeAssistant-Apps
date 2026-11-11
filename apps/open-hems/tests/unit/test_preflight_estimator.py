from layer4_control.preflight.estimator import (
    estimate_dhw_run_duration_mins,
    estimate_dhw_standby_loss_c,
)


def test_estimate_dhw_run_duration():
    # Opwarmen van 40°C naar 50°C bij 10°C buitentemperatuur duurt tussen de 30 en 60 minuten
    dur = estimate_dhw_run_duration_mins(t_start_c=40.0, t_target_c=50.0, t_outdoor_c=10.0)
    assert 30.0 <= dur <= 60.0


def test_estimate_dhw_already_warm():
    dur = estimate_dhw_run_duration_mins(t_start_c=50.5, t_target_c=50.0, t_outdoor_c=10.0)
    assert dur == 0.0


def test_estimate_dhw_standby_loss():
    # 2.5 uur spitsblokkade -> verlies ca. 0.6°C
    loss = estimate_dhw_standby_loss_c(duration_hours=2.5)
    assert 0.4 <= loss <= 0.8
