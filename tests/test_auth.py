import jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.routers.auth import INVALID_CREDENTIALS
from tests.conftest import PASSWORD

SIGNUP = {"email": "newuser@example.com", "password": "a-good-password"}


def _count_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User))


def test_signup_creates_user_and_returns_201(client: TestClient, db: Session):
    response = client.post("/auth/signup", json=SIGNUP)
    assert response.status_code == 201

    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["is_active"] is True
    assert isinstance(body["id"], int)

    assert db.scalar(select(User).where(User.email == "newuser@example.com")) is not None


def test_signup_normalises_and_rejects_duplicate_email_with_409(client: TestClient, db: Session):
    assert client.post("/auth/signup", json=SIGNUP).status_code == 201

    # Different casing and surrounding whitespace must still collide.
    duplicate = {"email": "  NewUser@Example.COM  ", "password": "another-password"}
    response = client.post("/auth/signup", json=duplicate)

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"
    assert _count_users(db) == 1


def test_signup_rejects_short_password_with_422(client: TestClient, db: Session):
    response = client.post("/auth/signup", json={"email": "x@example.com", "password": "short7c"})
    assert response.status_code == 422
    assert _count_users(db) == 0


def test_signup_rejects_invalid_email_with_422(client: TestClient, db: Session):
    payload = {"email": "not-an-email", "password": "long-enough"}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 422
    assert _count_users(db) == 0


def test_signup_never_exposes_password_and_stores_a_hash(client: TestClient, db: Session):
    body = client.post("/auth/signup", json=SIGNUP).json()
    assert "password" not in body
    assert "hashed_password" not in body

    user = db.scalar(select(User).where(User.email == SIGNUP["email"]))
    assert user.hashed_password != SIGNUP["password"]
    assert user.hashed_password.startswith("$argon2")


def test_login_returns_bearer_token_for_valid_credentials(client: TestClient, user_a: User):
    response = client.post(
        "/auth/login", data={"username": user_a.email, "password": PASSWORD}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"

    claims = jwt.decode(body["access_token"], settings.jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user_a.id)


def test_login_rejects_wrong_password_with_401(client: TestClient, user_a: User):
    response = client.post(
        "/auth/login", data={"username": user_a.email, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS


def test_login_rejects_unknown_email_with_401(client: TestClient):
    response = client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401
    # Identical to the wrong-password message: no user enumeration. Asserting
    # against the shared constant means any future divergence fails here.
    assert response.json()["detail"] == INVALID_CREDENTIALS
