# Import every model here so Base.metadata knows about all tables
# (Alembic autogenerate and test table creation depend on this).
from app.database.models.base import Base
from app.database.models.guild import CHANNEL_KINDS, GuildConfiguration
from app.database.models.mission import MissionIndexEntry
from app.database.models.operation import (
    ALLOWED_TRANSITIONS,
    AttendanceStatus,
    MissionPublication,
    Operation,
    OperationAttendance,
    OperationStatus,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AttendanceStatus",
    "Base",
    "CHANNEL_KINDS",
    "GuildConfiguration",
    "MissionIndexEntry",
    "MissionPublication",
    "Operation",
    "OperationAttendance",
    "OperationStatus",
]
