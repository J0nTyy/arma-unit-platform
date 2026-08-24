# Import every model here so Base.metadata knows about all tables
# (Alembic autogenerate and test table creation depend on this).
from app.database.models.base import Base
from app.database.models.guild import GuildConfiguration
from app.database.models.mission import MissionIndexEntry

__all__ = ["Base", "GuildConfiguration", "MissionIndexEntry"]
