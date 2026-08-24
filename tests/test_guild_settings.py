import pytest

from app.errors import ValidationError
from app.services import GuildService
from app.services.guilds import validate_timezone


async def test_update_channel_and_role_settings(database):
    service = GuildService(database)
    configuration = await service.update_settings(
        1, "Test Guild",
        operations_channel_id=111, missions_channel_id=222, staff_role_id=333,
    )
    assert configuration.operations_channel_id == 111
    assert configuration.missions_channel_id == 222
    assert configuration.staff_role_id == 333

    fetched = await service.get_configuration(1)
    assert fetched is not None
    assert fetched.operations_channel_id == 111
    # untouched settings stay unset
    assert fetched.logs_channel_id is None
    assert fetched.timezone is None


async def test_update_settings_registers_unknown_guild(database):
    service = GuildService(database)
    assert await service.get_configuration(42) is None
    await service.update_settings(42, "New Guild", timezone="Asia/Kolkata")
    fetched = await service.get_configuration(42)
    assert fetched is not None and fetched.timezone == "Asia/Kolkata"


async def test_invalid_timezone_rejected(database):
    service = GuildService(database)
    with pytest.raises(ValidationError):
        await service.update_settings(1, "Test Guild", timezone="Middle/Earth")


async def test_reminders_toggle(database):
    service = GuildService(database)
    configuration = await service.update_settings(1, "Test Guild")
    assert configuration.reminders_enabled is True  # default on
    configuration = await service.update_settings(1, "Test Guild", reminders_enabled=False)
    assert configuration.reminders_enabled is False


async def test_unknown_setting_rejected(database):
    service = GuildService(database)
    with pytest.raises(ValueError):
        await service.update_settings(1, "Test Guild", not_a_real_setting=999)


def test_validate_timezone_accepts_iana_names():
    assert validate_timezone(" Asia/Kolkata ") == "Asia/Kolkata"
    with pytest.raises(ValidationError):
        validate_timezone("IST")
