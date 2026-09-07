# ============================================================
#  Makefile — удобные команды для разработки
#  Использование: make <target>
# ============================================================

DC = docker compose -f infra/docker-compose.yml --env-file .env
DC_PROD = docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file .env
DC_OBS = docker compose -f infra/docker-compose.yml -f infra/docker-compose.observability.yml --env-file .env
# Dev-режим фронтенда: базовый compose + override с Nuxt dev server (хот-релоад)
DC_WEB_DEV = docker compose -f infra/docker-compose.yml -f infra/docker-compose.web-dev.yml --env-file .env

.PHONY: help up down build logs ps api-shell web-shell web-dev web-prod alembic-check migrate migrate-gen seed seed-catalog seed-all test test-pattern lint fmt db-reset gen-jwt-keys obs-up obs-down test-e2e test-load test-load-import prod-up prod-down prod-logs prod-migrate gen-self-signed-certs backup backup-list ratelimit-reset

help: ## показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## поднять все сервисы (web — prod-сборка; api — dev с хот-релоадом)
	$(DC) up -d

web-dev: ## web в dev-режиме (Nuxt dev server + хот-релоад; нужен для make test-e2e)
	$(DC_WEB_DEV) up -d --build web
	@echo "web переключён в dev-режим (npm run dev). Вернуть prod: make web-prod"

web-prod: ## web в prod-режиме (собранный .output; режим по умолчанию)
	$(DC) up -d --build web
	@echo "web переключён в prod-режим (node .output/server/index.mjs)."

alembic-check: ## проверить дрейф моделей → миграций (аудит 2026-09-06 §3)
	$(DC) exec -T api alembic check

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
	@$(DC) exec -T db sh -c 'createdb -U "$${POSTGRES_USER}" "$${POSTGRES_DB}_test" 2>/dev/null || true'
	@$(DC) exec -T -e TEST_DB_URL="postgresql+asyncpg://$$( $(DC) exec -T db printenv POSTGRES_USER ):$$( $(DC) exec -T db printenv POSTGRES_PASSWORD )@db:5432/$$( $(DC) exec -T db printenv POSTGRES_DB )_test" api pytest -q

test-pattern: ## прогнать отдельный тест: make test-pattern T="tests/test_catalog.py -k discount"
	@$(DC) exec -T db sh -c 'createdb -U "$${POSTGRES_USER}" "$${POSTGRES_DB}_test" 2>/dev/null || true'
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

gen-jwt-keys: ## сгенерировать RSA-пару для JWT RS256, prod (§16 п.15)
	@if [ -e infra/jwt-keys/jwt_rsa.key ] || [ -e infra/jwt-keys/jwt_rsa.pub ]; then \
		echo "infra/jwt-keys/ уже содержит ключи — не перезаписываю (удалите вручную, если нужно)"; \
		exit 1; \
	fi
	mkdir -p infra/jwt-keys
	openssl genrsa -out infra/jwt-keys/jwt_rsa.key 2048
	openssl rsa -in infra/jwt-keys/jwt_rsa.key -pubout -out infra/jwt-keys/jwt_rsa.pub
	chmod 600 infra/jwt-keys/jwt_rsa.key
	chmod 644 infra/jwt-keys/jwt_rsa.pub
	@echo "Ключи созданы: infra/jwt-keys/jwt_rsa.key (600) и jwt_rsa.pub (644)"
	@echo "Prod монтирует их read-only в /jwt-keys (docker-compose.prod.yml); в git не коммитить (.gitignore)"

obs-up: ## observability-стек (§16 п.23): Prometheus+Grafana+Alertmanager+Pushgateway
	$(DC_OBS) up -d
	@echo ""
	@echo "Grafana:     http://localhost:3001  (admin/admin; анонимно — Viewer)"
	@echo "Prometheus:  http://localhost:9090"
	@echo "Alertmanager: http://localhost:9093"
	@echo "Pushgateway:  http://localhost:9091"

obs-down: ## остановить observability-стек (dev-сервисы не трогаем)
	$(DC_OBS) rm -sf prometheus grafana alertmanager pushgateway
	@$(DC) up -d api worker beat   # пересоздать без PUSHGATEWAY_URL (push выключен, fail-open)

test-e2e: ## E2E Playwright (§16 п.23) в контейнере web против dev-стека
	@$(DC) exec -T redis sh -c 'redis-cli --scan --pattern "LIMITS:*auth/login*" | xargs redis-cli DEL' >/dev/null 2>&1 || true
	@NGINX_IP=$$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' pp-nginx); \
	$(DC) exec -T web sh -c 'command -v chromium >/dev/null 2>&1 || apk add --no-cache chromium >/dev/null 2>&1'; \
	$(DC) exec -T -e E2E_BASE_URL="http://$${NGINX_IP}" -e PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium web npx playwright test

test-load: ## нагрузочный k6 (§16 п.23): каталог 100 RPS (нужен k6 на хосте)
	@if ! command -v k6 >/dev/null 2>&1; then echo "k6 не установлен: brew install k6 (см. infra/k6/README.md)"; exit 1; fi
	k6 run infra/k6/catalog.js

test-load-import: ## нагрузочный k6: импорт 50k строк (генерирует CSV)
	@if ! command -v k6 >/dev/null 2>&1; then echo "k6 не установлен: brew install k6 (см. infra/k6/README.md)"; exit 1; fi
	python3 infra/k6/gen_csv.py
	cd infra/k6 && k6 run import_50k.js

# ============================================================
#  PROD (Этап 11, §14/§16 п.24). См. docs/RUNBOOK.md
# ============================================================

prod-up: ## поднять prod-стек (перед этим: .env, gen-jwt-keys, сертификаты — см. RUNBOOK)
	$(DC_PROD) up -d
	@echo ""
	@echo "Предварительные шаги перед prod-up (если ещё не сделаны):"
	@echo "  1) .env с prod-значениями (ENV=prod, пароли, CORS_ORIGINS, TELEGRAM_*)"
	@echo "  2) make gen-jwt-keys            — RSA-пара для JWT RS256 (infra/jwt-keys/)"
	@echo "  3) сертификаты TLS infra/nginx/certs/{fullchain,privkey}.pem:"
	@echo "       make gen-self-signed-certs (тест) или Let's Encrypt (docs/RUNBOOK.md)"
	@echo "  4) make prod-migrate            — применить миграции"
	@echo "Дальше: make prod-logs, бэкапы — make backup (cron — docs/RUNBOOK.md)"

prod-down: ## остановить prod-стек (volumes не трогает)
	$(DC_PROD) down

prod-logs: ## логи prod-сервисов (tail)
	$(DC_PROD) logs -f --tail=100

prod-migrate: ## применить миграции Alembic в prod (с approve — см. §14/RUNBOOK)
	$(DC_PROD) run --rm api alembic upgrade head

gen-self-signed-certs: ## self-signed TLS-серт для localhost (проверка prod-конфига nginx)
	@if [ -e infra/nginx/certs/fullchain.pem ] || [ -e infra/nginx/certs/privkey.pem ]; then \
		echo "infra/nginx/certs/ уже содержит сертификаты — не перезаписываю (удалите вручную, если нужно)"; \
		exit 1; \
	fi
	mkdir -p infra/nginx/certs
	openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
		-subj "/CN=localhost" \
		-addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
		-keyout infra/nginx/certs/privkey.pem \
		-out infra/nginx/certs/fullchain.pem
	chmod 600 infra/nginx/certs/privkey.pem
	chmod 644 infra/nginx/certs/fullchain.pem
	@echo "Сертификаты созданы: infra/nginx/certs/fullchain.pem + privkey.pem (CN=localhost, SAN: DNS:localhost,IP:127.0.0.1)"
	@echo "Это self-signed — только для проверки конфига/локального теста; боевые — Let's Encrypt (docs/RUNBOOK.md). В git не коммитить (.gitignore)"

# ============================================================
#  Бэкапы (Этап 11, §14/§16 п.24): MVP — pg_dump -Fc + retention 30 д.
# ============================================================

backup: ## сделать бэкап БД (pg_dump -Fc → infra/backups/, retention 30 д.)
	infra/scripts/backup_db.sh

backup-list: ## список бэкапов
	@ls -lh infra/backups 2>/dev/null || echo "infra/backups/ пока пуст (make backup)"

restore-test: ## проверить свежий бэкап восстановлением во временную БД (§16 п.30)
	infra/scripts/restore_db.sh

ratelimit-reset: ## сбросить dev-счётчики rate-limit (login и др.) в Redis
	@$(DC) exec -T redis sh -c 'redis-cli --scan --pattern "LIMITS:*" | xargs redis-cli DEL' >/dev/null
	@echo "Счётчики rate-limit сброшены (только dev; в prod не применять)"
