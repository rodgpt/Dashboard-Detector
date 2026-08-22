.PHONY: help dev up down logs rebuild fixtures test migrate upgrade psql openapi types contract

help:
	@echo "  make dev        fixtures + db + backend + frontend, all three up"
	@echo "  make up         start the stack"
	@echo "  make down       stop it"
	@echo "  make rebuild    rebuild images after dependency or Dockerfile changes"
	@echo "  make logs       follow logs (s=backend|frontend|db to narrow)"
	@echo "  make fixtures   generate local test data (no cloud account needed)"
	@echo "  make test       run backend tests"
	@echo "  make migrate    generate an Alembic revision:  make migrate m=\"add x\""
	@echo "  make upgrade    apply migrations to head"
	@echo "  make psql       open a shell on the database"
	@echo "  make openapi    regenerate docs/openapi.json from the code"
	@echo "  make types      regenerate frontend/src/api/generated.ts from openapi.json"
	@echo "  make contract   check DATA-CONTRACT.md matches the canonical copy (R-10.1)"

fixtures:
	python3 tools/generate_fixtures.py --out fixtures

dev: fixtures up
	@echo ""
	@echo "  app       http://localhost:$${FRONTEND_PORT:-3000}"
	@echo "  backend   http://localhost:$${BACKEND_PORT:-8000}/api/health  (debugging only)"
	@echo ""
	@echo "  Use the app on :$${FRONTEND_PORT:-3000}. Hitting the backend directly"
	@echo "  bypasses nginx, which is a different origin and a different cookie."
	@echo ""

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

test:
	docker compose run --rm -e OCEANKIND_DB_URL=sqlite:////tmp/test.db backend pytest -q

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

