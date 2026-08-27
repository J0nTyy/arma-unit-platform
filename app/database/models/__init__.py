# Import every model here so Base.metadata knows about all tables
# (Alembic autogenerate and test table creation depend on this).
from app.database.models.ai_usage import AIUsageDaily
from app.database.models.base import Base
from app.database.models.guild import CHANNEL_KINDS, GuildConfiguration
from app.database.models.knowledge import KnowledgeDocument
from app.database.models.memory import BotMemory
from app.database.models.mission import MissionIndexEntry
from app.database.models.player import (
    EXPERIENCE_LEVELS,
    QUALIFICATIONS,
    ROLE_PREFERENCES,
    AttendanceAudit,
    AttendanceRecord,
    FinalAttendance,
    MemberStatus,
    Player,
    PlayerQualification,
)
from app.database.models.operation import (
    ALLOWED_TRANSITIONS,
    AttendanceStatus,
    MissionPublication,
    Operation,
    OperationAttendance,
    OperationStatus,
)

__all__ = [
    "AIUsageDaily",
    "ALLOWED_TRANSITIONS",
    "AttendanceAudit",
    "AttendanceRecord",
    "AttendanceStatus",
    "Base",
    "BotMemory",
    "EXPERIENCE_LEVELS",
    "FinalAttendance",
    "MemberStatus",
    "Player",
    "PlayerQualification",
    "QUALIFICATIONS",
    "ROLE_PREFERENCES",
    "CHANNEL_KINDS",
    "GuildConfiguration",
    "KnowledgeDocument",
    "MissionIndexEntry",
    "MissionPublication",
    "Operation",
    "OperationAttendance",
    "OperationStatus",
]
