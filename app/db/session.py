from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

DATABASE_URL = settings.database_url

engine = create_async_engine(DATABASE_URL, future=True, echo=False)

if DATABASE_URL and DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
