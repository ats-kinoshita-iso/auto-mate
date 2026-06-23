.PHONY: sync lint format type test check run

sync:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run mypy src

test:
	uv run pytest

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run pytest

run:
	uv run automate --help
