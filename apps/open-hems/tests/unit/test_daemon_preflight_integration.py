from unittest.mock import patch, MagicMock
from daemon import HemsBackgroundCollector
from layer4_control.preflight.models import GatekeeperDecision, SubsystemLiveState


def test_daemon_uses_preflight_coordinator():
    collector = HemsBackgroundCollector()
    with patch("daemon.GLOBAL_PREFLIGHT_COORDINATOR") as mock_coord:
        mock_coord.evaluate_all.return_value = {
            "dhw": GatekeeperDecision("NORMAL", "Alles normaal", "normal"),
            "heating": GatekeeperDecision("NORMAL", "Alles normaal", "normal"),
            "battery": GatekeeperDecision("ALLOW", "Toegestaan", "IDLE"),
        }
        with patch("daemon.get_ha_states_map") as mock_states:
            mock_states.return_value = {
                "sensor.warmtepomp_boiler_temperatuur": {"state": "45.0"},
                "sensor.warmtepomp_power": {"state": "0.0"},
                "binary_sensor.warmtepomp_driewegklep": {"state": "off"},
                "switch.hc_mode_altherma_on": {"state": "on"},
                "climate.hc_room_room_heating": {"state": "heat", "attributes": {"current_temperature": 20.0, "temperature": 20.0}}
            }
            with patch("daemon.ensure_active_canonical_plan") as mock_plan:
                mock_plan.return_value = None
                with patch("daemon.make_daikin_ha_actuator") as mock_actuator:
                    mock_act_inst = MagicMock()
                    mock_actuator.return_value = mock_act_inst
                    mock_act_inst.execute_mode.return_value = MagicMock(success=True)
                    collector.execute_live_dispatch()
                    assert mock_coord.evaluate_all.called
