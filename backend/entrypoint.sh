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

# --forwarded-allow-ips: the only client this process ever sees is nginx on the
# compose network, which forwards the real address in X-Forwarded-For. Without
# this uvicorn trusts forwarded headers from 127.0.0.1 only, so request.client
# was always nginx's address and the login throttle (keyed on address + email)
# collapsed to per-email: five wrong guesses from ANYONE locked an account for
# everyone (review BE-07a). In development the backend port is bound to
# 127.0.0.1 (docker-compose.yml), so nothing but nginx and the host can spoof it.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --forwarded-allow-ips='*'
