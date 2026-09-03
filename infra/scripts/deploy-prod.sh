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

log "rsync web/.output → $REMOTE"
rsync -az --delete \
  -e "$SSH" \
  apps/web/.output/ "$REMOTE:$PP/app/web/.output/"

log "миграции + перезапуск стека"
$SSH "$REMOTE" 'bash -s' <<EOF
set -e
source $PP/app/api/.env
cd $PP/app/api
$PP/venv/bin/alembic upgrade head
$PP/bin/start-all.sh
EOF

log "health-check"
sleep 3
TITLE="$(curl -s --max-time 15 "$SITE_URL/" | grep -oE '<title>[^<]*' | head -1 || true)"
[ -n "$TITLE" ] || die "сайт не отвечает после деплоя — смотри ~/pp/logs и pm2 на ноде"
log "OK: $TITLE"
log "деплой $REF завершён"
