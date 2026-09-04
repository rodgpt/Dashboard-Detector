.PHONY: help dev up down logs rebuild fixtures reindex test migrate upgrade psql openapi types contract

help:
	@echo "  make dev        frontend with hot reload (foreground). backend: make up"
	@echo "  make up         start db + backend + frontend containers"
	@echo "  make down       stop it"
	@echo "  make rebuild    rebuild images after dependency or Dockerfile changes"
	@echo "  make logs       follow logs (s=backend|frontend|db to narrow)"
	@echo "  make fixtures   generate local test data (no cloud account needed)"
	@echo "  make reindex    drop and rebuild the detection index from storage"
	@echo "  make test       run backend tests"
	@echo "  make migrate    generate an Alembic revision:  make migrate m=\"add x\""
	@echo "  make upgrade    apply migrations to head"
	@echo "  make psql       open a shell on the database"
	@echo "  make openapi    regenerate docs/openapi.json from the code"
	@echo "  make types      regenerate frontend/src/api/generated.ts from openapi.json"
	@echo "  make contract   check DATA-CONTRACT.md matches the canonical copy (R-10.1)"

fixtures:
	python3 tools/generate_fixtures.py --out fixtures

# `make dev` runs the FRONTEND with hot reload, in the foreground.
#
# The backend is not started here on purpose — it is brought up separately with
# `make up` (or `docker compose up -d --build`), because backend and interface
# work have different loops: the backend wants a rebuild and a restart, the
# interface wants a file save and a browser that already knows.
#
# Fixtures are generated only when missing. Regenerating takes ~40 s at the
# realistic event volume, which is not a price worth paying on every start of a
# UI session — `make fixtures` when you actually want a fresh tree, and
# `make reindex` afterwards, since new fixtures carry new event ids and the
# reconcile pass only ever adds.
dev:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	if [ ! -d fixtures/sites ]; then \
	  echo "no fixture tree yet — generating (~40 s)"; \
	  $(MAKE) --no-print-directory fixtures; \
	fi; \
	port=$${BACKEND_PORT:-8000}; \
	if ! curl -sf -m 2 "http://localhost:$$port/api/health" >/dev/null 2>&1; then \
	  echo ""; \
	  echo "  !! the backend is not answering on :$$port"; \
	  echo "     the interface will load and every API call will fail."; \
	  echo "     start it first:  make up"; \
	  echo ""; \
	fi; \
	if [ "$${OCEANKIND_COOKIE_SECURE:-true}" = "true" ]; then \
	  echo ""; \
	  echo "  !! OCEANKIND_COOKIE_SECURE=true, and the dev server is plain http."; \
	  echo "     a Secure cookie is not stored over http, so login will fail"; \
	  echo "     silently — the form posts and nothing happens."; \
	  echo "     set it to false in .env for local work."; \
	  echo ""; \
	fi; \
	echo "  frontend  http://localhost:5173   (hot reload, /api proxied to :$$port)"; \
	echo "  backend   http://localhost:$$port/api/health"; \
	echo ""; \
	cd frontend && { [ -d node_modules ] || npm install; } && npm run dev

up:
	@test -f .env || cp .env.example .env
	docker compose up --build -d
	@$(MAKE) --no-print-directory upgrade

down:
	docker compose down

rebuild:
	docker compose build --no-cache
	docker compose up -d
	@$(MAKE) --no-print-directory upgrade

logs:
	docker compose logs -f $(or $(s),backend)

# Drop every index row and rebuild from object storage (R-12.2).
#
# Two uses. It is the proof that the index is *derived* — if a rebuild cannot
# reproduce it, something existed only in Postgres. And it is the fix for the
# dev-loop papercut: `make fixtures` writes a whole new tree with new event ids,
# and the reconcile pass only ever *adds*, so the old rows linger forever and
# the detections list fills with events whose clips no longer exist.
reindex:
	docker compose run --rm backend python -c "\
from sqlmodel import Session, select; \
from app.core.database import engine; \
from app.core.models import DetectionEvent; \
from app.services import scheduler; \
db = Session(engine()); \
n = len(db.exec(select(DetectionEvent)).all()); \
[db.delete(r) for r in db.exec(select(DetectionEvent)).all()]; \
db.commit(); db.close(); \
print(f'dropped {n} rows'); \
[print(f\"  {r.site_id}: {r.newly_indexed} indexed, drift={r.drift}\") for r in scheduler.run_all(trigger='manual')]"

# RECONCILE_INTERVAL_HOURS=0 switches off the in-process reconcile timer. Tests
# drive the pass explicitly; a background one would make them non-deterministic
# and would reconcile against whatever fixture tree happened to be mounted.
test:
	docker compose run --rm \
	  -e OCEANKIND_DB_URL=sqlite:////tmp/test.db \
	  -e OCEANKIND_RECONCILE_INTERVAL_HOURS=0 \
	  backend pytest -q

# Schema changes go through Alembic. Never by hand, never by create_all.
migrate:
	@test -n "$(m)" || (echo 'usage: make migrate m="what changed"'; exit 1)
	docker compose run --rm backend alembic revision --autogenerate -m "$(m)"

upgrade:
	@docker compose run --rm backend alembic upgrade head

psql:
	docker compose exec db psql -U $${POSTGRES_USER:-oceankind} $${POSTGRES_DB:-oceankind}

openapi:
	docker compose run --rm -v $(PWD)/tools:/tools:ro -v $(PWD)/docs:/out \
	  backend python /tools/dump_openapi.py /out/openapi.json

types: openapi
	cd frontend && npm install --silent && npm run types

# R-10.1: the device repository holds the canonical data contract.
contract:
	@diff -u ../_Rpi-Detector/docs/DATA-CONTRACT.md docs/DATA-CONTRACT.md \
	  && echo "DATA-CONTRACT.md in sync with the canonical copy" \
	  || (echo "DATA-CONTRACT.md has drifted from _Rpi-Detector"; exit 1)

