# ============================================================
#  Makefile — удобные команды для разработки
#  Использование: make <target>
# ============================================================

DC = docker compose -f infra/docker-compose.yml --env-file .env
DC_PROD = docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml

.PHONY: help up down build logs ps api-shell web-shell migrate migrate-gen seed seed-catalog seed-all test lint fmt db-reset

help: ## показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## поднять все сервисы (dev, с хот-релоадом)
	$(DC) up -d

down: ## остановить все сервисы
	$(DC) down

build: ## пересобрать образы
	$(DC) build

logs: ## логи всех сервисов (tail)
	$(DC) logs -f --tail=100

ps: ## статус сервисов
	$(DC) ps

api-shell: ## shell в контейнере api
	$(DC) exec api bash

web-shell: ## shell в контейнере web
	$(DC) exec web sh

migrate: ## применить миграции Alembic
	$(DC) exec api alembic upgrade head

migrate-gen: ## создать миграцию: make migrate-gen m="create users"
	$(DC) exec api alembic revision --autogenerate -m "$(m)"

seed: ## наполнить тестовыми данными
	$(DC) exec api python -m app.scripts.seed

seed-catalog: ## загрузить каталог OptiBox Pro (тестовые цены)
	$(DC) exec api python -m app.scripts.seed_catalog

seed-all: seed seed-catalog ## менеджер + каталог OptiBox Pro

test: ## прогнать тесты api (тестовая БД на сервере db, авто-создание)
	@$(DC) exec -T db sh -c 'createdb "$${POSTGRES_DB}_test" 2>/dev/null || true'
	@$(DC) exec -T -e TEST_DB_URL="postgresql+asyncpg://$$( $(DC) exec -T db printenv POSTGRES_USER ):$$( $(DC) exec -T db printenv POSTGRES_PASSWORD )@db:5432/$$( $(DC) exec -T db printenv POSTGRES_DB )_test" api pytest -q

test-pattern: ## прогнать отдельный тест: make test-pattern T="tests/test_catalog.py -k discount"
	@$(DC) exec -T db sh -c 'createdb "$${POSTGRES_DB}_test" 2>/dev/null || true'
	@$(DC) exec -T -e TEST_DB_URL="postgresql+asyncpg://$$( $(DC) exec -T db printenv POSTGRES_USER ):$$( $(DC) exec -T db printenv POSTGRES_PASSWORD )@db:5432/$$( $(DC) exec -T db printenv POSTGRES_DB )_test" api pytest -v $(T)

lint: ## линтеры (api: ruff; web: eslint)
	$(DC) exec api ruff check .
	$(DC) exec web npm run lint

fmt: ## форматирование
	$(DC) exec api ruff format .
	$(DC) exec web npm run format

db-reset: ## пересоздать БД с нуля (ОСТОРОЖНО: удаляет данные)
	$(DC) down -v
	$(DC) up -d db redis minio
