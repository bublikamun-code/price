#!/bin/bash
# deploy-prod.sh — воспроизводимый деплой портала из git на vh163.hoster.by.
#
# ПРИНЦИП (защита от отката дизайна): обычный деплой собирается только из
# clean-дерева, полученного `git archive` указанного тега/коммита. Для осознанной
# публикации проверенного незакоммиченного дерева существует явный режим
# DEPLOY_SOURCE=worktree: он сначала копирует исходники в отдельный временный
# каталог и собирает .output только там. Готовый .output из рабочей копии
# никогда не копируется на сервер.
#
# Использование:
#   infra/scripts/deploy-prod.sh              # origin/main
#   infra/scripts/deploy-prod.sh v0.4-mobile-fixed
#   infra/scripts/deploy-prod.sh <commit-sha>
#   DEPLOY_SOURCE=worktree infra/scripts/deploy-prod.sh
#
# Что делает: fetch/ref или worktree-снимок → build web
# (npm ci + nuxt build) → rsync api-исходников и web/.output на сервер
# (без .env, venv и мусора) → alembic upgrade → pm2 reload → health-check.
#
# Требования с Mac: node 20+ и npm (build фронта), rsync, ssh-ключ
# ~/.ssh/h215691_deploy.

set -euo pipefail

REF="${1:-origin/main}"
DEPLOY_SOURCE="${DEPLOY_SOURCE:-ref}"
SSH="ssh -i $HOME/.ssh/h215691_deploy -o IdentitiesOnly=yes -o ConnectTimeout=15"
REMOTE="h215691@vh163.hoster.by"
PP="/var/www/h215691/data/pp"
SITE_URL="https://portal-87-232-64-23.nip.io"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log() { echo "[deploy $(date '+%H:%M:%S')] $*"; }
die() { echo "[deploy] ОШИБКА: $*" >&2; exit 1; }

cd "$REPO_ROOT"
git rev-parse --is-inside-work-tree >/dev/null || die "запускать из репозитория"

TMP="$(mktemp -d /tmp/pp-deploy.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

case "$DEPLOY_SOURCE" in
  ref)
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
    git archive "$COMMIT" | tar -x -C "$TMP"
    ;;
  worktree)
    [ "$#" -eq 0 ] || die "DEPLOY_SOURCE=worktree не принимает ref; передаваемое состояние игнорируется"
    log "deploy source: явный снимок текущего worktree"
    git status --short
    mkdir -p "$TMP/apps"
    rsync -a --delete \
      --exclude '.git/' --exclude 'node_modules/' --exclude '.nuxt/' --exclude '.output/' \
      --exclude '.env' --exclude '.env.*' --exclude 'venv/' --exclude '__pycache__/' \
      --exclude '*.pyc' --exclude '.pytest_cache/' --exclude 'gui-audit-*/' \
      --exclude '*.png' --exclude '*.jpg' --exclude '*.jpeg' \
      "$REPO_ROOT/apps/api" "$TMP/apps/"
    rsync -a --delete \
      --exclude 'node_modules/' --exclude '.nuxt/' --exclude '.output/' \
      --exclude '.env' --exclude '.env.*' \
      "$REPO_ROOT/apps/web" "$TMP/apps/"
    ;;
  *)
    die "неизвестный DEPLOY_SOURCE: $DEPLOY_SOURCE (допустимо ref или worktree)"
    ;;
esac

[ -f "$TMP/apps/web/package-lock.json" ] || die "в источнике нет package-lock.json — фронт не соберётся воспроизводимо"

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

# Smoke-тест Trade-системы: новый light-first build обязан содержать реальные
# семантические токены, а не старый dark-only маркер. PM2 reload грациозный,
# поэтому edge-кэш и старый процесс коротко polls'им в течение 4 минут.
SMOKED=0
for i in $(seq 1 80); do
  S_CODE="$(curl -s -o "$TMP/smoke.html" -w '%{http_code}' --max-time 15 "$SITE_URL/login" || echo 000)"
  S_MARK="$(grep -Ec -- '--color-(action|background):(198 92 59|245 242 235)' "$TMP/smoke.html" 2>/dev/null || echo 0)"
  S_STRUCTURE="$(grep -Ec -- 'data-trade-frontend="record-v2"' "$TMP/smoke.html" 2>/dev/null || echo 0)"
  if [ "$S_MARK" -ge 1 ] && [ "$S_STRUCTURE" -ge 1 ]; then
    SMOKED=1
    break
  fi
  log "smoke iter=$i: http=$S_CODE bytes=$(wc -c < "$TMP/smoke.html" 2>/dev/null || echo 0) tokens=$S_MARK structure=$S_STRUCTURE"
  sleep 3
done
if [ "$SMOKED" = "1" ]; then
  log "smoke: Trade light-first tokens и record-v2 marker на месте"
else
  log "СМОК ПРОВАЛ: Trade-токены или record-v2 marker не обнаружены. Диагностика ответа /login:"
  BODY="$(curl -s --max-time 15 "$SITE_URL/login" || true)"
  echo "$BODY" | head -c 600
  echo
  log "semantic tokens в ответе:"
  echo "$BODY" | grep -oE -- '--color-(action|background):[^;}]*' | sort -u | head -10 || true
  log "title ответа: $(echo "$BODY" | grep -oE '<title>[^<]*' | head -1 || true)"
  if [ "${DEPLOY_NO_ROLLBACK:-0}" = "1" ]; then
    die "DEPLOY_NO_ROLLBACK=1: новый .output ОСТАВЛЕН на сервере для ручной диагностики"
  fi
  log "откатываю .output и перезапускаю"
  $SSH "$REMOTE" "set -e; [ -d $PP/app/web/.output.prev ] && rm -rf $PP/app/web/.output && mv $PP/app/web/.output.prev $PP/app/web/.output && $PP/bin/start-all.sh && echo 'rollback ok'" \
    || die "не удалось выполнить авто-откат — верни .output вручную на сервере"
  die "деплой откачен: новый билд не содержал Trade-токены или record-v2 marker"
fi

# Регресс-тест на подделку роли. auth_user не подписана: раньше SSR брал роль
# прямо из неё, поэтому cookie с role:ADMIN открывала менеджерские страницы.
# Теперь источник истины — /me по настоящей HttpOnly access-cookie, поэтому
# фейковый токен обязан увести на /login. Тест безопасный: подделанный токен
# не соответствует ни одной реальной сессии и никого не разлогинивает.
FORGED_USER='%7B%22id%22%3A%221%22%2C%22email%22%3A%22probe%40example.by%22%2C%22role%22%3A%22ADMIN%22%2C%22is_active%22%3Atrue%7D'
AUTH_HEADERS="$(curl -s -o /dev/null -D - -w '\n%{http_code}' --max-time 15 \
  -H "Cookie: access_token=bogus; auth_user=$FORGED_USER" "$SITE_URL/dashboard" | tr -d '\r' || true)"
AUTH_STATUS="$(echo "$AUTH_HEADERS" | tail -1)"
AUTH_LOC="$(echo "$AUTH_HEADERS" | grep -i '^location:' | head -1 || true)"
log "auth-forgery probe: http=$AUTH_STATUS $AUTH_LOC"
case "$AUTH_STATUS $AUTH_LOC" in
  2*) die "ДЫРА: подделанная auth_user с role:ADMIN открыла /dashboard (http=$AUTH_STATUS). Откат обязателен." ;;
  3*login*|*login*3*) log "OK: подделанная роль не дала доступ — редирект на /login" ;;
  *) log "ВНИМАНИЕ: неожиданный ответ на поддельную сессию (http=$AUTH_STATUS $AUTH_LOC) — проверьте вручную" ;;
esac

# Заголовки безопасности на HTML: без них ни CSP, ни запрет фрейминга не
# работают. Проверяем то, что обязаны ставить приложение: прод — PM2 за edge
# nginx хостера, конфигурации nginx из репозитория на сервере нет.
for H in content-security-policy x-frame-options x-content-type-options referrer-policy; do
  curl -sI --max-time 15 "$SITE_URL/" | tr -d '\r' | grep -qi "^$H:" \
    || log "ВНИМАНИЕ: заголовок $H отсутствует в ответе /"
done

# X-Powered-By: приложение обязано его снимать (server/plugins/strip-powered-by.ts).
# Возврат заголовка = плагин выпал из сборки, и по нему сканер определяет стек.
curl -sI --max-time 15 "$SITE_URL/" | tr -d '\r' | grep -qi "^x-powered-by:" \
  && log "ВНИМАНИЕ: ответ отдаёт X-Powered-By — плагин strip-powered-by не сработал"

log "деплой $REF завершён"
