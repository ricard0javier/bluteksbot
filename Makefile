.PHONY: install dev build test clean lint

ENV_NAME = bluteksbot
CONDA_RUN = conda run -n $(ENV_NAME) --no-capture-output
DEEP_AGENT_WORKSPACE = ./tmp

install:
	conda env create -f environment.yml || conda env update -f environment.yml --prune

dev:
	cp -n .env.example .env || true
	mkdir -p logs "${DEEP_AGENT_WORKSPACE}"
	docker compose up mongo litellm -d
	PYTHONPATH=. $(CONDA_RUN) python -m src.main

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

test:
	PYTHONPATH=. $(CONDA_RUN) pytest tests/ -v --tb=short

lint:
	$(CONDA_RUN) ruff check src/ tests/
	$(CONDA_RUN) mypy src/ --ignore-missing-imports

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf logs/* workspace/*
	docker compose down -v
