#!/bin/bash
# deploy-prod.sh — воспроизводимый деплой портала из git на vh163.hoster.by.
#
# ПРИНЦИП (защита от отката дизайна): билд делается ТОЛЬКО из clean-дерева,
# полученного `git archive` указанного тега/коммита. Рабочее дерево деплою
# не участвует. Запрещено копировать apps/web/.output из рабочей копии.
#
# Использование:
#   infra/scripts/deploy-prod.sh              # origin/main
#   infra/scripts/deploy-prod.sh v0.4-mobile-fixed
#   infra/scripts/deploy-prod.sh <commit-sha>
#
# Что делает: fetch → git archive во временную директорию → build web
# (npm ci + nuxt build) → rsync api-исходников и web/.output на сервер
# (без .env, venv и мусора) → alembic upgrade → pm2 reload → health-check.
#
# Требования с Mac: node 20+ и npm (build фронта), rsync, ssh-ключ
# ~/.ssh/h215691_deploy.

set -euo pipefail

REF="${1:-origin/main}"
SSH="ssh -i $HOME/.ssh/h215691_deploy -o IdentitiesOnly=yes -o ConnectTimeout=15"
REMOTE="h215691@vh163.hoster.by"
PP="/var/www/h215691/data/pp"
SITE_URL="http://portal-87-232-64-23.nip.io"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log() { echo "[deploy $(date '+%H:%M:%S')] $*"; }
die() { echo "[deploy] ОШИБКА: $*" >&2; exit 1; }

cd "$REPO_ROOT"
git rev-parse --is-inside-work-tree >/dev/null || die "запускать из репозитория"

log "fetch origin (теги/ветки)"
git fetch origin --tags --prune

# Разрешаем ref → commit. Допускаем tag, branch, sha.
if COMMIT="$(git rev-parse --verify --quiet "$REF^{commit}")"; then
  :
elif COMMIT="$(git rev-parse --verify --quiet "origin/$REF^{commit}")"; then
  REF="origin/$REF"
else
  die "не найден ref: $REF"
fi
log "деплою $REF ($COMMIT)"

TMP="$(mktemp -d /tmp/pp-deploy.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
git archive "$COMMIT" | tar -x -C "$TMP"
[ -f "$TMP/apps/web/package-lock.json" ] || die "в $REF нет package-lock.json — фронт не соберётся воспроизводимо"

log "build web (npm ci + nuxt build) из чистого дерева"
cd "$TMP/apps/web"
npm ci --no-audit --no-fund
npm run build

log "rsync api-исходников → $REMOTE (без .env/venv/кэшей)"
cd "$TMP"
rsync -az --delete \
  --exclude '.env' --exclude '.env.*' --exclude 'venv/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' \
  --exclude 'celerybeat-schedule.db' \
  -e "$SSH" \
  apps/api/ "$REMOTE:$PP/app/api/"

log "бэкап текущего .output на сервере (защита от отката дизайна)"
$SSH "$REMOTE" "[ -d $PP/app/web/.output ] && rm -rf $PP/app/web/.output.prev && cp -a $PP/app/web/.output $PP/app/web/.output.prev && echo 'backup ok' || echo 'нет старого .output — бэкап пропущен'"

log "rsync web/.output → $REMOTE"
rsync -az --delete \
  -e "$SSH" \
  apps/web/.output/ "$REMOTE:$PP/app/web/.output/"

log "миграции + перезапуск стека"
$SSH "$REMOTE" 'bash -s' <<EOF || die "миграции/перезапуск завершились с ошибкой"
set -e
source $PP/app/api/.env
cd $PP/app/api
$PP/venv/bin/alembic upgrade head
$PP/bin/start-all.sh
EOF

log "health-check"
TITLE=""
for i in $(seq 1 20); do
  TITLE="$(curl -s --max-time 15 "$SITE_URL/" | grep -oE '<title>[^<]*' | head -1 || true)"
  [ -n "$TITLE" ] && break
  sleep 3
done
[ -n "$TITLE" ] || die "сайт не отвечает после деплоя — смотри ~/pp/logs и pm2 на ноде"
log "OK: $TITLE"

# Smoke-тест дизайна: отдаваемый HTML обязан содержать тёмные токены.
# Это маркер того, что задеплоен тёмный дизайн, а не светлый откат.
# PM2 reload грациозный: старый процесс может ещё отвечать первые секунды,
# а фронт-прокси хостера может кэшировать HTML — поэтому поллим до 4 минут
# и логируем КАЖДУЮ неудачную итерацию (код/размер/маркер), чтобы при провале
# было видно, ЧТО именно отвечало в окне ожидания.
SMOKED=0
for i in $(seq 1 80); do
  S_CODE="$(curl -s -o "$TMP/smoke.html" -w '%{http_code}' --max-time 15 "$SITE_URL/login" || echo 000)"
  S_MARK="$(grep -c -- '--color-canvas:10 10 10' "$TMP/smoke.html" 2>/dev/null || echo 0)"
  if [ "$S_MARK" -ge 1 ]; then
    SMOKED=1
    break
  fi
  log "smoke iter=$i: http=$S_CODE bytes=$(wc -c < "$TMP/smoke.html" 2>/dev/null || echo 0) marker=$S_MARK"
  sleep 3
done
if [ "$SMOKED" = "1" ]; then
  log "smoke: тёмная тема на месте"
else
  log "СМОК ПРОВАЛ: тёмный дизайн не обнаружен. Диагностика ответа /login:"
  BODY="$(curl -s --max-time 15 "$SITE_URL/login" || true)"
  echo "$BODY" | head -c 600
  echo
  log "color-canvas токены в ответе:"
  echo "$BODY" | grep -o -- '--color-canvas:[^;}]*' | sort -u | head -10 || true
  log "title ответа: $(echo "$BODY" | grep -oE '<title>[^<]*' | head -1 || true)"
  if [ "${DEPLOY_NO_ROLLBACK:-0}" = "1" ]; then
    die "DEPLOY_NO_ROLLBACK=1: новый .output ОСТАВЛЕН на сервере для ручной диагностики"
  fi
  log "откатываю .output и перезапускаю"
  $SSH "$REMOTE" "set -e; [ -d $PP/app/web/.output.prev ] && rm -rf $PP/app/web/.output && mv $PP/app/web/.output.prev $PP/app/web/.output && $PP/bin/start-all.sh && echo 'rollback ok'" \
    || die "не удалось выполнить авто-откат — верни .output вручную на сервере"
  die "деплой откачен: новый билд не содержал тёмную тему (светлый дизайн из git?)"
fi

log "деплой $REF завершён"
