# Перенос стека на другую машину

Инструкция для ситуации «сегодня один сервер, завтра другой». Проверено на Debian-хосте
с Docker 29 и Compose 2.40.

---

## 0. Что изменилось и почему

**MinIO удалил свои образы с Docker Hub.** В пространстве имён `minio` больше нет
репозиториев `minio` и `mc` — API Docker Hub отдаёт на них 404. Поэтому
`docker compose up` падал ещё на этапе pull:

```
Error response from daemon: pull access denied for minio/mc,
repository does not exist or may require 'docker login'
```

Это происходило **на любой машине**, включая свежий клон репозитория. Локально
проект обходил это в `infra/scripts/docker-idle.sh`, поднимая стек без S3 —
то есть файловое хранилище на dev-машине не работало вовсе.

**Что сделано:**

| Было | Стало |
|---|---|
| `minio/minio:latest` | `rustfs/rustfs@sha256:8cc980…` |
| `minio/mc:latest` | `amazon/aws-cli@sha256:95f8d1…` |
| `postgres:16-alpine` | `postgres:16-alpine@sha256:721873…` |
| `redis:7-alpine` | `redis:7-alpine@sha256:858f00…` |
| `nginx:1.27-alpine` | `nginx:1.27-alpine@sha256:65645c…` |
| сервис `minio` | `rustfs` |
| сервис `createbuckets` | `s3init` |
| том `minio-data` | `rustfs-data` |

RustFS — S3-совместимый сервер, один бинарник. Приложение ходит в него тем же
boto3 с `signature_version="s3v4"` и `addressing_style="path"`, менять код не нужно.

Все образы запинены по digest: при переезде поднимется ровно та же версия, а не
«latest на момент запуска».

**Что НЕ изменилось:** прод на VPS использует нативный MinIO
(`docs/PROD-h215691.md`, порт 127.0.0.1:19000) — эти правки его не касаются.

---

## 1. Перенос на новую машину

### 1.1. Подготовить хост

Нужны `docker` (≥ 24) и `docker compose` v2. Проверка:

```bash
docker version && docker compose version
```

### 1.2. Забрать репозиторий

```bash
git clone https://github.com/bublikamun-code/price.git
cd price
```

### 1.3. Создать `.env`

```bash
cp .env.example .env
```

**Обязательно поправить `.env`:**

```bash
# если .env создан до 2026-10-01, там остался старый адрес — хранилище не поднимется
sed -i 's|^S3_ENDPOINT=.*|S3_ENDPOINT=http://rustfs:9000|' .env
```

Сгенерировать секреты вместо дефолтов:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(12)+'Aa1!')"  # → SEED_MANAGER_PASSWORD
```

Залить в `.env` поля `SECRET_KEY`, `SEED_MANAGER_EMAIL`, `SEED_MANAGER_PASSWORD`.

> `S3_EXTERNAL_ENDPOINT` должен совпадать с host-портом S3. Если меняете порт
> через `DEV_S3_PORT`, меняйте и `S3_EXTERNAL_ENDPOINT` — он подставляется в
> presigned URL, которые отдаются браузеру.

### 1.4. Порты

По умолчанию: db `5432`, redis `6379`, S3 `9000`, консоль S3 `9001`, nginx `8080`.
Если порт занят другим проектом — переопределите в `.env`
(`DEV_DB_PORT`, `DEV_REDIS_PORT`, `DEV_NGINX_PORT`, `DEV_S3_PORT`, `DEV_S3_CONSOLE_PORT`).

### 1.5. Поднять стек

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml --env-file .env ps
```

Ожидаемо: `pp-rustfs` — `healthy`, `pp-s3-init` — `Exited (0)` с логом
`бакеты S3 готовы`, `pp-api`, `pp-web`, `pp-nginx` — `Up`.

> На macOS используйте `make up` — скрипт `infra/scripts/docker-idle.sh`
> поднимает и гасит стек сам.

### 1.6. Проверка

```bash
# S3 доступен и бакеты созданы
docker run --rm --network price-portal_pp-net --entrypoint sh \
  -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin \
  amazon/aws-cli -c 'aws --endpoint-url http://rustfs:9000 s3 ls'

# приложение видит хранилище
docker compose -f infra/docker-compose.yml --env-file .env exec api \
  python -c "from app.services import storage; storage.check_connection(); print('S3 OK')"
```

---

## 2. Перенос данных между машинами

Стек поднят — теперь нужны сами данные.

### 2.1. База данных (обязательно)

```bash
# Сделать дамп (проверяет сигнатуру PGDMP, ротирует старые — по умолчанию 14 шт.)
infra/scripts/backup_db.sh

# Проверить дамп БЕЗ риска для данных: восстановление во временную БД (§16 п.30)
infra/scripts/restore_db.sh --test --yes

# Восстановить в рабочую БД — только когда точно нужно. Без --yes скрипт
# отказывается работать: операция сносит данные.
infra/scripts/restore_db.sh --yes
```

Бэкапы складываются в `infra/backups/` (каталок уже в `.gitignore`). Скрипт пишет
дамп во временный файл и публикует его только после проверки, поэтому оборванный
бэкап не выглядит рабочим.

### 2.2. Файлы S3 (фото, PDF, экспорты)

```bash
# Старая машина
docker run --rm --network price-portal_pp-net --entrypoint sh \
  -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin \
  amazon/aws-cli -c '
    for b in photos-series pdf-catalogs csv-exports tmp-uploads error-logs; do
      aws --endpoint-url http://rustfs:9000 s3 sync "s3://$b" "/tmp/$b";
    done'

# Новая машина — в обратную сторону
docker run --rm -v "$PWD/infra/backups/s3:/backup" --network price-portal_pp-net \
  --entrypoint sh -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin \
  amazon/aws-cli -c '
    for b in photos-series pdf-catalogs csv-exports tmp-uploads error-logs; do
      aws --endpoint-url http://rustfs:9000 s3 sync "/backup/$b" "s3://$b";
    done'
```

### 2.3. Что переносить не нужно

- Том `rustfs-data` — только что созданный, пустой
- `node_modules`, `.output`, `__pycache__` — пересобираются при сборке образов
- `.env` — на каждой машине свой (секреты могут различаться)

### 2.4. Что забыть легко

- **JWT-ключи.** В проде используется RS256: `infra/jwt-keys/jwt_rsa.key` и
  `jwt_rsa.pub` (генерируются `make gen-jwt-keys`, в git **не** коммитятся).
  Потеряете — все сессии станут невалидными, все пользователи разлогинятся.
- **`SECRET_KEY`** из `.env` — им подписываются курсоры пагинации v2. Смена
  значения ломает открытые ссылки на постраничные выборки.
- **Сертификаты TLS** (`infra/nginx/certs/`) — для прод-стека.

---

## 3. Проверка после переезда

```bash
# Тесты бэкенда (650 тестов, ~35 минут)
docker compose -f infra/docker-compose.yml --env-file .env exec -T db sh -c \
  'createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test" 2>/dev/null || true'
docker compose -f infra/docker-compose.yml --env-file .env exec -T \
  -e TEST_DB_URL="postgresql+asyncpg://price:price_secret@db:5432/price_portal_test" \
  api pytest -q

# Дрейф миграций
docker compose -f infra/docker-compose.yml --env-file .env exec -T api alembic check

# Веб
cd apps/web && npm ci && npm run typecheck && npm run lint && npm test
```

Прогнать **до** переключения продакшена, а не после.

---

## 4. Если образы не тянутся

Образы запинены по digest, поэтому «отвалится при обновлении» — уже невозможно.
Но если новый образ вообще не скачивается (закрытый реестр, прокси):

```bash
# На любой машине, где образ есть
docker save rustfs/rustfs@sha256:8cc980… | gzip > rustfs.tar.gz

# На целевой машине
gunzip -c rustfs.tar.gz | docker load
```

Digest в `docker-compose.yml` менять не нужно — загруженный образ подойдёт.