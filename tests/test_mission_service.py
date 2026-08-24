import json

import pytest

from app.errors import (
    GitHubFileNotFoundError,
    GitHubUnavailableError,
    MissionNotFoundError,
)
from app.integrations.github import TreeEntry
from app.services.missions import MissionService
from tests.test_mission_schema import VALID_MISSION, VALID_OBJECTIVE

BRIEF = "# Operation Test\n\n## Situation\n\n" + "Enemy forces hold the town. " * 10


class FakeGitHubClient:
    """In-memory stand-in for GitHubClient (same interface, same errors)."""

    def __init__(self, files: dict[str, str], *, unavailable: bool = False) -> None:
        self.files = files
        self.unavailable = unavailable
        self.file_requests: list[str] = []

    @property
    def repository_url(self) -> str:
        return "https://github.com/unit/missions"

    async def get_tree(self) -> list[TreeEntry]:
        if self.unavailable:
            raise GitHubUnavailableError("repository unreachable")
        return [TreeEntry(path=path, type="blob", size=len(c)) for path, c in self.files.items()]

    async def get_file(self, path: str) -> str:
        if self.unavailable:
            raise GitHubUnavailableError("repository unreachable")
        self.file_requests.append(path)
        if path not in self.files:
            raise GitHubFileNotFoundError(path)
        return self.files[path]


def mission_files(
    mission_id: str = "OP-010",
    directory: str | None = None,
    *,
    include_brief: bool = True,
    **metadata_overrides,
) -> dict[str, str]:
    directory = directory or f"active/{mission_id}-test"
    metadata = {**VALID_MISSION, "id": mission_id, **metadata_overrides}
    files = {
        f"{directory}/mission.json": json.dumps(metadata),
        f"{directory}/objectives.json": json.dumps([VALID_OBJECTIVE]),
        f"{directory}/slots.json": json.dumps(
            {"categories": [{"name": "Infantry", "slots": [{"role": "Rifleman", "count": 10}]}]}
        ),
    }
    if include_brief:
        files[f"{directory}/brief.md"] = BRIEF
    return files


@pytest.fixture
def repo_files() -> dict[str, str]:
    return {
        **mission_files("OP-010", name="Operation Alpha", map="Altis", status="ready"),
        **mission_files(
            "OP-011",
            name="Operation Bravo",
            map="Livonia",
            mission_type="Defense",
            status="development",
            tags=["armor"],
        ),
    }


async def make_synced_service(database, files) -> tuple[MissionService, object]:
    github = FakeGitHubClient(files)
    service = MissionService(database, github)
    result = await service.sync()
    return service, result


async def test_sync_indexes_missions(database, repo_files):
    service, result = await make_synced_service(database, repo_files)
    assert result.found == 2
    assert result.indexed == 2
    assert result.valid == 2
    assert result.invalid == 0
    assert result.failures == ()

    entries = await service.list_missions()
    assert [e.mission_id for e in entries] == ["OP-010", "OP-011"]
    assert entries[0].is_valid


async def test_sync_flags_invalid_mission(database, repo_files):
    repo_files.update(mission_files("OP-012", include_brief=False))
    service, result = await make_synced_service(database, repo_files)
    assert result.invalid == 1
    entry = await service.get_mission("OP-012")
    assert entry is not None
    assert not entry.is_valid
    assert any("brief.md" in error for error in entry.validation_errors)


async def test_sync_reports_unparseable_mission(database, repo_files):
    repo_files["active/OP-099-broken/mission.json"] = "{broken json"
    service, result = await make_synced_service(database, repo_files)
    assert len(result.failures) == 1
    assert result.failures[0].directory == "active/OP-099-broken"
    assert await service.get_mission("OP-099") is None  # not indexed


async def test_sync_rejects_duplicate_mission_ids(database, repo_files):
    repo_files.update(mission_files("OP-010", directory="active/OP-010-copy"))
    service, result = await make_synced_service(database, repo_files)
    assert result.indexed == 2
    assert any("duplicate mission ID" in f.errors[0] for f in result.failures)


async def test_sync_removes_deleted_missions(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    github = FakeGitHubClient(mission_files("OP-010", name="Operation Alpha"))
    service_after = MissionService(database, github)
    result = await service_after.sync()
    assert result.removed == 1
    assert await service_after.get_mission("OP-011") is None


async def test_sync_propagates_unavailable_repository(database):
    service = MissionService(database, FakeGitHubClient({}, unavailable=True))
    with pytest.raises(GitHubUnavailableError):
        await service.sync()


async def test_index_survives_github_outage(database, repo_files):
    """Cached reads keep working when GitHub goes down after a sync."""
    github = FakeGitHubClient(repo_files)
    service = MissionService(database, github)
    await service.sync()
    github.unavailable = True
    entries = await service.list_missions()
    assert len(entries) == 2


async def test_list_filters(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    assert [e.mission_id for e in await service.list_missions(status="ready")] == ["OP-010"]
    assert [e.mission_id for e in await service.list_missions(map_name="livonia")] == ["OP-011"]
    assert [e.mission_id for e in await service.list_missions(mission_type="defense")] == ["OP-011"]


async def test_search_matches_name_map_and_tags(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    assert [e.mission_id for e in await service.search("bravo")] == ["OP-011"]
    assert [e.mission_id for e in await service.search("altis")] == ["OP-010"]
    assert [e.mission_id for e in await service.search("armor")] == ["OP-011"]
    assert await service.search("nonexistent") == []


async def test_get_mission_is_case_insensitive(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    entry = await service.get_mission("op-010")
    assert entry is not None and entry.mission_id == "OP-010"


async def test_get_brief_fetches_live_content(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    brief = await service.get_brief("OP-010")
    assert brief.startswith("# Operation Test")


async def test_get_brief_unknown_mission(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    with pytest.raises(MissionNotFoundError):
        await service.get_brief("OP-404")


async def test_get_objectives(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    objectives = await service.get_objectives("OP-010")
    assert objectives[0].id == "OBJ-01"


async def test_validate_mission_reports_current_state(database, repo_files):
    service, _ = await make_synced_service(database, repo_files)
    report = await service.validate_mission("OP-010")
    assert report.is_valid

    # Break the mission on "GitHub" after the sync — validate sees it live.
    github = FakeGitHubClient({k: v for k, v in repo_files.items() if not k.endswith("OP-010-test/brief.md")})
    stale_index_service = MissionService(database, github)
    report = await stale_index_service.validate_mission("OP-010")
    assert not report.is_valid


async def test_validate_unindexed_mission_found_by_directory_scan(database):
    files = mission_files("OP-050")
    service = MissionService(database, FakeGitHubClient(files))
    # No sync — the index is empty, so validate falls back to a live scan.
    report = await service.validate_mission("OP-050")
    assert report.is_valid


async def test_validate_unknown_mission_raises(database):
    service = MissionService(database, FakeGitHubClient({}))
    with pytest.raises(MissionNotFoundError):
        await service.validate_mission("OP-404")
