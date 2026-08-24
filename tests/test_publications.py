from app.services import PublicationService


async def test_record_and_get_publication(database):
    service = PublicationService(database)
    publication = await service.record_publication(
        guild_id=1, mission_id="op-001", channel_id=10, message_id=20, published_by=99
    )
    assert publication.mission_id == "OP-001"  # normalized

    fetched = await service.get_publication(1, "OP-001")
    assert fetched is not None and fetched.message_id == 20
    # lookups are case-insensitive, guild-scoped
    assert await service.get_publication(1, "op-001") is not None
    assert await service.get_publication(2, "OP-001") is None


async def test_republish_same_channel_updates_message_reference(database):
    service = PublicationService(database)
    await service.record_publication(
        guild_id=1, mission_id="OP-001", channel_id=10, message_id=20, published_by=99
    )
    await service.record_publication(
        guild_id=1, mission_id="OP-001", channel_id=10, message_id=99, published_by=99
    )
    publications = await service.list_publications(1)
    assert len(publications) == 1  # no duplicate rows
    assert publications[0].message_id == 99


async def test_forget_publication(database):
    service = PublicationService(database)
    publication = await service.record_publication(
        guild_id=1, mission_id="OP-001", channel_id=10, message_id=20, published_by=99
    )
    await service.forget_publication(publication.id)
    assert await service.get_publication(1, "OP-001") is None
