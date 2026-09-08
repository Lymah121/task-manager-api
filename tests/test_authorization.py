import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Task, User
from app.security import create_access_token

# Long enough to avoid PyJWT's InsecureKeyLengthWarning.
FOREIGN_SECRET = "a-different-secret-that-is-at-least-32-bytes-long"

PROTECTED = [
    ("get", "/tasks"),
    ("post", "/tasks"),
    ("get", "/tasks/1"),
    ("patch", "/tasks/1"),
    ("delete", "/tasks/1"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_tasks_require_authentication(client: TestClient, method: str, path: str):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", "", "a.b.c", "Bearer-inside-the-value"],
)
def test_malformed_token_is_rejected_401(client: TestClient, token: str):
    response = client.get("/tasks", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_tampered_signature_is_rejected_401(client: TestClient, user_a: User):
    token = create_access_token(user_a.id)
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    response = client.get("/tasks", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_token_signed_with_another_secret_is_rejected_401(client: TestClient, user_a: User):
    assert settings.jwt_secret != FOREIGN_SECRET
    foreign = jwt.encode({"sub": str(user_a.id)}, FOREIGN_SECRET, algorithm="HS256")

    response = client.get("/tasks", headers={"Authorization": f"Bearer {foreign}"})
    assert response.status_code == 401


def test_expired_token_is_rejected_401(client: TestClient, expired_headers: dict[str, str]):
    response = client.get("/tasks", headers=expired_headers)
    assert response.status_code == 401


def test_inactive_user_is_rejected_403(
    client: TestClient, headers_a: dict[str, str], user_a: User, db: Session
):
    """403 is reserved for 'I know who you are and you may not use this API'.

    Hiding a deactivated account gains nothing, so unlike cross-tenant access
    this one is honestly reported.
    """
    user_a.is_active = False
    db.commit()

    response = client.get("/tasks", headers=headers_a)
    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"


# --------------------------------------------------------------------------
# Cross-user isolation: the claim the README makes.
# --------------------------------------------------------------------------


def test_user_cannot_read_another_users_task(
    client: TestClient, headers_a: dict[str, str], task_of_b: dict
):
    response = client.get(f"/tasks/{task_of_b['id']}", headers=headers_a)
    assert response.status_code == 404
    assert "Bob's secret" not in response.text


def test_user_cannot_update_another_users_task(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str], task_of_b: dict
):
    response = client.patch(
        f"/tasks/{task_of_b['id']}", json={"title": "hijacked"}, headers=headers_a
    )
    assert response.status_code == 404

    # The 404 alone only proves the response was denied. Re-reading as the real
    # owner is what proves the write was denied too.
    still = client.get(f"/tasks/{task_of_b['id']}", headers=headers_b).json()
    assert still["title"] == "Bob's secret"
    assert still == task_of_b


def test_user_cannot_delete_another_users_task(
    client: TestClient,
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    task_of_b: dict,
    db: Session,
):
    response = client.delete(f"/tasks/{task_of_b['id']}", headers=headers_a)
    assert response.status_code == 404

    assert db.get(Task, task_of_b["id"]) is not None
    assert client.get(f"/tasks/{task_of_b['id']}", headers=headers_b).status_code == 200


def test_another_users_task_is_indistinguishable_from_a_nonexistent_one(
    client: TestClient, headers_a: dict[str, str], task_of_b: dict
):
    """Encodes the 404-over-403 decision.

    If someone later 'fixes' cross-tenant access to return 403, this fails with
    an obvious diff rather than silently reintroducing an enumeration oracle.
    """
    missing = client.get("/tasks/99999999", headers=headers_a)
    other = client.get(f"/tasks/{task_of_b['id']}", headers=headers_a)

    assert missing.status_code == other.status_code == 404
    assert missing.json() == other.json()
