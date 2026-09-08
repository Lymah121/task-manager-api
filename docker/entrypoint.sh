#!/bin/sh
# Migrations run at boot so a fresh container converges the schema itself.
# 'exec' hands PID 1 to uvicorn so SIGTERM reaches it and shutdown is graceful.
set -e

echo "entrypoint: applying database migrations"
alembic upgrade head

echo "entrypoint: starting $*"
exec "$@"
