.PHONY: help dev up down logs fixtures web test openapi types contract drop-v1

help:
	@echo "  make fixtures   generate local test data (no cloud account needed)"
	@echo "  make web        compile the typescript frontend"
	@echo "  make dev        fixtures + web + up"
	@echo "  make up         start the container"
	@echo "  make down       stop it"
	@echo "  make logs       follow logs"
	@echo "  make test       run backend tests"
	@echo "  make openapi    regenerate docs/openapi.json from the code"
	@echo "  make types      regenerate web/src/generated/api-types.ts from openapi.json"
	@echo "  make contract   check DATA-CONTRACT.md matches the canonical copy (R-10.1)"
	@echo "  make drop-v1    delete the v1 compatibility layer once devices write v2"

fixtures:
	python3 tools/generate_fixtures.py --out fixtures

web:
	cd web && npm install --silent && npm run build

dev: fixtures web up
	@echo ""
	@echo "  http://localhost:$${API_PORT:-8000}"
	@echo ""

up:
	@test -f .env || cp .env.example .env
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api

test:
	docker compose run --rm api pytest -q

openapi:
	docker compose run --rm -v $(PWD)/tools:/tools:ro -v $(PWD)/docs:/out \
	  api python /tools/dump_openapi.py /out/openapi.json

types: openapi
	cd web && npm install --silent && npm run types

# R-10.1: the device repository holds the canonical data contract.
contract:
	@diff -u ../_Rpi-Detector/docs/DATA-CONTRACT.md docs/DATA-CONTRACT.md \
	  && echo "DATA-CONTRACT.md in sync with the canonical copy" \
	  || (echo "DATA-CONTRACT.md has drifted from _Rpi-Detector"; exit 1)

# LEGACY-V1: removes itself. See tools/drop_v1.py
drop-v1:
	python3 tools/drop_v1.py
