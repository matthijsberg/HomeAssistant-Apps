"""Room climate I/O: Madoka room temperature, setpoint and writes on the Daikin room heating circuit."""
import pytest

from integrations.daikin_altherma.reader import (
    ROOM_HEATING_CIRCUIT_ENTITY, read_room_climate, room_setpoint_service_call
)


def _states(madoka=21.4, circuit_setpoint=20.5, woonkamer_low=19.0):
    return {
        "climate.woonkamer_climate_daikin": {"state": "heat", "attributes": {
            "current_temperature": madoka, "target_temp_low": woonkamer_low, "target_temp_high": 24.5}},
        ROOM_HEATING_CIRCUIT_ENTITY: {"state": "heat", "attributes": {
            "temperature": circuit_setpoint, "current_temperature": 21.5, "target_temp_step": 0.5}},
    }


def test_setpoint_comes_from_room_heating_circuit_and_room_from_madoka():
    room = read_room_climate(_states())
    assert room.room_temp_c == pytest.approx(21.4)
    assert room.setpoint_c == pytest.approx(20.5)  # not the Madoka climate's target_temp_low (19.0)


def test_missing_circuit_setpoint_is_none_not_guessed():
    s = _states()
    s[ROOM_HEATING_CIRCUIT_ENTITY] = {"state": "unavailable", "attributes": {}}
    assert read_room_climate(s).setpoint_c is None


@pytest.mark.parametrize("requested, written", [(22.4, 22.5), (21.2, 21.0), (21.0, 21.0), (20.75, 21.0)])
def test_setpoint_write_targets_room_heating_circuit_in_half_degree_steps(requested, written):
    domain, service, data = room_setpoint_service_call(requested)
    assert (domain, service) == ("climate", "set_temperature")
    assert data == {"entity_id": ROOM_HEATING_CIRCUIT_ENTITY, "temperature": written}
