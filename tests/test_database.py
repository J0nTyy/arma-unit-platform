from app.database import Database
from app.database.repositories.guilds import GuildConfigurationRepository


async def test_ping_reports_healthy_database(database):
    assert await database.ping() is True


async def test_ping_reports_unreachable_database(tmp_path):
    broken = Database("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nope")
    try:
        assert await broken.ping() is False
    finally:
        await broken.dispose()


async def test_guild_repository_roundtrip(database):
    async with database.session() as session:
        async with session.begin():
            repository = GuildConfigurationRepository(session)
            created = await repository.upsert(guild_id=1234, guild_name="Test Unit")
        assert created.id is not None
        assert created.configured_at is not None

    async with database.session() as session:
        repository = GuildConfigurationRepository(session)
        fetched = await repository.get_by_guild_id(1234)
    assert fetched is not None
    assert fetched.guild_name == "Test Unit"


async def test_guild_repository_upsert_updates_in_place(database):
    async with database.session() as session:
        async with session.begin():
            repository = GuildConfigurationRepository(session)
            first = await repository.upsert(guild_id=42, guild_name="Old Name")
            first_id = first.id

    async with database.session() as session:
        async with session.begin():
            repository = GuildConfigurationRepository(session)
            second = await repository.upsert(guild_id=42, guild_name="New Name")

    assert second.id == first_id
    assert second.guild_name == "New Name"
