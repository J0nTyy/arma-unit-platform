import pytest
from pydantic import ValidationError

from app.missions import (
    MissionMetadata,
    MissionObjectives,
    MissionSlots,
    MissionStatus,
)

VALID_MISSION = {
    "id": "OP-010",
    "name": "Operation Test",
    "status": "ready",
    "mission_maker": "Tester",
    "description": "A test mission used by the automated test suite.",
    "map": "Altis",
    "mission_type": "Direct Action",
    "difficulty": "hard",
    "minimum_players": 8,
    "maximum_players": 32,
    "estimated_duration_minutes": 120,
    "factions": ["NATO"],
    "required_mods": ["CBA_A3"],
    "tags": ["night"],
    "version": "1.0.0",
}


def make_mission(**overrides):
    return MissionMetadata.model_validate({**VALID_MISSION, **overrides})


def test_valid_mission_parses():
    mission = make_mission()
    assert mission.id == "OP-010"
    assert mission.status is MissionStatus.READY
    assert mission.tags == ["night"]


def test_missing_required_field_rejected():
    data = dict(VALID_MISSION)
    del data["map"]
    with pytest.raises(ValidationError, match="map"):
        MissionMetadata.model_validate(data)


def test_unknown_field_rejected():
    # Catches typos like "max_players" instead of "maximum_players"
    with pytest.raises(ValidationError, match="max_players"):
        make_mission(max_players=10)


def test_schema_key_is_tolerated():
    # "$schema" is allowed so editors can offer IntelliSense
    mission = make_mission(**{"$schema": "./schema/mission.schema.json"})
    assert mission.id == "OP-010"


def test_invalid_status_rejected():
    with pytest.raises(ValidationError, match="status"):
        make_mission(status="in-progress")


def test_status_is_case_insensitive():
    assert make_mission(status="READY").status is MissionStatus.READY


def test_invalid_difficulty_rejected():
    with pytest.raises(ValidationError, match="difficulty"):
        make_mission(difficulty="nightmare")


def test_invalid_mission_id_format_rejected():
    with pytest.raises(ValidationError, match="id"):
        make_mission(id="operation one")


def test_player_count_maximum_below_minimum_rejected():
    with pytest.raises(ValidationError, match="maximum_players must be >= minimum_players"):
        make_mission(minimum_players=20, maximum_players=10)


def test_zero_players_rejected():
    with pytest.raises(ValidationError):
        make_mission(minimum_players=0)


def test_invalid_version_rejected():
    with pytest.raises(ValidationError, match="version"):
        make_mission(version="1.0")


def test_blank_required_mod_rejected():
    with pytest.raises(ValidationError, match="empty"):
        make_mission(required_mods=["CBA_A3", "  "])


def test_tags_normalized_and_deduplicated():
    mission = make_mission(tags=["Night", "night", " Stealth "])
    assert mission.tags == ["night", "stealth"]


VALID_OBJECTIVE = {
    "id": "OBJ-01",
    "name": "Destroy Radar",
    "description": "Destroy the enemy radar installation.",
    "type": "primary",
    "required": True,
}


def test_valid_objectives_parse():
    objectives = MissionObjectives.model_validate([VALID_OBJECTIVE])
    assert objectives.root[0].id == "OBJ-01"


def test_invalid_objective_type_rejected():
    with pytest.raises(ValidationError, match="type"):
        MissionObjectives.model_validate([{**VALID_OBJECTIVE, "type": "tertiary"}])


def test_duplicate_objective_ids_rejected():
    second = {**VALID_OBJECTIVE, "name": "Other Objective"}
    with pytest.raises(ValidationError, match="duplicate objective ID"):
        MissionObjectives.model_validate([VALID_OBJECTIVE, second])


def test_empty_objectives_rejected():
    with pytest.raises(ValidationError, match="at least one objective"):
        MissionObjectives.model_validate([])


VALID_SLOTS = {
    "categories": [
        {"name": "Infantry", "slots": [{"role": "Rifleman", "count": 8}]},
        {"name": "Support", "slots": [{"role": "Medic", "count": 2}]},
    ]
}


def test_valid_slots_parse_and_count():
    slots = MissionSlots.model_validate(VALID_SLOTS)
    assert slots.total_player_count == 10


def test_slot_count_zero_rejected():
    with pytest.raises(ValidationError):
        MissionSlots.model_validate(
            {"categories": [{"name": "Infantry", "slots": [{"role": "Rifleman", "count": 0}]}]}
        )


def test_duplicate_slot_category_rejected():
    with pytest.raises(ValidationError, match="duplicate slot category"):
        MissionSlots.model_validate(
            {
                "categories": [
                    {"name": "Infantry", "slots": [{"role": "Rifleman", "count": 1}]},
                    {"name": "infantry", "slots": [{"role": "Medic", "count": 1}]},
                ]
            }
        )
