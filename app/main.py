from fastapi import FastAPI

app = FastAPI(
    title="Task Manager API",
    description="A multi-user task manager with JWT auth, built on FastAPI and PostgreSQL.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
