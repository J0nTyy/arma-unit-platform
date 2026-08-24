"""The /unit setup hub — the central configuration point for administrators.

One ephemeral panel: pick a setting from a dropdown, a matching picker
appears (channel select, role select, timezone list, or a modal). Includes
the guided "create recommended channels" flow with confirmation and
duplicate protection. Nobody ever types a channel ID.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.permissions import PermissionLevel, ensure_level
from app.bot.views.components import respond_error
from app.database.models.guild import CHANNEL_KINDS, GuildConfiguration

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

# general_channel_id has no default name on purpose: servers already have a
# general chat — admins point the bot at it instead of creating a new one.
DEFAULT_CHANNEL_NAMES = {
    "attendance_channel_id": "attendance",
    "briefing_channel_id": "operation-brief",
    "ask_channel_id": "ask-the-unit",
    "operations_channel_id": "operations",
    "missions_channel_id": "missions",
    "announcements_channel_id": "announcements",
    "operation_logs_channel_id": "operation-logs",
    "logs_channel_id": "bot-logs",
    "recruitment_channel_id": "recruitment",
    "aar_channel_id": "after-action-reports",
    "staff_channel_id": "staff",
}

# Set as the channel topic on creation so every channel explains itself.
DEFAULT_CHANNEL_TOPICS = {
    "attendance_channel_id": (
        "🪖 Operation signups. The latest operation's post lives here — answer with "
        "the Attend/Maybe/Can't buttons. Finished operations move to the logs."
    ),
    "briefing_channel_id": (
        "📖 Operation briefings and maps for the currently posted operations."
    ),
    "ask_channel_id": (
        "🤖 Ask the unit assistant anything — use /ask or just @mention the bot "
        "with your question. Missions, operations, rules, getting started."
    ),
    "operations_channel_id": "🎯 Operations chatter — planning, questions, coordination.",
    "missions_channel_id": (
        "🪖 The unit's mission library. Mission makers publish missions here via "
        "/mission publish; buttons open the brief and objectives."
    ),
    "announcements_channel_id": "📢 Unit-wide announcements from staff and the unit bot.",
    "operation_logs_channel_id": (
        "📦 Staff archive: completed and cancelled operations are logged here with "
        "their final attendance and briefing."
    ),
    "logs_channel_id": "🤖 Bot activity log for staff — sync results, errors, admin events.",
    "recruitment_channel_id": "📝 New-player information and recruitment.",
    "aar_channel_id": "📊 After-action reports for completed operations.",
    "staff_channel_id": "🛡️ Staff coordination and staff-only bot notifications.",
}
_PRIVATE_CHANNELS = {"logs_channel_id", "staff_channel_id", "operation_logs_channel_id"}
_READONLY_CHANNELS = {
    "operations_channel_id",
    "missions_channel_id",
    "announcements_channel_id",
    "aar_channel_id",
    "attendance_channel_id",
    "briefing_channel_id",
}

COMMON_TIMEZONES = (
    "UTC", "Asia/Kolkata", "Asia/Singapore", "Asia/Dubai", "Asia/Tokyo", "Asia/Shanghai",
    "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Warsaw", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Sao_Paulo", "Australia/Sydney", "Pacific/Auckland",
)

_ROLE_SETTINGS = (
    ("staff_role_id", "Staff role"),
    ("mission_maker_role_id", "Mission Maker role"),
    ("trainer_role_id", "Trainer role"),
)


def invite_url(application_id: int) -> str:
    """Invite link including permissions needed for channel management."""
    permissions = discord.Permissions(
        view_channel=True, send_messages=True, embed_links=True, attach_files=True,
        read_message_history=True, manage_channels=True, manage_roles=True,
        manage_messages=True, mention_everyone=True,
    )
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={application_id}&scope=bot%20applications.commands"
        f"&permissions={permissions.value}"
    )


def build_setup_embed(guild: discord.Guild, configuration: GuildConfiguration) -> discord.Embed:
    def channel(value: int | None) -> str:
        return f"<#{value}>" if value else "*not set*"

    def role(value: int | None) -> str:
        return f"<@&{value}>" if value else "*not set (falls back to Manage Server)*"

    embed = discord.Embed(
        title=f"⚙️ Unit Bot Setup — {configuration.unit_name or guild.name}",
        description="Pick a setting below to change it. Changes save immediately.",
        colour=embeds.BLURPLE,
    )
    channel_lines = [
        f"**{label}:** {channel(getattr(configuration, key))}" for key, label in CHANNEL_KINDS
    ]
    embed.add_field(name="Channels", value="\n".join(channel_lines), inline=False)
    embed.add_field(
        name="Roles",
        value="\n".join(
            f"**{label}:** {role(getattr(configuration, key))}" for key, label in _ROLE_SETTINGS
        ),
        inline=False,
    )
    embed.add_field(
        name="General",
        value=(
            f"**Unit name:** {configuration.unit_name or '*not set*'}\n"
            f"**Timezone:** {configuration.timezone or '⚠️ *not set — required for scheduling*'}\n"
            f"**Reminders:** {'✅ enabled' if configuration.reminders_enabled else '⛔ disabled'}\n"
            f"**Ambient chatter:** {'✅ enabled' if configuration.chatter_enabled else '⛔ disabled'}"
        ),
        inline=False,
    )
    return embed


class SetupHubView(discord.ui.View):
    def __init__(self, bot: "UnitBot", guild: discord.Guild) -> None:
        super().__init__(timeout=900)
        self._bot = bot
        self._guild = guild
        self._pending_setting: str | None = None
        self._picker: discord.ui.Item | None = None

        options = [
            discord.SelectOption(label=f"{label} channel", value=key, emoji="#️⃣")
            for key, label in CHANNEL_KINDS
        ]
        options += [
            discord.SelectOption(label=label, value=key, emoji="👤")
            for key, label in _ROLE_SETTINGS
        ]
        options += [
            discord.SelectOption(label="Timezone", value="timezone", emoji="🕒"),
            discord.SelectOption(label="Unit name", value="unit_name", emoji="🏷️"),
            discord.SelectOption(label="Reminders on/off", value="reminders_enabled", emoji="⏰"),
            discord.SelectOption(
                label="Ambient chatter on/off", value="chatter_enabled", emoji="💬",
                description="Occasional in-character messages in general",
            ),
        ]
        chooser = discord.ui.Select(
            placeholder="Choose a setting to change…", options=options, row=0
        )
        chooser.callback = self._on_choose  # type: ignore[method-assign]
        self._chooser = chooser
        self.add_item(chooser)

    # --- helpers ---------------------------------------------------------------

    async def _save(self, interaction: discord.Interaction, **fields: object) -> None:
        configuration = await self._bot.guild_service.update_settings(
            self._guild.id, self._guild.name, **fields
        )
        self._swap_picker(None)
        await interaction.response.edit_message(
            embed=build_setup_embed(self._guild, configuration), view=self
        )

    def _swap_picker(self, item: discord.ui.Item | None) -> None:
        if self._picker is not None:
            self.remove_item(self._picker)
        self._picker = item
        if item is not None:
            self.add_item(item)

    # --- setting chooser ---------------------------------------------------------

    async def _on_choose(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            setting = self._chooser.values[0]
            self._pending_setting = setting

            if setting == "unit_name":
                await interaction.response.send_modal(UnitNameModal(self))
                return

            picker: discord.ui.Item
            if setting.endswith("_channel_id"):
                picker = discord.ui.ChannelSelect(
                    channel_types=[discord.ChannelType.text],
                    placeholder="Select the channel…",
                    row=1,
                )
                picker.callback = self._on_channel_picked  # type: ignore[method-assign]
            elif setting.endswith("_role_id"):
                picker = discord.ui.RoleSelect(placeholder="Select the role…", row=1)
                picker.callback = self._on_role_picked  # type: ignore[method-assign]
            elif setting == "timezone":
                picker = discord.ui.Select(
                    placeholder="Select the unit timezone…",
                    options=[
                        discord.SelectOption(label=zone, value=zone) for zone in COMMON_TIMEZONES
                    ]
                    + [discord.SelectOption(label="Custom (type an IANA name)…", value="__custom__")],
                    row=1,
                )
                picker.callback = self._on_timezone_picked  # type: ignore[method-assign]
            else:  # reminders_enabled / chatter_enabled toggles
                noun = "reminders" if setting == "reminders_enabled" else "ambient chatter"
                picker = discord.ui.Select(
                    placeholder=f"{noun.title()}…",
                    options=[
                        discord.SelectOption(label=f"Enable {noun}", value="on", emoji="✅"),
                        discord.SelectOption(label=f"Disable {noun}", value="off", emoji="⛔"),
                    ],
                    row=1,
                )
                picker.callback = self._on_toggle_picked  # type: ignore[method-assign]

            self._swap_picker(picker)
            await interaction.response.edit_message(view=self)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_channel_picked(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            channel = self._picker.values[0]  # type: ignore[union-attr]
            await self._save(interaction, **{self._pending_setting: channel.id})  # type: ignore[arg-type]
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_role_picked(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            role = self._picker.values[0]  # type: ignore[union-attr]
            await self._save(interaction, **{self._pending_setting: role.id})  # type: ignore[arg-type]
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_timezone_picked(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            value = self._picker.values[0]  # type: ignore[union-attr]
            if value == "__custom__":
                await interaction.response.send_modal(TimezoneModal(self))
                return
            await self._save(interaction, timezone=value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_toggle_picked(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            value = self._picker.values[0] == "on"  # type: ignore[union-attr]
            await self._save(interaction, **{self._pending_setting: value})  # type: ignore[arg-type]
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    # --- bottom-row buttons --------------------------------------------------------

    @discord.ui.button(
        label="Create recommended channels", emoji="🏗️",
        style=discord.ButtonStyle.primary, row=3,
    )
    async def create_channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            configuration = await self._bot.guild_service.get_configuration(self._guild.id)
            plan = build_channel_plan(self._guild, configuration)
            if not plan.to_create and not plan.to_reuse:
                await interaction.response.send_message(
                    "✅ Every channel type is already configured — nothing to create.",
                    ephemeral=True,
                )
                return
            lines = []
            if plan.to_create:
                lines.append(
                    "**Will create:**\n" + "\n".join(f"• #{name}" for _, name in plan.to_create)
                )
            if plan.to_reuse:
                lines.append(
                    "**Will reuse existing:**\n"
                    + "\n".join(f"• <#{channel.id}>" for _, channel in plan.to_reuse)
                )
            lines.append("*Nothing is created until you confirm.*")
            await interaction.response.send_message(
                "🏗️ **Create recommended channels**\n\n" + "\n\n".join(lines),
                view=ConfirmChannelCreationView(self._bot, self._guild, plan),
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Done", emoji="✔️", style=discord.ButtonStyle.secondary, row=3)
    async def done(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="✅ Setup saved. Run `/unit setup` again any time.", view=None
        )


class UnitNameModal(discord.ui.Modal, title="Unit name"):
    name_input = discord.ui.TextInput(label="Unit name", max_length=100)

    def __init__(self, hub: SetupHubView) -> None:
        super().__init__()
        self._hub = hub

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self._hub._save(interaction, unit_name=self.name_input.value.strip())
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class TimezoneModal(discord.ui.Modal, title="Unit timezone"):
    tz_input = discord.ui.TextInput(
        label="IANA timezone name", placeholder="e.g. Asia/Kolkata", max_length=64
    )

    def __init__(self, hub: SetupHubView) -> None:
        super().__init__()
        self._hub = hub

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self._hub._save(interaction, timezone=self.tz_input.value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class ChannelPlan:
    def __init__(self) -> None:
        self.to_create: list[tuple[str, str]] = []  # (setting key, channel name)
        self.to_reuse: list[tuple[str, discord.TextChannel]] = []  # (setting key, channel)


def build_channel_plan(
    guild: discord.Guild, configuration: GuildConfiguration | None
) -> ChannelPlan:
    """Decide which channels to create vs reuse — never duplicates."""
    plan = ChannelPlan()
    for key, _label in CHANNEL_KINDS:
        if key not in DEFAULT_CHANNEL_NAMES:
            continue  # e.g. General: selected in setup, never auto-created
        configured_id = getattr(configuration, key, None) if configuration else None
        if configured_id and guild.get_channel(configured_id) is not None:
            continue  # already configured and the channel still exists
        name = DEFAULT_CHANNEL_NAMES[key]
        existing = discord.utils.get(guild.text_channels, name=name)
        if existing is not None:
            plan.to_reuse.append((key, existing))
        else:
            plan.to_create.append((key, name))
    return plan


class ConfirmChannelCreationView(discord.ui.View):
    def __init__(self, bot: "UnitBot", guild: discord.Guild, plan: ChannelPlan) -> None:
        super().__init__(timeout=300)
        self._bot = bot
        self._guild = guild
        self._plan = plan

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.ADMIN)
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild = self._guild
            configuration = await self._bot.guild_service.get_configuration(guild.id)
            staff_role = (
                guild.get_role(configuration.staff_role_id)
                if configuration and configuration.staff_role_id
                else None
            )
            me = guild.me
            updates: dict[str, int] = {key: channel.id for key, channel in self._plan.to_reuse}
            created: list[str] = []
            try:
                for key, name in self._plan.to_create:
                    overwrites: dict = {
                        me: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, embed_links=True,
                            attach_files=True, manage_messages=True, mention_everyone=True,
                        )
                    }
                    if key in _PRIVATE_CHANNELS:
                        overwrites[guild.default_role] = discord.PermissionOverwrite(
                            view_channel=False
                        )
                        if staff_role is not None:
                            overwrites[staff_role] = discord.PermissionOverwrite(
                                view_channel=True, send_messages=True
                            )
                    elif key in _READONLY_CHANNELS:
                        overwrites[guild.default_role] = discord.PermissionOverwrite(
                            send_messages=False
                        )
                    channel = await guild.create_text_channel(
                        name,
                        overwrites=overwrites,
                        topic=DEFAULT_CHANNEL_TOPICS.get(key),
                        reason="Unit bot setup",
                    )
                    updates[key] = channel.id
                    created.append(channel.mention)
            except discord.Forbidden:
                await interaction.followup.send(
                    "⚠️ I don't have permission to create channels. Re-invite me with the "
                    f"updated permissions, then try again:\n{invite_url(self._bot.settings.discord_application_id)}",
                    ephemeral=True,
                )
                return
            if updates:
                await self._bot.guild_service.update_settings(guild.id, guild.name, **updates)
            self.stop()
            summary = []
            if created:
                summary.append("Created: " + ", ".join(created))
            if self._plan.to_reuse:
                summary.append(
                    "Reused: " + ", ".join(f"<#{c.id}>" for _, c in self._plan.to_reuse)
                )
            await interaction.followup.send(
                "✅ Channels configured. " + " · ".join(summary), ephemeral=True
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Channel creation cancelled.", view=None)
