import pytest

from app.database import Database
from app.database.models import Base


@pytest.fixture
async def database(tmp_path):
    """A real (SQLite-backed) database with the schema created."""
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()
