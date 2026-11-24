PYTHON ?= python

.PHONY: install dev test lint format

install:
	$(PYTHON) -m pip install -e ".[dev]"

dev:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .
