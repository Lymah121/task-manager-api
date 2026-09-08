# Task Manager API

A multi-user task manager built as a production-shaped backend service: JWT authentication,
owner-scoped CRUD, PostgreSQL with migrations, containerized, and deployed to AWS behind a
CI/CD pipeline.

## The problem

Most task-manager demos are single-user CRUD with no authorization story. The interesting
part of the problem is the one they skip: when many users share a database, *user A must
never be able to read or modify user B's rows* — not by guessing an ID, not by crafting a
request, not through any endpoint. Every route in this API is scoped to the authenticated
owner, and there is a test that proves it.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.14 |
| Framework | FastAPI |
| Database | PostgreSQL (SQLAlchemy + Alembic) |
| Auth | JWT bearer tokens, hashed passwords |
| Tests | pytest |
| Lint | ruff |
| Container | Docker (multi-stage, non-root) |
| CI | GitHub Actions |
| Hosting | AWS EC2 + RDS |

## Running it locally

```bash
git clone https://github.com/<you>/task-manager-api.git
cd task-manager-api

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload
```

Interactive API docs are then at `http://127.0.0.1:8000/docs`.

Run the checks the pipeline runs:

```bash
ruff check .
pytest -v
```

## Status

Scaffold stage — `/health` is live and covered by a test. Auth, the task domain, containers
and deployment land over the next few days; this section gets replaced by an architecture
diagram and the live URL as they do.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe. Returns `{"status": "ok"}`. |

## What I would do next

To be written once the service is deployed — the honest version, including what is
configured but not yet load-tested.
