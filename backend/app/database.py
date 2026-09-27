import sqlite3
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./telemetry.db"

engine = create_async_engine(DATABASE_URL, echo=False)


# 1. Custom SQLite function helper
def date_trunc_sqlite(granularity, timestamp):
    if timestamp is None:
        return None

    timestamp_str = str(timestamp).replace("T", " ")

    if granularity == "minute":
        return timestamp_str[:16] + ":00"
    elif granularity == "hour":
        return timestamp_str[:13] + ":00:00"
    elif granularity == "day":
        return timestamp_str[:10]

    return timestamp_str


# 2. Register event listener on engine sync target
@event.listens_for(engine.sync_engine, "connect")
def add_sqlite_functions(dbapi_connection, connection_record):
    raw_connection = getattr(dbapi_connection, "dbapi_connection", dbapi_connection)

    if hasattr(raw_connection, "_connection"):
        raw_connection = raw_connection._connection

    if isinstance(raw_connection, sqlite3.Connection):
        raw_connection.create_function(
            "date_trunc", 2, date_trunc_sqlite, deterministic=True
        )


async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)