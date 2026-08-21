#!/bin/sh
# Migrate, then serve.
#
# Safe because the backend is pinned to one replica (see
# docs/SERVER-INFRASTRUCTURE.md — the in-process login throttle requires it), so
# there is no second instance to race the migration. If that ever changes,
# migrations move to a separate job and this script goes back to just serving.
set -e

echo "alembic: upgrading to head"
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
