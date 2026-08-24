from app.bot.permissions import PermissionLevel, resolve_level


def level(**kwargs) -> PermissionLevel:
    defaults = dict(
        is_administrator=False,
        has_manage_guild=False,
        role_ids=(),
        staff_role_id=None,
        mission_maker_role_id=None,
    )
    defaults.update(kwargs)
    return resolve_level(**defaults)


def test_plain_member():
    assert level() is PermissionLevel.MEMBER


def test_administrator_outranks_everything():
    assert level(is_administrator=True) is PermissionLevel.ADMIN


def test_manage_guild_falls_back_to_staff():
    assert level(has_manage_guild=True) is PermissionLevel.STAFF


def test_configured_staff_role_grants_staff():
    assert level(role_ids=(10, 20), staff_role_id=20) is PermissionLevel.STAFF


def test_configured_maker_role_grants_mission_maker():
    assert level(role_ids=(30,), mission_maker_role_id=30) is PermissionLevel.MISSION_MAKER


def test_staff_role_wins_over_maker_role():
    assert (
        level(role_ids=(20, 30), staff_role_id=20, mission_maker_role_id=30)
        is PermissionLevel.STAFF
    )


def test_unrelated_roles_grant_nothing():
    assert (
        level(role_ids=(99,), staff_role_id=20, mission_maker_role_id=30)
        is PermissionLevel.MEMBER
    )


def test_level_ordering_used_by_checks():
    assert PermissionLevel.ADMIN > PermissionLevel.STAFF > PermissionLevel.MISSION_MAKER
    assert PermissionLevel.MISSION_MAKER > PermissionLevel.MEMBER > PermissionLevel.PUBLIC
