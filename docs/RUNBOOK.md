# RUNBOOK — операционная памятка портала

> Актуально на 2026-09-04. Хостинг/доступы — в `docs/PROD-h215691.md`.

> **Про S3-хранилище в этом RUNBOOK (приписка 2026-10-02).** Все упоминания MinIO ниже
> относятся к **прод-ноде РБ-VPS**, где он стоит нативно и продолжает работать: PM2-процесс
> `pp-minio`, бинарники в `~/pp/opt/minio`, данные в `~/pp/var/minio`, бэкап — `~/pp/backups/<дата>/minio.tar.gz`.
> Локальная разработка и `docker compose` используют **RustFS** (сервисы `rustfs` + `s3init`)
> — образы MinIO удалены с Docker Hub, поэтому в compose их заменили. Приложение ходит в оба
> хранилища одним и тем же S3-клиентом boto3, так что для API разницы нет. Перенос dev-стека —
> `docs/MIGRATION.md`; общий канон — `ARCHITECTURE_PLAN.md` §10.

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

## TLS-сертификат Let's Encrypt (автопродление)

Публичный вход — `https://bublik.tail4fd7f3.ts.net/price/` через Tailscale Funnel;
TLS терминирует наш nginx (`infra/nginx/nginx.prod.conf`), а не Funnel. Сертификат —
Let's Encrypt для `bublik.tail4fd7f3.ts.net`, полученный командой `tailscale cert`:
ACME-челлендж Let's Encrypt к ts.net-домену выдаёт только сам Tailscale, отдельный
ACME-клиент (certbot) здесь не сработает.

Файлы сертификата лежат в `infra/nginx/certs/` (`fullchain.pem` + `privkey.pem`;
каталог в `.gitignore`) и смонтированы в nginx read-only.

### Как продлевается

Скрипт `infra/scripts/renew-cert.sh`:

1. просит у `tailscale cert` сертификат с `--min-validity 720h` (30 суток) — если до
   истечения больше 30 дней, Tailscale вернёт **тот же** сертификат и ничего не изменится;
   если меньше — выпустит новый;
2. проверяет, что новый сертификат валиден и покрывает домен (`openssl x509 -checkhost`);
3. подставляет новые файлы на место старых (`fullchain.pem` 644, `privkey.pem` 600);
4. перечитывает их в nginx через `nginx -s reload` — **без рестарта контейнера**
   и без разрыва соединений.

Шаг 1 идемпотентен, поэтому скрипт безопасно запускать хоть каждый час.

### Расписание на хосте (systemd-таймер, вне git)

Файлы юнитов лежат в репозитории (`infra/systemd/`), на хост копируются вручную:

```bash
sudo cp infra/systemd/price-cert-renew.service infra/systemd/price-cert-renew.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now price-cert-renew.timer
systemctl list-timers price-cert-renew.timer    # следующий запуск
journalctl -u price-cert-renew -n 50            # журнал прогонов
```

Таймер срабатывает раз в сутки около 04:17; продление случается только если до
истечения сертификата осталось меньше 30 суток. Путь к репозиторию в юнитах —
`/data/bublik/projects/price`; при переезде хоста поправить `WorkingDirectory`
и `ExecStart` в `price-cert-renew.service`.

### Ручная проверка и продление

```bash
sudo infra/scripts/renew-cert.sh        # или: make cert-renew
openssl x509 -in infra/nginx/certs/fullchain.pem -noout -dates
```

### Если сертификат всё-таки протух (сайт не открывается)

1. `sudo infra/scripts/renew-cert.sh` — выпустит новый (Tailscale выдаёт до 5 LE-сертификатов
   на домен в неделю; при исчерпании лимита нужен другой способ).
2. `docker exec pp-nginx nginx -t && docker exec pp-nginx nginx -s reload`.
3. Проверка, что сертификат изменился и валиден:

   ```bash
   openssl s_client -connect 127.0.0.1:443 -servername bublik.tail4fd7f3.ts.net </dev/null 2>/dev/null \
     | openssl x509 -noout -dates -issuer
   ```

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

## Доступы к GitHub: токен `gh` на dev-хосте

`gh` на этом хосте авторизован OAuth-токеном, который лежит **plaintext** в
`/root/.config/gh/hosts.yml`. Отдельного credential store (keyring/secret-service)
на headless-хосте нет, поэтому `gh auth login --insecure-storage` — единственный
вариант: без флага `gh` требует системное хранилище и завершается ошибкой.

Что уже сделано (2026-11-18):

- `/root/.config/gh` — права `700`, `hosts.yml` и `config.yml` — `600`, владелец `root`;
- токен не попадает в репозиторий и в историю git (проверено `git log --all -S` по префиксу `gho_`);
- в бэкапы (`infra/scripts/backup_db.sh`) уходит только БД — каталог `~/.config` не копируется;
- scopes — минимальные, которые `gh` требует сам (`repo`, `read:org`, `gist`); `gist` в
  `--scopes` убрать нельзя, это требование самого `gh`;
- git-операции идут **по SSH** (`git@github.com:bublikamun-code/price.git`,
  `gh auth status` → `Git operations protocol: ssh`), то есть токен нужен только
  для API `gh` — PR, CI-статусы, комментарии.

Правила: токен не печатать в чат и в логи, не коммитить, не класть в `.env`
(там он попадёт в `docker inspect` и в бэкапы контейнеров).

Ротация (нужна, если токен мог утечь):

1. GitHub → **Settings → Applications → Installed OAuth Apps → GitHub CLI →
   Revoke access** — это отзывает грант и все OAuth-токены CLI разом;
2. `gh auth login --web` — device flow: код подтверждает владелец в браузере;
3. `gh auth status` — проверить, что токен на месте и scopes те же;
4. `chmod 600 /root/.config/gh/hosts.yml` (login перезапишет файл).

## Локальный dev

- `make up` — стек (nginx :8080, web :3000, api :8000).
- `make test`, `make migrate`, см. `Makefile`.
- Проверка мобильного UI: Playwright-скриптом в контейнере web (chromium внутри
  контейнера; внешний URL: прокси `http://127.0.0.1:<порт>` внутри контейнера,
  Host должен быть `localhost` — Vite блокирует иные Host с 403).
