import json

from app.missions import MissionFiles, validate_mission_files
from tests.test_mission_schema import VALID_MISSION, VALID_OBJECTIVE, VALID_SLOTS

BRIEF = "# Operation Test\n\n## Situation\n\n" + "Enemy forces hold the town. " * 10


def make_files(**overrides) -> MissionFiles:
    mission = dict(VALID_MISSION)
    defaults = {
        "directory": "active/OP-010-test",
        "mission_json": json.dumps(mission),
        "brief_md": BRIEF,
        "objectives_json": json.dumps([VALID_OBJECTIVE]),
        "slots_json": json.dumps(
            {"categories": [{"name": "Infantry", "slots": [{"role": "Rifleman", "count": 32}]}]}
        ),
    }
    return MissionFiles(**{**defaults, **overrides})


def test_fully_valid_mission():
    report = validate_mission_files(make_files())
    assert report.is_valid, report.errors
    assert report.passed == ["mission.json", "brief.md", "objectives.json", "slots.json"]
    assert report.mission_id == "OP-010"


def test_missing_mission_json_is_error():
    report = validate_mission_files(make_files(mission_json=None))
    assert not report.is_valid
    assert report.metadata is None
    assert any("mission.json: file is missing" in e for e in report.errors)


def test_malformed_json_is_error_not_crash():
    report = validate_mission_files(make_files(mission_json="{not json"))
    assert not report.is_valid
    assert any("not valid JSON" in e for e in report.errors)


def test_missing_brief_is_error():
    report = validate_mission_files(make_files(brief_md=None))
    assert not report.is_valid
    assert any("brief.md: file is missing" in e for e in report.errors)


def test_empty_brief_is_error():
    report = validate_mission_files(make_files(brief_md="   \n"))
    assert any("brief.md: file is empty" in e for e in report.errors)


def test_duplicate_objective_ids_reported():
    objectives = [VALID_OBJECTIVE, {**VALID_OBJECTIVE, "name": "Copy of Objective"}]
    report = validate_mission_files(make_files(objectives_json=json.dumps(objectives)))
    assert not report.is_valid
    assert any("duplicate objective ID" in e for e in report.errors)


def test_slot_total_mismatch_is_warning_not_error():
    slots = {"categories": [{"name": "Infantry", "slots": [{"role": "Rifleman", "count": 5}]}]}
    report = validate_mission_files(make_files(slots_json=json.dumps(slots)))
    assert report.is_valid  # warnings don't fail validation
    assert any("does not match maximum_players" in w for w in report.warnings)
    assert any("below minimum_players" in w for w in report.warnings)


def test_directory_id_mismatch_is_warning():
    report = validate_mission_files(make_files(directory="active/OP-999-wrong-name"))
    assert any("should start with the mission ID" in w for w in report.warnings)


def test_archived_directory_with_active_status_is_warning():
    report = validate_mission_files(make_files(directory="archived/OP-010-test"))
    assert any("archived/" in w for w in report.warnings)


def test_multiple_independent_errors_all_reported():
    mission = {**VALID_MISSION, "minimum_players": 40}  # max (32) < min (40)
    objectives = [VALID_OBJECTIVE, {**VALID_OBJECTIVE, "name": "Duplicate"}]
    report = validate_mission_files(
        make_files(mission_json=json.dumps(mission), objectives_json=json.dumps(objectives), brief_md=None)
    )
    assert not report.is_valid
    assert len(report.errors) == 3
