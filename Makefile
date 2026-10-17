# TrialPilot — one entry point for humans, CI and judges.
#   make install   install every package that exists (uv + pnpm)
#   make dev       API on :8000 + web on :5173 (Ctrl-C stops both)
#   make test      every package's tests (folders that don't exist yet are skipped)
#   make lint      ruff on all Python packages, mypy --strict on engine, tsc on web
#   make seed      validate the parameter library, then seed the API database
#   make demo      seed + dev with DEMO_OFFLINE=1 (no network needed)
#   make validate  generate the GxP validation package (tpv package)
#   make gen       regenerate contracts/schema + web/src/contracts.ts
#   make licenses  regenerate THIRD_PARTY.md from installed package metadata
# Override ports/app: make dev API_PORT=8001 WEB_PORT=5174
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY_PACKAGES := contracts engine api validation science
API_PORT ?= 8000
WEB_PORT ?= 5173
API_APP ?= trialpilot_api.main:app
UV ?= uv
PNPM ?= pnpm

# Load .env if present (secrets never committed; see .env.example).
ifneq (,$(wildcard .env))
include .env
export
endif

# Packages that exist right now (have a pyproject.toml).
present = $(foreach p,$(PY_PACKAGES),$(if $(wildcard $(p)/pyproject.toml),$(p)))
has_web = $(wildcard web/package.json)

.PHONY: help install dev api web test test-py test-web lint gen gen-check params seed demo validate science licenses clean

help:
	@sed -n '2,11p' Makefile | sed 's/^# //'

install:
	@for p in $(present); do echo ">> uv sync $$p"; $(UV) sync --project $$p; done
	@if [ -n "$(has_web)" ]; then echo ">> pnpm install (web)"; $(PNPM) --dir web install; else echo "-- web/ not there yet, skipped"; fi

dev:
	@trap 'kill 0' INT TERM EXIT; \
	if [ -f api/pyproject.toml ]; then \
	  $(UV) run --project api uvicorn $(API_APP) --host 127.0.0.1 --port $(API_PORT) --reload --reload-dir api --reload-dir engine & \
	else echo "-- api/ not there yet, skipped"; fi; \
	if [ -n "$(has_web)" ]; then \
	  WEB_PORT=$(WEB_PORT) API_TARGET=http://localhost:$(API_PORT) $(PNPM) --dir web dev --port $(WEB_PORT) --strictPort & \
	else echo "-- web/ not there yet, skipped"; fi; \
	wait

api:
	$(UV) run --project api uvicorn $(API_APP) --host 127.0.0.1 --port $(API_PORT) --reload

web:
	WEB_PORT=$(WEB_PORT) API_TARGET=http://localhost:$(API_PORT) $(PNPM) --dir web dev --port $(WEB_PORT) --strictPort

test: test-py test-web

test-py:
	@fail=""; for p in $(present); do \
	  if [ -d $$p/tests ]; then echo ">> pytest $$p"; rc=0; (cd $$p && $(UV) run pytest) || rc=$$?; \
	    if [ $$rc -eq 5 ]; then echo "-- $$p: no tests collected yet"; elif [ $$rc -ne 0 ]; then fail="$$fail $$p"; fi; \
	  else echo "-- $$p has no tests/ yet, skipped"; fi; \
	done; \
	if [ -n "$$fail" ]; then echo "!! failing:$$fail"; exit 1; fi

test-web:
	@if [ -n "$(has_web)" ]; then $(PNPM) --dir web test; else echo "-- web/ not there yet, skipped"; fi

lint:
	@for p in $(present); do echo ">> ruff $$p"; (cd $$p && $(UV) run --with ruff ruff check .); done
	@if [ -f engine/pyproject.toml ]; then echo ">> mypy --strict engine"; (cd engine && $(UV) run --with mypy mypy --strict trialpilot_engine); fi
	@if [ -f contracts/pyproject.toml ]; then echo ">> mypy --strict contracts"; (cd contracts && $(UV) run mypy --strict trialpilot_contracts gen.py); fi
	@$(UV) run --project contracts python contracts/gen.py --check
	@if [ -n "$(has_web)" ]; then echo ">> tsc web"; $(PNPM) --dir web typecheck; fi

gen:
	$(UV) run --project contracts python contracts/gen.py

gen-check:
	$(UV) run --project contracts python contracts/gen.py --check

params:
	$(UV) run --project contracts python -m trialpilot_contracts data/params

seed: params
	@if [ -f api/trialpilot_api/seed.py ]; then $(UV) run --project api python -m trialpilot_api.seed; \
	else echo "-- api seed (api/trialpilot_api/seed.py) not there yet, skipped"; fi

demo: export DEMO_OFFLINE = 1
demo: seed dev

validate:
	@if [ -f validation/pyproject.toml ]; then cd validation && $(UV) run tpv package; \
	else echo "-- validation/ not there yet, skipped"; fi

science:
	@if [ -f science/pyproject.toml ]; then $(UV) run --project science python -m science.reproduce; \
	else echo "-- science/ not there yet, skipped"; fi

clean:
	rm -rf validation/out science/out web/dist

licenses:
	$(UV) run --project contracts python .github/scripts/third_party.py
