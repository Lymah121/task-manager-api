from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RefreshToken, User
from app.security import hash_refresh_token
from tests.conftest import PASSWORD


def _login(client: TestClient, user: User) -> dict:
    response = client.post(
        "/auth/login", data={"username": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


def test_login_returns_both_tokens(client: TestClient, user_a: User):
    body = _login(client, user_a)
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_refresh_token_is_stored_only_as_a_hash(client: TestClient, user_a: User, db: Session):
    raw = _login(client, user_a)["refresh_token"]
    stored = db.scalars(select(RefreshToken)).all()
    assert len(stored) == 1
    assert stored[0].token_hash != raw
    assert stored[0].token_hash == hash_refresh_token(raw)


def test_refresh_returns_a_new_working_access_token(client: TestClient, user_a: User):
    refresh = _login(client, user_a)["refresh_token"]

    response = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 200
    new = response.json()

    assert client.get(
        "/tasks", headers={"Authorization": f"Bearer {new['access_token']}"}
    ).status_code == 200


def test_refresh_rotates_the_token(client: TestClient, user_a: User):
    first = _login(client, user_a)["refresh_token"]
    second = client.post("/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
    assert second != first

    # The old one is now single-use-spent.
    assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401


def test_reusing_a_rotated_token_revokes_every_session(
    client: TestClient, user_a: User, db: Session
):
    """Theft detection.

    If a rotated token is presented again, either it is a replay or a thief and
    the real user are both holding it. We cannot tell which caller is genuine,
    so every session is burned and both must log in again.
    """
    stolen = _login(client, user_a)["refresh_token"]
    live = client.post("/auth/refresh", json={"refresh_token": stolen}).json()["refresh_token"]

    # The attacker replays the token they captured.
    response = client.post("/auth/refresh", json={"refresh_token": stolen})
    assert response.status_code == 401
    assert "reuse detected" in response.json()["detail"]

    # The legitimate user's current token is collateral damage, by design.
    assert client.post("/auth/refresh", json={"refresh_token": live}).status_code == 401

    db.expire_all()
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_expired_refresh_token_is_rejected(client: TestClient, user_a: User, db: Session):
    raw = _login(client, user_a)["refresh_token"]
    token = db.scalar(select(RefreshToken))
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert client.post("/auth/refresh", json={"refresh_token": raw}).status_code == 401


def test_unknown_refresh_token_is_rejected(client: TestClient):
    assert client.post("/auth/refresh", json={"refresh_token": "nope"}).status_code == 401


def test_logout_revokes_only_that_session(client: TestClient, user_a: User):
    first = _login(client, user_a)["refresh_token"]
    second = _login(client, user_a)["refresh_token"]

    assert client.post("/auth/logout", json={"refresh_token": first}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401
    # The other device stays logged in.
    assert client.post("/auth/refresh", json={"refresh_token": second}).status_code == 200


def test_logout_all_revokes_every_session(client: TestClient, user_a: User, headers_a):
    first = _login(client, user_a)["refresh_token"]
    second = _login(client, user_a)["refresh_token"]

    assert client.post("/auth/logout-all", headers=headers_a).status_code == 204
    for token in (first, second):
        assert client.post("/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_inactive_user_cannot_refresh(client: TestClient, user_a: User, db: Session):
    raw = _login(client, user_a)["refresh_token"]
    user_a.is_active = False
    db.commit()
    assert client.post("/auth/refresh", json={"refresh_token": raw}).status_code == 401
