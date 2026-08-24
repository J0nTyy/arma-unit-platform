"""Sheet export: row building from real services, via a fake sheets client."""

from datetime import datetime, timedelta, timezone

from app.database.models.operation import AttendanceStatus, OperationStatus
from app.database.models.player import FinalAttendance
from app.services import (
    AttendanceService,
    OperationService,
    PlayerService,
)
from app.services.sheets_export import SheetExportService


class FakeSheetsClient:
    url = "https://docs.google.com/spreadsheets/d/fake"

    def __init__(self):
        self.tabs: dict[str, tuple[list[str], list[list]]] = {}

    def replace_worksheet(self, title, headers, rows):
        self.tabs[title] = (headers, rows)
        return len(rows)


async def test_export_all_builds_every_tab(database):
    players = PlayerService(database)
    operations = OperationService(database)
    attendance = AttendanceService(database)

    await players.update_preferences(
        1, 100, "Kartikey", primary_role="medic", steam_id="76561198000000001"
    )
    await players.grant_qualification(1, 100, "medic", granted_by=999)

    operation = await operations.create_operation(
        guild_id=1, mission_id="OP-001", mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=1),
        tz_name="UTC", created_by=1,
    )
    await operations.mark_published(operation.id, channel_id=1, message_id=2)
    await operations.set_attendance(operation.id, 100, "Kartikey", AttendanceStatus.ATTENDING)
    await operations.transition(operation.id, OperationStatus.ACTIVE)
    await operations.transition(operation.id, OperationStatus.COMPLETED)
    await attendance.set_final_status(
        operation.id, 1, 100, "Kartikey", FinalAttendance.ATTENDED, changed_by=999
    )

    client = FakeSheetsClient()
    service = SheetExportService(database, client)
    results = await service.export_all(1)

    assert set(results) == {
        "Members", "Operations", "Attendance Log", "Certifications", "Missions"
    }
    headers, rows = client.tabs["Members"]
    assert headers[0] == "Name"
    member = rows[0]
    assert member[0] == "Kartikey"
    assert "Combat Medic" in member[10]
    assert member[11] == 1  # attended
    assert member[14] == "100%"

    _, operation_rows = client.tabs["Operations"]
    assert operation_rows[0][1] == "Blackout"
    assert operation_rows[0][6] == 1  # signed up
    assert operation_rows[0][7] == 1  # attended

    _, log_rows = client.tabs["Attendance Log"]
    assert log_rows[0][3] == "Kartikey" and log_rows[0][4] == "attended"

    _, cert_rows = client.tabs["Certifications"]
    assert cert_rows[0][0] == "Kartikey" and "Combat Medic" in cert_rows[0][1]


async def test_export_is_guild_scoped(database):
    players = PlayerService(database)
    await players.get_or_create(1, 100, "InGuild")
    await players.get_or_create(2, 200, "OtherGuild")

    client = FakeSheetsClient()
    await SheetExportService(database, client).export_all(1)
    _, rows = client.tabs["Members"]
    assert [row[0] for row in rows] == ["InGuild"]


def test_sheets_config(monkeypatch):
    from tests.test_config import ALL_ENV_VARS, REQUIRED
    from app.config import load_settings

    for var in ALL_ENV_VARS + ["GOOGLE_SHEETS_CREDENTIALS", "GOOGLE_SHEETS_SPREADSHEET_ID"]:
        monkeypatch.delenv(var, raising=False)
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    settings = load_settings(env_file=None)
    assert settings.sheets_configured is False
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS", '{"type":"service_account"}')
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "abc123")
    settings = load_settings(env_file=None)
    assert settings.sheets_configured is True