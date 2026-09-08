from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Task, User


def test_create_task_sets_owner_and_defaults_to_todo(
    client: TestClient, headers_a: dict[str, str], user_a: User
):
    response = client.post("/tasks", json={"title": "Write the README"}, headers=headers_a)
    assert response.status_code == 201

    body = response.json()
    assert body["title"] == "Write the README"
    assert body["status"] == "todo"
    assert body["owner_id"] == user_a.id
    assert body["description"] is None
    # tz-aware, not a naive local timestamp
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None


def test_create_task_ignores_client_supplied_owner_id(
    client: TestClient, headers_a: dict[str, str], user_a: User, user_b: User
):
    """owner_id is absent from TaskCreate, so it cannot be mass-assigned."""
    response = client.post(
        "/tasks",
        json={"title": "Mine, not Bob's", "owner_id": user_b.id},
        headers=headers_a,
    )
    assert response.status_code == 201
    assert response.json()["owner_id"] == user_a.id


def test_create_task_rejects_invalid_status_with_422(
    client: TestClient, headers_a: dict[str, str]
):
    response = client.post(
        "/tasks", json={"title": "Bad status", "status": "urgent"}, headers=headers_a
    )
    assert response.status_code == 422


def test_list_tasks_returns_only_current_users_tasks(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
):
    for title in ("A1", "A2"):
        client.post("/tasks", json={"title": title}, headers=headers_a)
    for title in ("B1", "B2", "B3"):
        client.post("/tasks", json={"title": title}, headers=headers_b)

    a_titles = {t["title"] for t in client.get("/tasks", headers=headers_a).json()}
    b_titles = {t["title"] for t in client.get("/tasks", headers=headers_b).json()}

    assert a_titles == {"A1", "A2"}
    assert b_titles == {"B1", "B2", "B3"}


def test_get_own_task_returns_full_representation(
    client: TestClient, headers_a: dict[str, str]
):
    due = datetime.now(UTC) + timedelta(days=3)
    created = client.post(
        "/tasks",
        json={"title": "Ship it", "description": "before Sunday", "due_at": due.isoformat()},
        headers=headers_a,
    ).json()

    response = client.get(f"/tasks/{created['id']}", headers=headers_a)
    assert response.status_code == 200

    body = response.json()
    assert body["title"] == "Ship it"
    assert body["description"] == "before Sunday"
    # Compare instants, never raw strings: psycopg returns TIMESTAMPTZ in the
    # session timezone, which is not necessarily the one we sent.
    assert datetime.fromisoformat(body["due_at"]).astimezone(UTC) == due.astimezone(UTC)


def test_patch_updates_only_provided_fields(client: TestClient, headers_a: dict[str, str]):
    created = client.post(
        "/tasks",
        json={"title": "Original", "description": "keep me"},
        headers=headers_a,
    ).json()

    response = client.patch(
        f"/tasks/{created['id']}", json={"status": "done"}, headers=headers_a
    )
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "done"
    assert body["title"] == "Original"
    assert body["description"] == "keep me"


def test_delete_task_returns_204_and_row_is_gone(
    client: TestClient, headers_a: dict[str, str], db: Session
):
    task_id = client.post("/tasks", json={"title": "Temporary"}, headers=headers_a).json()["id"]

    response = client.delete(f"/tasks/{task_id}", headers=headers_a)
    assert response.status_code == 204
    assert response.content == b""

    assert client.get(f"/tasks/{task_id}", headers=headers_a).status_code == 404
    assert db.get(Task, task_id) is None
