import sqlite3
from typing import cast

from sqlalchemy import Engine, event
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import ConnectionEventsTarget
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings


def create_database_engine(database_url: str | None = None) -> Engine:
    resolved_url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite:") else {}
    engine = sqlalchemy_create_engine(resolved_url, connect_args=connect_args)

    if engine.dialect.name == "sqlite":
        event.listen(cast(ConnectionEventsTarget, engine), "connect", enable_sqlite_foreign_keys)

    return engine


def enable_sqlite_foreign_keys(
    dbapi_connection: sqlite3.Connection, _connection_record: object
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
