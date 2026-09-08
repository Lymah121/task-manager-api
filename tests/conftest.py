import os
from collections.abc import Generator
from datetime import timedelta

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import settings
from app.db import get_db
from app.main import app
from app.models import User
from app.security import create_access_token, hash_password

PASSWORD = "correct-horse-battery"
# Hashed once for the whole session: Argon2 is ~60ms by design, and paying that
# twice per test would add seconds to every run for no coverage.
HASHED_PASSWORD = hash_password(PASSWORD)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine() -> Generator[Engine]:
    eng = create_engine(settings.test_database_url, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema(engine: Engine) -> None:
    """Build the test schema by running the real migration chain.

    Not Base.metadata.create_all: that builds the schema from the models, which
    is the artefact the migrations are supposed to reproduce. Running Alembic
    makes the whole suite an integration test of the migrations for free.

    The schema drop first makes the run deterministic -- a crashed previous run
    can leave alembic_version pointing at a revision whose tables are gone, and
    'upgrade head' would then no-op into a confusing cascade of failures.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@pytest.fixture
def connection(engine: Engine) -> Generator[Connection]:
    conn = engine.connect()
    transaction = conn.begin()
    yield conn
    transaction.rollback()  # discards everything, including the endpoints' commits
    conn.close()


@pytest.fixture
def db(connection: Connection) -> Generator[Session]:
    # join_transaction_mode="create_savepoint" makes every Session.commit() a
    # SAVEPOINT release rather than a real COMMIT, so endpoint commits behave
    # normally (db.refresh sees server defaults) while the outer transaction
    # stays open for the fixture to roll back.
    session = sessionmaker(
        bind=connection,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )()
    yield session
    session.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient]:
    def override_get_db() -> Generator[Session]:
        # Deliberately no close(): the db fixture owns the lifecycle. Closing
        # here would hand the second request in a multi-request test a dead session.
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_user(db: Session, email: str) -> User:
    user = User(email=email, hashed_password=HASHED_PASSWORD)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_a(db: Session) -> User:
    return _make_user(db, "alice@example.com")


@pytest.fixture
def user_b(db: Session) -> User:
    return _make_user(db, "bob@example.com")


@pytest.fixture
def headers_a(user_a: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_a.id)}"}


@pytest.fixture
def headers_b(user_b: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_b.id)}"}


@pytest.fixture
def expired_headers(user_a: User) -> dict[str, str]:
    token = create_access_token(user_a.id, expires_delta=timedelta(minutes=-1))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def task_of_b(client: TestClient, headers_b: dict[str, str]) -> dict:
    response = client.post("/tasks", json={"title": "Bob's secret"}, headers=headers_b)
    assert response.status_code == 201
    return response.json()
