.PHONY: help setup check test fmt clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

setup:   ## create the venv and install in editable mode
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e ".[dev]"

check:   ## lint and type check
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/mypy

test:    ## run the test suite
	.venv/bin/pytest

fmt:     ## format
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache
