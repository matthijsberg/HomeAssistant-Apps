"""Tests for Elephant (contextual multi-turn) and Goldfish (stateless atomic) review modes."""

import pytest
from domotica import DomoticaEngine
from resolver import HAResolver


@pytest.fixture
def mock_resolver():
    res = HAResolver()
    res._area_name_map = {"serre": "serre", "woonkamer": "woonkamer"}
    cached = {
        "light.serre_spots_dimmer": {
            "entity_id": "light.serre_spots_dimmer",
            "friendly_name": "spots serre",
            "state": "on",
            "attributes": {"friendly_name": "spots serre"},
        },
        "light.woonkamer_hanglamp": {
            "entity_id": "light.woonkamer_hanglamp",
            "friendly_name": "hanglamp woonkamer",
            "state": "off",
            "attributes": {"friendly_name": "hanglamp woonkamer"},
        },
    }
    res.load_cached_entities(cached)
    res._last_sync_time = 9999999999.0
    return res


def test_goldfish_mode_stateless_pronoun_rejection(mock_resolver):
    """Goldfish mode evaluates in pure isolation: pronouns fail fast-path as unknown_target."""
    engine = DomoticaEngine(resolver=mock_resolver, fast_path_enabled=True)

    # Prompt with pronoun and no prior context
    action = engine.parse("zet ze uit", review_mode="goldfish")
    assert action.is_domotica is True
    assert action.fast_path is False
    assert action.rejected_reason == "unknown_target"
    assert action.review_mode == "goldfish"
    assert action.context_applied is False
    assert action.context_source is None


def test_elephant_mode_anaphora_pronoun_resolution(mock_resolver):
    """Elephant mode retains prior turns and resolves pronouns to the previous target."""
    engine = DomoticaEngine(resolver=mock_resolver, fast_path_enabled=True)

    # Turn 1: Explicit target
    turn1 = engine.parse("zet de spots in de serre aan", review_mode="elephant")
    assert turn1.fast_path is True
    assert turn1.target_id == "light.serre_spots_dimmer"

    recent_turns = [
        {
            "target_id": turn1.target_id,
            "target_type": turn1.target_type,
            "target_name": turn1.target_name,
            "domain": turn1.domain,
        }
    ]

    # Turn 2: Pronoun "ze" in Elephant mode resolves to light.serre_spots_dimmer
    turn2 = engine.parse("zet ze uit", recent_turns=recent_turns, review_mode="elephant")
    assert turn2.fast_path is True
    assert turn2.service == "turn_off"
    assert turn2.target_id == "light.serre_spots_dimmer"
    assert turn2.context_applied is True
    assert turn2.context_source is not None
    assert turn2.context_source["target_id"] == "light.serre_spots_dimmer"
    assert turn2.context_source["reason"] == "anaphora_pronoun_resolution"


def test_elephant_mode_brightness_adjustment(mock_resolver):
    """Elephant mode carries entity into numeric percentage adjustments."""
    engine = DomoticaEngine(resolver=mock_resolver, fast_path_enabled=True)

    recent_turns = [
        {
            "target_id": "light.woonkamer_hanglamp",
            "target_type": "entity_id",
            "target_name": "hanglamp woonkamer",
            "domain": "light",
        }
    ]

    # "dim hem naar 40%"
    turn = engine.parse("dim hem naar 40%", recent_turns=recent_turns, review_mode="elephant")
    assert turn.fast_path is True
    assert turn.service == "turn_on"
    assert turn.target_id == "light.woonkamer_hanglamp"
    assert turn.service_data.get("brightness_pct") == 40
    assert turn.context_applied is True
