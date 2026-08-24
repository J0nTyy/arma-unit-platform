"""Player profile business logic.

A Player is the persistent unit profile behind a Discord account — Discord
is the primary identity (one profile per user per guild), Steam ID is an
optional linked identity, and profiles survive the Discord account leaving
so operational history stays intact.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database import Database
from app.database.models.player import (
    EXPERIENCE_LEVELS,
    QUALIFICATIONS,
    ROLE_PREFERENCES,
    MemberStatus,
    Player,
    PlayerQualification,
)
from app.database.repositories.players import PlayerRepository, QualificationRepository
from app.errors import DatabaseError, ValidationError
from app.services.guilds import validate_timezone

log = logging.getLogger(__name__)

_STEAM_ID_RE = re.compile(r"^\d{17}$")

# Fields members may set about themselves via /profile setup.
_SELF_SERVICE_FIELDS = {
    "timezone", "primary_role", "secondary_role", "arma_experience", "bio", "steam_id",
}


class PlayerService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_or_create(
        self,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        joined_at: datetime | None = None,
    ) -> Player:
        try:
            async with self._database.session() as session, session.begin():
                return await PlayerRepository(session).get_or_create(
                    guild_id, discord_user_id, display_name, joined_at
                )
        except IntegrityError as exc:  # concurrent creation — fetch the winner
            log.debug("Concurrent profile creation for %s", discord_user_id)
            async with self._database.session() as session:
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is not None:
                    return player
            raise DatabaseError("get_or_create failed") from exc
        except SQLAlchemyError as exc:
            raise DatabaseError("get_or_create failed") from exc

    async def get(self, guild_id: int, discord_user_id: int) -> Player | None:
        try:
            async with self._database.session() as session:
                return await PlayerRepository(session).get(guild_id, discord_user_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("get player failed") from exc

    async def update_preferences(
        self, guild_id: int, discord_user_id: int, display_name: str, **fields: object
    ) -> Player:
        """Self-service profile update; validates every field it accepts."""
        unknown = set(fields) - _SELF_SERVICE_FIELDS
        if unknown:
            raise ValueError(f"not self-service fields: {sorted(unknown)}")
        for key in ("primary_role", "secondary_role"):
            value = fields.get(key)
            if value is not None and value not in ROLE_PREFERENCES:
                raise ValidationError(
                    f"unknown role {value!r}", user_message="That's not a known role preference."
                )
        experience = fields.get("arma_experience")
        if experience is not None and experience not in EXPERIENCE_LEVELS:
            raise ValidationError(
                "unknown experience level", user_message="That's not a valid experience level."
            )
        if fields.get("timezone") is not None:
            fields["timezone"] = validate_timezone(str(fields["timezone"]))
        steam_id = fields.get("steam_id")
        if steam_id is not None:
            steam_id = str(steam_id).strip()
            if steam_id and not _STEAM_ID_RE.match(steam_id):
                raise ValidationError(
                    "bad steam id",
                    user_message=(
                        "That doesn't look like a SteamID64 — it's the 17-digit number "
                        "from your Steam profile URL (steamcommunity.com/profiles/<id>)."
                    ),
                )
            fields["steam_id"] = steam_id or None
        bio = fields.get("bio")
        if bio is not None:
            fields["bio"] = str(bio).strip()[:300] or None

        try:
            async with self._database.session() as session, session.begin():
                repository = PlayerRepository(session)
                player = await repository.get_or_create(guild_id, discord_user_id, display_name)
                for key, value in fields.items():
                    setattr(player, key, value)
                if player.primary_role and player.onboarding_status != "complete":
                    player.onboarding_status = "complete"
                await session.flush()
                await session.refresh(player)
                return player
        except SQLAlchemyError as exc:
            raise DatabaseError("update_preferences failed") from exc

    # --- staff operations -------------------------------------------------------

    async def set_status(self, guild_id: int, discord_user_id: int, status: str) -> Player:
        try:
            MemberStatus(status)
        except ValueError as exc:
            raise ValidationError(
                "bad status", user_message="Valid statuses: active, inactive, leave, retired."
            ) from exc
        return await self._staff_update(guild_id, discord_user_id, active_status=status)

    async def set_onboarding(self, guild_id: int, discord_user_id: int, status: str) -> Player:
        if status not in ("incomplete", "complete"):
            raise ValidationError("bad onboarding status")
        return await self._staff_update(guild_id, discord_user_id, onboarding_status=status)

    async def _staff_update(self, guild_id: int, discord_user_id: int, **fields: object) -> Player:
        try:
            async with self._database.session() as session, session.begin():
                repository = PlayerRepository(session)
                player = await repository.get(guild_id, discord_user_id)
                if player is None:
                    raise ValidationError(
                        "no profile",
                        user_message="That member has no unit profile yet.",
                    )
                for key, value in fields.items():
                    setattr(player, key, value)
                await session.flush()
                await session.refresh(player)
                return player
        except SQLAlchemyError as exc:
            raise DatabaseError("staff update failed") from exc

    async def mark_left(self, guild_id: int, discord_user_id: int) -> None:
        """Discord account left the server — keep everything, stamp the exit."""
        try:
            async with self._database.session() as session, session.begin():
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is not None:
                    player.left_at = datetime.now(timezone.utc)
        except SQLAlchemyError as exc:
            raise DatabaseError("mark_left failed") from exc

    async def search_members(
        self, guild_id: int, query: str | None = None, limit: int = 20
    ) -> list[Player]:
        try:
            async with self._database.session() as session:
                return await PlayerRepository(session).search(guild_id, query, limit)
        except SQLAlchemyError as exc:
            raise DatabaseError("member search failed") from exc

    # --- qualifications -----------------------------------------------------------

    async def qualifications(self, player_id: int) -> list[PlayerQualification]:
        try:
            async with self._database.session() as session:
                return await QualificationRepository(session).list_for(player_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("qualification list failed") from exc

    async def grant_qualification(
        self, guild_id: int, discord_user_id: int, qualification: str, granted_by: int
    ) -> PlayerQualification:
        if qualification not in QUALIFICATIONS:
            raise ValidationError(
                "unknown qualification", user_message="That qualification doesn't exist."
            )
        try:
            async with self._database.session() as session, session.begin():
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is None:
                    raise ValidationError(
                        "no profile", user_message="That member has no unit profile yet."
                    )
                repository = QualificationRepository(session)
                if await repository.get(player.id, qualification) is not None:
                    raise ValidationError(
                        "duplicate qualification",
                        user_message=(
                            f"They already hold {QUALIFICATIONS[qualification]}."
                        ),
                    )
                return await repository.grant(player.id, qualification, granted_by)
        except SQLAlchemyError as exc:
            raise DatabaseError("grant qualification failed") from exc

    async def revoke_qualification(
        self, guild_id: int, discord_user_id: int, qualification: str
    ) -> None:
        try:
            async with self._database.session() as session, session.begin():
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is None:
                    raise ValidationError(
                        "no profile", user_message="That member has no unit profile yet."
                    )
                repository = QualificationRepository(session)
                row = await repository.get(player.id, qualification)
                if row is None:
                    raise ValidationError(
                        "not held", user_message="They don't hold that qualification."
                    )
                await repository.revoke(row)
        except SQLAlchemyError as exc:
            raise DatabaseError("revoke qualification failed") from exc
