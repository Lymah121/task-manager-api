# Task Manager API

[![CI](https://github.com/Lymah121/task-manager-api/actions/workflows/ci.yml/badge.svg)](https://github.com/Lymah121/task-manager-api/actions/workflows/ci.yml)

A multi-user task manager built as a production-shaped backend service: JWT authentication,
owner-scoped CRUD, PostgreSQL with migrations, containerized, and deployed to AWS behind a
CI/CD pipeline.

## The problem

Most task-manager demos are single-user CRUD with no authorization story. The interesting
part of the problem is the one they skip: when many users share a database, *user A must
never be able to read or modify user B's rows* — not by guessing an ID, not by crafting a
request, not through any endpoint. Every route in this API is scoped to the authenticated
owner, and there is a test that proves it.

### 401, 403, 404 — and why cross-tenant access is a 404

Every `/tasks` route resolves through a single dependency, `get_owned_task`, which loads a task
with `WHERE id = :id AND owner_id = :current_user`. Ownership is part of the query, not a check
performed after the fact, so there is no code path that can load a row belonging to another user.

When that query returns nothing, the API responds **404 Not Found** — whether the task never
existed or belongs to someone else. Returning 403 for the second case would be more literally
descriptive, but it would also confirm that a given task ID exists. With sequential integer IDs,
an authenticated user could then walk the ID space and learn how many tasks other accounts hold
and when they were created, without ever reading one. 404 makes "not yours" and "doesn't exist"
indistinguishable from the outside.

| Code | Meaning | Trigger |
|---|---|---|
| **401** | I don't know who you are | token missing, malformed, tampered with, or expired |
| **403** | I know who you are, and you may not use this API | authenticated but deactivated account |
| **404** | As far as you are concerned, this row does not exist | task missing, *or* owned by someone else |

403 is reserved for the case where the client's identity *is* the problem and hiding it gains
nothing. 401 never says *which* of the four token failures occurred.

`tests/test_authorization.py` proves all of it, including that another user's task and a
nonexistent one return byte-identical responses, and that user B's task is unchanged after user A
attempts to `PATCH` and `DELETE` it — a 404 alone would only prove the *response* was denied.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.14 |
| Framework | FastAPI |
| Database | PostgreSQL 18 (SQLAlchemy 2.0 + Alembic) |
| Driver | psycopg 3 |
| Auth | JWT bearer tokens (PyJWT), Argon2 password hashing (pwdlib) |
| Tests | pytest, against real PostgreSQL |
| Lint | ruff |
| Container | Docker (multi-stage, non-root) |
| CI | GitHub Actions |
| Hosting | AWS EC2 + RDS |

## Running it locally

```bash
git clone https://github.com/Lymah121/task-manager-api.git
cd task-manager-api

cp .env.example .env
# then set JWT_SECRET:  python -c "import secrets; print(secrets.token_urlsafe(32))"

docker compose up -d db          # PostgreSQL 18 on host port 5433

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Interactive API docs are then at `http://127.0.0.1:8000/docs`. Log in through the **Authorize**
button — `/auth/login` uses the OAuth2 password flow, so the whole authenticated surface is
usable from the browser.

Run the checks the pipeline runs:

```bash
ruff check .
python -m pytest -v
```

> Commands use `python -m ...` throughout. That form is identical to the bare console scripts but
> immune to the antivirus policies that block `pytest.exe` / `alembic.exe` on some Windows setups.

**Port 5433, not 5432.** The Compose file publishes Postgres on 5433 so it cannot collide with a
native Postgres install on the host. CI uses 5432 inside the runner, where nothing else is bound.

**Tests need `taskmanager_test`.** It is created automatically the first time the `pgdata` volume
is initialised. If you added the init script to an existing volume, create it by hand with
`docker compose exec db createdb -U app taskmanager_test`.

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | — | Liveness probe. Returns `{"status": "ok"}`. |
| `POST` | `/auth/signup` | — | Create an account. `409` if the email is taken. |
| `POST` | `/auth/login` | — | OAuth2 password form → JWT access token. |
| `POST` | `/tasks` | Bearer | Create a task owned by the caller. |
| `GET` | `/tasks` | Bearer | List the caller's tasks. Supports `status`, `limit`, `offset`. |
| `GET` | `/tasks/{id}` | Bearer | Read one of the caller's tasks. |
| `PATCH` | `/tasks/{id}` | Bearer | Partial update; unset fields are left alone. |
| `DELETE` | `/tasks/{id}` | Bearer | Delete one of the caller's tasks. `204`. |

### Postman

`docs/task-manager-api.postman_collection.json` — import it, run **Auth → Signup** then
**Auth → Login**. The login request captures `access_token` into a collection variable, so every
request under **Tasks** is authenticated automatically. Each request carries assertions, so the
folder can be run end to end.

## Design notes

**Schema has one source of truth.** There is no `create_all()` at startup; the schema comes from
the Alembic chain, and the test suite builds its database by running those migrations rather than
from the models — so the migrations are themselves under test. `test_models_match_migrations`
fails the build if a model is edited without a matching revision.

**Task status is `VARCHAR` + `CHECK`, not a native Postgres enum.** Adding a value to a native
enum needs `ALTER TYPE ... ADD VALUE` and removing one is effectively impossible; Alembic
autogenerate detects neither. A CHECK constraint changes with ordinary, reversible DDL.

**Timestamps are `TIMESTAMPTZ`, defaulted by the database.** `server_default=func.now()` means
the database clock stamps rows, so a skewed application server cannot write out-of-order times.

**Duplicate signups are caught by the unique index**, not a pre-flight `SELECT` — checking first
is a TOCTOU race where two concurrent signups both see the email as free.

**Tests run against real PostgreSQL**, not SQLite. Each test executes inside a transaction bound
to a single connection and rolled back afterwards, so endpoint `commit()` calls behave normally
while tests stay isolated and fast.

## Status

Days 1 of 6 complete. Auth, the task domain, migrations and a 34-test suite are in; containerizing
the API, the AWS deployment and the live URL land next, and this section will be replaced by an
architecture diagram and the public endpoint as they do.

## What I would do next

To be written once the service is deployed — the honest version, including what is configured but
not yet load-tested.
