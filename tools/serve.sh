#!/usr/bin/env bash
# Static server for local development. Serves the repo root so that
# /src/ and /fixtures/ are both reachable from one origin.
set -e
PORT="${1:-8080}"
cd "$(dirname "$0")/.."
if [ ! -d fixtures ]; then
  echo "No fixtures/ yet. Building them first..."
  python3 tools/generate_fixtures.py
fi
echo
echo "  http://localhost:${PORT}/src/?data=/fixtures/"
echo
exec python3 -m http.server "$PORT"
