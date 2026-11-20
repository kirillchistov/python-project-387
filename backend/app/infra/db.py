"""Открытие SQLite и создание SQLAlchemy Engine.

Порт `backend/src/db.js`: тот же способ определения пути (переменная
окружения DATABASE_PATH, `:memory:` для тестов, иначе
`data/call-calendar.sqlite` относительно текущей директории).
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def resolve_database_path(database_path: str | None = None) -> str:
    value = database_path if database_path is not None else os.environ.get("DATABASE_PATH")
    if value:
        return value
    return str(Path("data", "call-calendar.sqlite").resolve())


def create_db_engine(database_path: str | None = None) -> Engine:
    path = resolve_database_path(database_path)

    if path == ":memory:":
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        # Несколько пуловых соединений на один файл (QueuePool) вместо
        # единственного синхронного соединения node:sqlite — даём SQLite
        # подождать снятия блокировки вместо мгновенной ошибки "database is locked".
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    return engine


def run_migrations(engine: Engine) -> None:
    """Прогоняет Alembic-миграции до head на уже созданном Engine.

    Порт императивного `migrate(db)` из db.js — здесь то же самое достигается
    версионированными миграциями (см. migrations/versions), но вызывается
    так же безусловно при старте приложения (идемпотентно: alembic_version
    хранит текущую ревизию и ничего не делает, если она уже head).
    """
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
