.PHONY: help setup up down migrate worker api web check test eval demo

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

setup:  ## install deps and copy env
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"
	test -f .env || cp .env.example .env

up:     ## start postgres
	docker compose up -d db

down:
	docker compose down

migrate:  ## apply migrations (idempotent)
	.venv/bin/python -m cli.migrate

worker:   ## run the job loop
	.venv/bin/python -m worker.run

api:
	.venv/bin/uvicorn api.main:app --reload --port 8000

web:
	cd web && npm run dev

check:   ## lint + types
	.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy .

test:
	.venv/bin/pytest -q

eval:    ## run golden set; MEETING=slug PROVIDER=x to narrow
	.venv/bin/python -m evals.run_eval $(if $(MEETING),--meeting $(MEETING)) $(if $(PROVIDER),--provider $(PROVIDER))

demo:    ## PHASE 1 GOAL: print the interleaved timeline
	.venv/bin/python -m cli.meetinglens timeline --audio $(AUDIO) --video $(VIDEO)
