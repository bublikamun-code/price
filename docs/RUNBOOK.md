# RUNBOOK — операционная памятка портала

> Актуально на 2026-09-04. Хостинг/доступы — в `docs/PROD-h215691.md`.

## Быстрые действия

### Статус стека (с прод-ноды)

```bash
~/pp/bin/status.sh
```

### Остановка / запуск стека

```bash
~/pp/bin/stop-all.sh
~/pp/bin/start-all.sh        # поднимает PG (если надо) + pm2 startOrReload
```

### Ручной бэкап

```bash
~/pp/bin/backup-full.sh      # → ~/pp/backups/<YYYY-MM-DD>/
~/pp/bin/backup-offsite.sh   # копия на CRM-ноду (87.232.64.12)
```

### Восстановление БД из бэкапа

```bash
# на прод-ноде, стек остановлен (или хотя бы api/worker/beat)
~/pp/opt/pg/bin/pg_ctl -D ~/pp/var/pgdata stop -m fast
# развернуть в ЧИСТЫЙ кластер:
mv ~/pp/var/pgdata ~/pp/var/pgdata.bak
~/pp/opt/pg/bin/initdb -D ~/pp/var/pgdata -U price --encoding=UTF8
~/pp/opt/pg/bin/pg_ctl -D ~/pp/var/pgdata -l ~/pp/logs/pg.log start
~/pp/opt/pg/bin/pg_restore -h ~/pp/run -p 15432 -U price -d price_portal \
    --clean --if-exists ~/pp/backups/<дата>/price_portal.dump
# проверить, затем: ~/pp/bin/start-all.sh && rm -rf ~/pp/var/pgdata.bak
```

MinIO: остановить pp-minio, распаковать `minio.tar.gz` в `~/pp/var/`, запустить.

### Деплой новой версии

Только через `infra/scripts/deploy-prod.sh` из репозитория (см. ниже «Правило деплоя»).

## Правило деплоя (защита от отката дизайна)

Причина потери дизайна 02–03.09: `.output` собирался из рабочего дерева Mac и
раскладывался вручную; при переключении веток исходники мобильного дизайна были
утеряны, а на проде остался старый билд. Правила:

1. **Источник истины — git.** Всё, что деплоится, обязано быть закоммичено.
   Ключевые версии помечаются тегами (`v0.3-design-fixed`, `v0.4-mobile-fixed`).
2. **Билд только из clean clone** конкретного тега/коммита — делает
   `infra/scripts/deploy-prod.sh` (`git archive` во временную директорию).
3. **Запрещено** копировать `apps/web/.output` из рабочего дерева на прод.
4. После деплоя — автоматическая проверка health; при провале скрипт сам не
   откатывает (см. «Откат»).

### Откат на предыдущую версию

```bash
# на Mac, из корня репозитория:
TAG=v0.3-design-fixed ./infra/scripts/deploy-prod.sh   # любой тег/коммит
```

## Инциденты и диагностика

### Сайт отдаёт 302 → start.hoster.by

Сайт **выключен в панели хостинга** (https://vh163.hoster.by:1500/). Включить
сайт в панели → `~/pp/bin/start-all.sh`. Не путать с падением приложения.

### Стек упал и не поднимается

1. `~/pp/bin/status.sh` — кто жив.
2. Диск/квоты: `df -h`, `du -sh ~/pp/* | sort -rh | head`.
3. Лимит процессов тарифа (было 03.09 и 19.09): в логе PG `could not fork ... Resource
   temporarily unavailable`. Лимит **150 процессов+потоков**, обычное потребление
   стека ~92 → любой полный reload стека его пробивает. Лечится у хостера
   (просить nproc ≥ 300); временно — убить всё пользователем
   (`pkill -9 -u h215691` — из панели срабатывает даже при исчерпанной квоте:
   crond форкает под root, одиночная команда исполняется без доп. форка),
   затем канонический подъём (см. ниже).
4. **Канонический подъём — только так:** `set -a; source ~/pp/app/api/.env; set +a;
   bash ~/pp/bin/start-all.sh`. Без `source .env` MinIO поднимается со случайными
   root-кредами → `readyz` отдаёт `s3: fail`. PG — не PM2-процесс: если убит,
   поднимать `~/pp/opt/pg/bin/pg_ctl -D ~/pp/var/pgdata start` (start-all делает
   это сам, но только при своём запуске).
5. **OpenBLAS-цикл воркера/API**: `pp-worker`/`pp-api` падают при старте с
   `OpenBLAS blas_thread_init: pthread_create failed ... Aborted` — numpy (через
   `services/banner.py`, `services/manager_catalog.py`, `tasks/photo_zip.py`)
   пытается создать 48 потоков и упирается в лимит задач тарифа. Лечится
   `OPENBLAS_NUM_THREADS=1` (+ `OMP_NUM_THREADS=1`) в `env` pp-api/pp-worker/pp-beat
   в `~/pp/ecosystem.config.js` (добавлено 19.09; при пересоздании файла — вернуть).
6. Watchdog в cron держать ЗАКОММЕНТИРОВАННЫМ: его `start-all.sh` на каждой
   проверке при впритык занятой квоте порождает лавину перезапусков
   (19.09 из-за этого второй всплеск до ~7500 процессов в мониторе панели).

### Бэкапы не уходят на CRM

1. `tail ~/pp/logs/backup.log`, `tail ~/pp/logs/offsite.log`.
2. Ручной прогон `~/pp/bin/backup-offsite.sh`.
3. Ключ на прод-ноде `~/.ssh/pp_backup_ed25519` → h212005@87.232.64.12, проверка:
   `ssh -i ~/.ssh/pp_backup_ed25519 -o IdentitiesOnly=yes h212005@87.232.64.12 ls pp-backups-from-portal/`.

### Мониторинг с CRM слепой

**Обновлено 19.09:** `monitor_portal.sh` на CRM (v2) проверяет и `/readyz`
(db+redis+s3) — при живом, но нерабочем API пишет `DEGRADED ready=no` вместо
ложного `OK`. Состояние: `~/portal-monitor.log` на CRM-ноде.

### Логи PM2

Ротация — `pm2-logrotate` (max 20 МБ, 5 копий, установлен 19.09).
Старые всплески (OpenBLAS-спам 55 МБ) обрезаны, хвосты в `*.log.keep`.

## Локальный dev

- `make up` — стек (nginx :8080, web :3000, api :8000).
- `make test`, `make migrate`, см. `Makefile`.
- Проверка мобильного UI: Playwright-скриптом в контейнере web (chromium внутри
  контейнера; внешний URL: прокси `http://127.0.0.1:<порт>` внутри контейнера,
  Host должен быть `localhost` — Vite блокирует иные Host с 403).
