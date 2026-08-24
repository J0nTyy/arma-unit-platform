from app.services import GuildService


async def test_register_and_fetch_guild(database):
    service = GuildService(database)

    configuration = await service.register_guild(9001, "42nd Rifles")
    assert configuration.guild_id == 9001
    assert configuration.guild_name == "42nd Rifles"
    assert configuration.configured_at is not None

    fetched = await service.get_configuration(9001)
    assert fetched is not None
    assert fetched.guild_name == "42nd Rifles"


async def test_get_configuration_returns_none_for_unknown_guild(database):
    service = GuildService(database)
    assert await service.get_configuration(404404) is None
