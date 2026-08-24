import json
from pathlib import Path

from tools.validate_mission import load_mission_files, run

TEMPLATE_REPO = Path(__file__).resolve().parent.parent / "missions-repo-template"


def test_shipped_example_missions_are_valid(capsys):
    exit_code = run(
        [
            str(TEMPLATE_REPO / "active" / "OP-001-blackout"),
            str(TEMPLATE_REPO / "active" / "OP-002-iron-rain"),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0, output
    assert "OP-001" in output
    assert "INVALID" not in output


def test_shipped_mission_template_is_valid(capsys):
    exit_code = run([str(TEMPLATE_REPO / "templates" / "mission-template")])
    assert exit_code == 0, capsys.readouterr().out


def test_broken_mission_fails_with_exit_code_1(tmp_path, capsys):
    broken = tmp_path / "active" / "OP-090-broken"
    broken.mkdir(parents=True)
    (broken / "mission.json").write_text(
        json.dumps({"id": "OP-090", "name": "Broken"}), encoding="utf-8"
    )  # missing most required fields; no brief/objectives/slots at all

    exit_code = run([str(broken)])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "INVALID" in output
    assert "brief.md" in output


def test_nonexistent_directory_fails(tmp_path, capsys):
    exit_code = run([str(tmp_path / "does-not-exist")])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().out


def test_load_mission_files_reads_directory():
    files = load_mission_files(TEMPLATE_REPO / "active" / "OP-001-blackout")
    assert files.mission_json is not None
    assert files.directory == "active/OP-001-blackout"
