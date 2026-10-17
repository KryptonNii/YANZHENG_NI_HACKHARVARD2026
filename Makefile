# TrialPilot — one entry point for humans, CI and judges.
#   make install   uv sync contracts engine api validation science; pnpm 9.15.9 install in web/
#   make dev       API factory on :8000 + Vite on :5173 (Ctrl-C stops both)
#   make test      pytest in every Python package, then vitest in web/
#   make lint      ruff on every Python package; mypy --strict on engine and contracts; gen --check; tsc
#   make seed      validate data/params, then python -m trialpilot_api.seed
#   make demo      seed + dev with DEMO_OFFLINE=1
#   make validate  cd validation && uv run tpv package
#   make science   uv run --project science python -m science.reproduce
#   make gen       regenerate contracts/schema and web/src/contracts.ts
#   make licenses  regenerate THIRD_PARTY.md
# Ports: make dev API_PORT=8001 WEB_PORT=5174
# Web package manager is pnpm 9.15.9 (web/package.json packageManager, api/Dockerfile).
# Override with PNPM=pnpm if that exact version is already on PATH.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY_PACKAGES := contracts engine api validation science
API_PORT ?= 8000
WEB_PORT ?= 5173
API_APP ?= trialpilot_api.main:create_app
UV ?= uv
PNPM ?= corepack pnpm@9.15.9

# Load .env if present (secrets never committed; see .env.example).
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help install dev api web test test-py test-web lint gen gen-check params seed demo validate validate-isolated science licenses clean

help:
	@sed -n '2,13p' Makefile | sed 's/^# //'

install:
	@for p in $(PY_PACKAGES); do echo ">> uv sync $$p"; $(UV) sync --frozen --project $$p; done
	@echo ">> pnpm 9.15.9 install (web)"
	$(PNPM) --dir web install --frozen-lockfile

dev:
	@api_pid=""; web_pid=""; \
	trap 'for pid in "$$api_pid" "$$web_pid"; do if [ -n "$$pid" ]; then kill "$$pid" 2>/dev/null || true; fi; done' INT TERM EXIT; \
	$(UV) run --project api uvicorn --factory $(API_APP) --host 127.0.0.1 --port $(API_PORT) --reload --reload-dir api --reload-dir engine & \
	api_pid=$$!; \
	WEB_PORT=$(WEB_PORT) API_TARGET=http://localhost:$(API_PORT) $(PNPM) --dir web dev --port $(WEB_PORT) --strictPort & \
	web_pid=$$!; \
	wait

api:
	$(UV) run --project api uvicorn --factory $(API_APP) --host 127.0.0.1 --port $(API_PORT) --reload

web:
	WEB_PORT=$(WEB_PORT) API_TARGET=http://localhost:$(API_PORT) $(PNPM) --dir web dev --port $(WEB_PORT) --strictPort

test: test-py test-web

test-py:
	@fail=""; for p in $(PY_PACKAGES); do \
	  echo ">> pytest $$p"; \
	  (cd $$p && $(UV) run pytest) || fail="$$fail $$p"; \
	done; \
	if [ -n "$$fail" ]; then echo "!! failing:$$fail"; exit 1; fi

test-web:
	$(PNPM) --dir web test

lint:
	@for p in $(PY_PACKAGES); do echo ">> ruff $$p"; (cd $$p && $(UV) run ruff check .); done
	@echo ">> mypy --strict engine"
	@(cd engine && $(UV) run mypy --strict trialpilot_engine)
	@echo ">> mypy --strict contracts"
	@(cd contracts && $(UV) run mypy --strict trialpilot_contracts gen.py)
	$(UV) run --project contracts python contracts/gen.py --check
	@echo ">> tsc web"
	$(PNPM) --dir web typecheck

gen:
	$(UV) run --project contracts python contracts/gen.py

gen-check:
	$(UV) run --project contracts python contracts/gen.py --check

params:
	$(UV) run --project contracts python -m trialpilot_contracts data/params

seed: params
	$(UV) run --project api python -m trialpilot_api.seed

demo: export DEMO_OFFLINE = 1
demo: seed dev

validate:
	cd validation && $(UV) run tpv package

# Preserves the timestamped evidence and clone, uses temporary databases and 8007/5180.
# Requires committed code, locked dependencies and an available Playwright Chromium.
validate-isolated:
	$(UV) run --frozen --project validation python validation/scripts/check_clean_clone.py --e2e

science:
	$(UV) run --project science python -m science.reproduce

clean:
	@echo "Validation and science evidence are retained. Only build output is cleaned."
	rm -rf web/dist

licenses:
	$(UV) run --project contracts python .github/scripts/third_party.py
