.PHONY: test lint quickstart-client

test:
	pytest -v

lint:
	ruff check app worker tests

quickstart-client:
	@echo "Quickstart checklist for new DocExtract client"
	@echo "1) cp .env.example .env"
	@echo "2) Set database_url, redis_url, anthropic_api_key"
	@echo "3) docker compose up -d db redis"
	@echo "4) uvicorn app.main:app --reload"
	@echo "5) POST /api/v1/reports/generate after first run"
