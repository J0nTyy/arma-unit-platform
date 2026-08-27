"""Role auto-creation planning for /unit setup (pure logic, no Discord)."""

from types import SimpleNamespace

from app.bot.views.setup import DEFAULT_ROLE_NAMES, build_role_plan


class FakeGuild:
    def __init__(self, roles=()):
        self.roles = list(roles)

    def get_role(self, role_id):
        return next((r for r in self.roles if r.id == role_id), None)


def role(role_id, name):
    return SimpleNamespace(id=role_id, name=name)


def test_fresh_guild_creates_all_roles():
    plan = build_role_plan(FakeGuild(), configuration=None)
    assert [name for _, name in plan.to_create] == list(DEFAULT_ROLE_NAMES.values())
    assert plan.to_reuse == []


def test_existing_roles_are_reused_case_insensitively():
    guild = FakeGuild([role(1, "staff"), role(2, "MISSION MAKER")])
    plan = build_role_plan(guild, configuration=None)
    reused = {key: r.id for key, r in plan.to_reuse}
    assert reused == {"staff_role_id": 1, "mission_maker_role_id": 2}
    assert {name for _, name in plan.to_create} == {"Trainer", "Developer"}


def test_configured_and_alive_roles_are_skipped():
    guild = FakeGuild([role(9, "Anything At All")])
    configuration = SimpleNamespace(
        staff_role_id=9, mission_maker_role_id=None,
        trainer_role_id=None, developer_role_id=None,
    )
    plan = build_role_plan(guild, configuration)
    keys = {key for key, _ in plan.to_create} | {key for key, _ in plan.to_reuse}
    assert "staff_role_id" not in keys  # configured + exists -> untouched
    assert len(plan.to_create) == 3


def test_configured_but_deleted_role_is_replanned():
    configuration = SimpleNamespace(
        staff_role_id=404, mission_maker_role_id=None,
        trainer_role_id=None, developer_role_id=None,
    )
    plan = build_role_plan(FakeGuild(), configuration)  # role 404 no longer exists
    assert ("staff_role_id", "Staff") in plan.to_create