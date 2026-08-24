"""Player profiles, qualifications, guild isolation, leave/rejoin."""

import pytest

from app.errors import ValidationError
from app.services import PlayerService


async def test_get_or_create_is_idempotent(database):
    service = PlayerService(database)
    first = await service.get_or_create(1, 100, "Kartikey")
    second = await service.get_or_create(1, 100, "Kartikey [42nd]")  # name refresh
    assert first.id == second.id
    assert second.display_name == "Kartikey [42nd]"
    assert second.onboarding_status == "incomplete"
    assert second.active_status == "active"


async def test_guild_isolation(database):
    service = PlayerService(database)
    in_guild_a = await service.get_or_create(1, 100, "Kartikey")
    in_guild_b = await service.get_or_create(2, 100, "Kartikey")
    assert in_guild_a.id != in_guild_b.id  # same person, two units, two profiles

    await service.update_preferences(1, 100, "Kartikey", primary_role="medic")
    assert (await service.get(2, 100)).primary_role is None


async def test_update_preferences_and_onboarding_completion(database):
    service = PlayerService(database)
    player = await service.update_preferences(
        1, 100, "Kartikey",
        primary_role="infantry", secondary_role="medic",
        arma_experience="new", timezone="Asia/Kolkata",
        bio="  Loves night ops.  ", steam_id="76561198000000001",
    )
    assert player.primary_role == "infantry"
    assert player.bio == "Loves night ops."
    assert player.steam_id == "76561198000000001"
    assert player.onboarding_status == "complete"  # primary role set


async def test_optional_fields_can_be_cleared(database):
    service = PlayerService(database)
    await service.update_preferences(1, 100, "K", bio="something", steam_id="76561198000000001")
    player = await service.update_preferences(1, 100, "K", bio="", steam_id="")
    assert player.bio is None
    assert player.steam_id is None


async def test_validation_rejections(database):
    service = PlayerService(database)
    with pytest.raises(ValidationError):
        await service.update_preferences(1, 100, "K", primary_role="space-marine")
    with pytest.raises(ValidationError):
        await service.update_preferences(1, 100, "K", steam_id="not-a-steam-id")
    with pytest.raises(ValidationError):
        await service.update_preferences(1, 100, "K", timezone="Nowhere/Land")
    with pytest.raises(ValueError):
        await service.update_preferences(1, 100, "K", active_status="retired")  # staff-only


async def test_member_status_is_staff_controlled(database):
    service = PlayerService(database)
    await service.get_or_create(1, 100, "K")
    player = await service.set_status(1, 100, "retired")
    assert player.active_status == "retired"
    with pytest.raises(ValidationError):
        await service.set_status(1, 100, "banned")


async def test_leave_preserves_profile_and_rejoin_clears_mark(database):
    service = PlayerService(database)
    created = await service.get_or_create(1, 100, "K")
    await service.mark_left(1, 100)
    departed = await service.get(1, 100)
    assert departed is not None and departed.left_at is not None
    assert departed.id == created.id  # nothing deleted

    rejoined = await service.get_or_create(1, 100, "K")
    assert rejoined.left_at is None
    assert rejoined.id == created.id


async def test_qualifications_grant_revoke_duplicate(database):
    service = PlayerService(database)
    await service.get_or_create(1, 100, "K")
    await service.grant_qualification(1, 100, "medic", granted_by=999)
    player = await service.get(1, 100)
    held = await service.qualifications(player.id)
    assert [q.qualification for q in held] == ["medic"]

    with pytest.raises(ValidationError, match="duplicate"):
        await service.grant_qualification(1, 100, "medic", granted_by=999)
    with pytest.raises(ValidationError):
        await service.grant_qualification(1, 100, "astronaut", granted_by=999)

    await service.revoke_qualification(1, 100, "medic")
    assert await service.qualifications(player.id) == []
    with pytest.raises(ValidationError):
        await service.revoke_qualification(1, 100, "medic")


async def test_member_search(database):
    service = PlayerService(database)
    await service.get_or_create(1, 100, "Kartikey")
    await service.get_or_create(1, 101, "Vector")
    await service.get_or_create(2, 102, "Kartik-other-guild")

    assert [p.display_name for p in await service.search_members(1, "kart")] == ["Kartikey"]
    assert len(await service.search_members(1)) == 2  # guild-scoped listing
