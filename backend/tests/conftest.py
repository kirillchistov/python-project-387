import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.infra.db import create_db_engine, run_migrations
from app.infra.store import Store
from app.main import app, create_app


def migrated_engine(database_path: str = ":memory:") -> Engine:
    """SQLite (`:memory:` или файл) с применёнными миграциями до head.

    Прогоняет реальные Alembic-миграции (не CREATE TABLE «на скорую руку»),
    чтобы тесты ловили расхождения между кодом миграций и ожиданиями store.py.
    """
    engine = create_db_engine(database_path)
    run_migrations(engine)
    return engine


@pytest.fixture
def engine() -> Engine:
    return migrated_engine()


@pytest.fixture
def file_engine(tmp_path) -> Engine:
    """Файловая БД (как в проде — QueuePool, отдельное соединение на поток).

    В отличие от `:memory:` (StaticPool — одно общее соединение на всех),
    только файловый движок годится для тестов настоящей многопоточной
    конкурентности (см. test_create_booking_concurrent_same_slot_only_one_succeeds).
    """
    return migrated_engine(str(tmp_path / "test.sqlite"))


@pytest.fixture
def store(engine: Engine) -> Store:
    return Store(engine)


@pytest.fixture
def client() -> TestClient:
    """TestClient на пустое приложение из app.main (только /api/health)."""
    return TestClient(app)


@pytest.fixture
def api_client():
    """Свежий FastAPI-инстанс на изолированной `:memory:` БД для каждого теста.

    Как и `buildApp({ databasePath: ':memory:' })` в JS-тестах — приложение
    всегда сеет демо-владельца (owner@example.com / secret / slug kirill,
    см. app/infra/seed.py) при пустой БД, так что каждый тест начинает с уже
    существующим владельцем, а не с чистого листа.
    """
    test_app = create_app(database_path=":memory:")
    with TestClient(test_app) as c:
        yield c
