"""The unit assistant's Discord interface.

One obvious command — /ask — plus natural @mention questions in the
configured ask channel. The bot never responds to ordinary conversation.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.permissions import PermissionLevel, member_level, require
from app.errors import AINotConfiguredError, AppError
from app.services.assistant_tools import ToolContext

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_MESSAGE_LIMIT = 1990


def _chunk(text: str) -> list[str]:
    chunks: list[str] = []
    while text:
        if len(text) <= _MESSAGE_LIMIT:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, _MESSAGE_LIMIT)
        cut = cut if cut > 200 else _MESSAGE_LIMIT
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks or ["…"]


class AssistantCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    async def _answer(self, member: discord.Member, question: str) -> str:
        service = self.bot.assistant_service
        if service is None:
            raise AINotConfiguredError()
        level = await member_level(self.bot, member)
        context = ToolContext(
            bot=self.bot, guild_id=member.guild.id, user_id=member.id, level=level
        )
        return await service.ask(context, question)

    @app_commands.command(
        name="ask",
        description="Ask the unit assistant about the unit, missions, operations or rules",
    )
    @app_commands.describe(question="Your question, in plain language")
    @app_commands.guild_only()
    @require(PermissionLevel.MEMBER)
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(thinking=True)
        assert isinstance(interaction.user, discord.Member)
        answer = await self._answer(interaction.user, question)
        chunks = _chunk(f"> {question[:180]}\n\n{answer}")
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:3]:
            await interaction.followup.send(chunk)

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        """@UnitBot <question> — only in the configured ask channel."""
        if message.author.bot or message.guild is None:
            return
        if self.bot.user is None or self.bot.user not in message.mentions:
            return
        configuration = await self.bot.guild_service.get_configuration(message.guild.id)
        if configuration is None or configuration.ask_channel_id != message.channel.id:
            return
        question = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not question:
            await message.reply(
                "Ask me anything about the unit — missions, operations, rules, "
                "getting started. You can also use `/ask`.",
                mention_author=False,
            )
            return
        if not isinstance(message.author, discord.Member):
            return
        try:
            async with message.channel.typing():
                answer = await self._answer(message.author, question)
        except AppError as error:
            await message.reply(f"⚠️ {error.user_message}", mention_author=False)
            return
        except Exception:  # noqa: BLE001 — listener errors must not go unanswered
            log.exception("Mention question failed")
            await message.reply(
                "⚠️ The unit assistant is temporarily unavailable. Please try again shortly.",
                mention_author=False,
            )
            return
        first = True
        for chunk in _chunk(answer)[:3]:
            await message.reply(chunk, mention_author=False) if first else await message.channel.send(chunk)
            first = False


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(AssistantCog(bot))
