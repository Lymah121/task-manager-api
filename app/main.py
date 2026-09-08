from fastapi import FastAPI

from app.routers import auth, tasks

app = FastAPI(
    title="Task Manager API",
    description="A multi-user task manager with JWT auth, built on FastAPI and PostgreSQL.",
    version="0.2.0",
)

app.include_router(auth.router)
app.include_router(tasks.router)


# No Base.metadata.create_all here: the schema has exactly one source of truth,
# and that is the Alembic migration chain.
@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
