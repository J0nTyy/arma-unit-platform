"""The unit assistant's Discord interface.

Ways to talk to it:
- /ask <question> — anywhere
- @mention it with a question — in any channel
- reply to (quote) someone's message and @mention it — it reads the quoted
  message plus recent chat and answers in context
- reply to one of ITS OWN messages — continues the conversation, no mention
  needed

It never reacts to ordinary conversation it isn't addressed in. Reading
recent channel messages requires Discord's Message Content Intent.
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
_HISTORY_MESSAGES = 15      # recent channel messages given as context
_HISTORY_CHAR_BUDGET = 1600  # keep the token bill sane

# Answers may REFERENCE the staff role (<@&id>) so members know who to
# contact — render it without actually pinging the whole staff team.
_ANSWER_MENTIONS = discord.AllowedMentions(users=True, roles=False, everyone=False)


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


def _is_staff_channel(channel) -> bool:
    """A channel ordinary members can't see counts as a staff channel."""
    guild = getattr(channel, "guild", None)
    if guild is None:
        return False
    try:
        return not channel.permissions_for(guild.default_role).view_channel
    except AttributeError:
        return False


async def _recent_chat(channel, *, before=None, bot_user=None) -> str | None:
    """Compact transcript of the channel's recent messages (oldest first)."""
    try:
        lines: list[str] = []
        async for message in channel.history(limit=_HISTORY_MESSAGES, before=before):
            content = message.content.strip()
            if not content:
                continue
            author = "you (the assistant)" if message.author == bot_user else message.author.display_name
            lines.append(f"{author}: {content[:200]}")
        lines.reverse()
        transcript = "\n".join(lines)
        return transcript[-_HISTORY_CHAR_BUDGET:] if transcript else None
    except (discord.Forbidden, discord.HTTPException):
        return None


class AssistantCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    async def _answer(
        self,
        member: discord.Member,
        question: str,
        *,
        chat_context: str | None = None,
        quoted: str | None = None,
        staff_channel: bool = False,
        channel_id: int | None = None,
    ) -> str:
        service = self.bot.assistant_service
        if service is None:
            raise AINotConfiguredError()
        level = await member_level(self.bot, member)
        context = ToolContext(
            bot=self.bot, guild_id=member.guild.id, user_id=member.id, level=level
        )
        return await service.ask(
            context, question,
            chat_context=chat_context, quoted=quoted, staff_channel=staff_channel,
            style_examples=self.bot.style_sampler.sample(member.guild.id),
            channel_id=channel_id,
        )

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
        chat_context = await _recent_chat(interaction.channel, bot_user=self.bot.user)
        answer = await self._answer(
            interaction.user, question,
            chat_context=chat_context,
            staff_channel=_is_staff_channel(interaction.channel),
            channel_id=interaction.channel_id,
        )
        chunks = _chunk(f"> {question[:180]}\n\n{answer}")
        await interaction.followup.send(chunks[0], allowed_mentions=_ANSWER_MENTIONS)
        for chunk in chunks[1:3]:
            await interaction.followup.send(chunk, allowed_mentions=_ANSWER_MENTIONS)

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or self.bot.user is None:
            return

        # Every ordinary public-channel message teaches the assistant how
        # people here type (text only, no authors, in-memory).
        self.bot.style_sampler.consider(
            message.guild.id,
            message.content,
            author_is_bot=message.author.bot,
            staff_channel=_is_staff_channel(message.channel),
        )

        mentioned = self.bot.user in message.mentions
        quoted: str | None = None
        referenced: discord.Message | None = None
        if message.reference is not None:
            referenced = message.reference.resolved
            if referenced is None and message.reference.message_id:
                try:
                    referenced = await message.channel.fetch_message(
                        message.reference.message_id
                    )
                except discord.HTTPException:
                    referenced = None

        reply_to_bot = referenced is not None and referenced.author == self.bot.user
        # Triggers: an explicit @mention anywhere, OR replying to the bot's
        # own message (natural conversation continuation, no ping needed).
        if not mentioned and not reply_to_bot:
            return
        # A reply to a HUMAN whose ping list happens to include the bot only
        # counts when the bot is explicitly mentioned in the text itself.
        if referenced is not None and not reply_to_bot and f"{self.bot.user.id}" not in message.content:
            return

        question = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not question and not referenced:
            await message.reply(
                self.bot.messages.pick(
                    "ask_prompt",
                    fallback="Ask me anything about the unit — missions, ops, rules, getting started.",
                ),
                mention_author=False,
            )
            return
        if not isinstance(message.author, discord.Member):
            return

        if referenced is not None and referenced.content:
            if reply_to_bot:
                # Make the thread unmissable: their message ANSWERS this.
                quoted = (
                    f'YOUR OWN previous message: "{referenced.content[:400]}" '
                    "(their message below is a direct response to it — read it "
                    "in that thread, not as a standalone question)"
                )
            else:
                quoted = f'{referenced.author.display_name}: "{referenced.content[:400]}"'
            if not question:
                question = "What do you make of the quoted message?"

        try:
            async with message.channel.typing():
                chat_context = await _recent_chat(
                    message.channel, before=message, bot_user=self.bot.user
                )
                answer = await self._answer(
                    message.author, question,
                    chat_context=chat_context, quoted=quoted,
                    staff_channel=_is_staff_channel(message.channel),
                    channel_id=message.channel.id,
                )
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
            if first:
                await message.reply(
                    chunk, mention_author=False, allowed_mentions=_ANSWER_MENTIONS
                )
                first = False
            else:
                await message.channel.send(chunk, allowed_mentions=_ANSWER_MENTIONS)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(AssistantCog(bot))
