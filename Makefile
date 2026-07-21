.PHONY: up down logs test import-workflows

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api n8n

test:
	docker compose run --rm api pytest -q

import-workflows:
	docker compose exec n8n n8n import:workflow --separate --input=/workflows

