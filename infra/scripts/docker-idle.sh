#!/usr/bin/env bash
# docker-idle.sh — гасит dev-стек Docker, когда с ним никто не работает.
#
# Режимы:
#   hook-post [payload]  вызывается из PostToolUse: запоминает, что в этой сессии
#                       только что выполнялась команда, связанная с docker
#   hook-stop            вызывается из Stop: планирует выключение с задержкой
#   __delayed            внутренний режим: та самая отложенная проверка
#   check                показать решение и причину, ничего не меняя
#   stop                 выключить стек, если решение «можно»
#   ensure               поднять стек, если он не поднят (для задач, которым нужен docker)
#   cancel               снять отложенное выключение
#
# Решение «можно выключать» принимается, когда ВСЕ условия верны:
#   1) нет живых процессов docker CLI — кто-то прямо сейчас что-то делает;
#   2) нет свежих следов работы с docker в других сессиях (окно IDLE_WINDOW);
#   3) нет хостовых процессов, привязанных к каталогу проекта (vite, playwright, pytest…);
#   4) отложенная проверка (GRACE) уже выдержала паузу — сессия успела вернуться.
#
# Переменные окружения:
#   DOCKER_IDLE_WINDOW=900   окно «недавней» активности, сек (по умолчанию 15 мин)
#   DOCKER_IDLE_GRACE=180    пауза перед выключением, сек (по умолчанию 3 мин)
#   DOCKER_IDLE_KEEP_DESKTOP=1  не выключать сам Docker Desktop (только контейнеры)

set -uo pipefail

SELF="${BASH_SOURCE[0]}"
PROJECT_DIR="${ZCODE_PROJECT_DIR:-$PWD}"
COMPOSE_FILE="$PROJECT_DIR/infra/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"
STATE_DIR="$HOME/.zcode/docker-idle"
LOG="$STATE_DIR/docker-idle.log"
ACTIVITY="$STATE_DIR/last-docker-activity"       # mtime = последняя работа с docker
CANCEL="$STATE_DIR/cancel-until"                 # epoch: до этого момента не выключать
PENDING="$STATE_DIR/stop-pending"                # pid отложенной проверки
COMPOSE_PROJECT="price-portal"

IDLE_WINDOW="${DOCKER_IDLE_WINDOW:-900}"
GRACE="${DOCKER_IDLE_GRACE:-180}"
STALE_MIN="${DOCKER_IDLE_STALE_MIN:-20}"

mkdir -p "$STATE_DIR" 2>/dev/null

# Хук висит в общем конфиге ZCode — работаем только внутри этого проекта.
[ -f "$COMPOSE_FILE" ] || exit 0

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG" 2>/dev/null; }

debug() { # payload хука — коротко, чтобы понять, пришли ли нужные поля
  local f="$STATE_DIR/hook-debug.log"
  [ -f "$f" ] && [ "$(wc -c <"$f" 2>/dev/null || echo 0)" -gt 200000 ] && : >"$f"
  { printf '=== %s mode=%s cwd=%s\n' "$(date '+%H:%M:%S')" "${1:-}" "$PWD"
    printf 'env: %s\n' "$(env | grep -iE 'zcode|session' | cut -c1-100 | tr '\n' ' ')"
    printf 'payload: %s\n' "$(printf '%s' "${2:-}" | cut -c1-400)"
  } >>"$f" 2>/dev/null
}

now() { date +%s; }

# ---------------------------------------------------------------- payload ----
# Достаём id сессии из stdin-payload хука (в ZCode поле может называться иначе,
# поэтому берём первый подходящий ключ) — он нужен, чтобы не путать свою сессию с чужой.
session_id_from() {
  local payload="$1" sid=""
  sid=$(printf '%s' "$payload" | grep -oE '"(session|conversation)_?([iI])d"[[:space:]]*:[[:space:]]*"[^"]*"' \
        | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')
  [ -n "$sid" ] || sid="${ZCODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"
  printf '%s' "$sid"
}

payload_field() { # $1 — ключ, $2 — json
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$2" | python3 -c '
import json,sys
raw = sys.stdin.read()
keys = sys.argv[1:]
try:
    data = json.loads(raw)
except Exception:
    data = None
def dig(d, k):
    if isinstance(d, dict):
        for kk, vv in d.items():
            if kk in keys and isinstance(vv, str):
                return vv
            r = dig(vv, k)
            if r:
                return r
    elif isinstance(d, list):
        for it in d:
            r = dig(it, k)
            if r:
                return r
    return ""
print(dig(data, keys), end="")
' "$1" 2>/dev/null && return 0
  fi
  printf '%s' "$2" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 | sed -E "s/.*:[[:space:]]*\"([^\"]*)\"/\1/"
}

# Команда считается «связанной с docker», если в ней есть docker / make-цели стека.
touches_docker() {
  printf '%s' "$1" | grep -Eqi \
    'docker[ _-]?(compose|ps|exec|run|build|logs|down|up|system)|[^a-z]docker[^a-z]|make +(up|down|ps|logs|build|test|test-pattern|test-e2e|migrate|migrate-gen|seed|seed-all|seed-catalog|alembic-check|restore-test|test-load|test-load-import|web-dev|web-prod|ratelimit-reset|db-reset)\b'
}

mark_activity() {
  : >"$ACTIVITY" 2>/dev/null
  log "активность: docker"
}

cancel_pending() {
  rm -f "$PENDING" 2>/dev/null
  printf '%s' "$(now)" >"$CANCEL" 2>/dev/null
}

# ------------------------------------------------------------------ проверки --
daemon_up() { docker info >/dev/null 2>&1; }

# PID'ы наших собственных предков: их не считаем «другой сессией» — это мы сами.
ancestor_pids() {
  local p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    printf '%s\n' "$p"
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
}

# Живые процессы docker CLI (сам Docker Desktop и его помощники — не в счёт).
#
# Различаем два случая:
#   * docker compose build/up — долгие по определению, считаем активными всегда;
#   * exec/ps/logs/down — обычно секунды, но могут «залипнуть» (незакрытый stdout),
#     поэтому процесс старше DOCKER_IDLE_STALE_MIN считаем мёртвым.
docker_clients() {
  local line pid elapsed cmd mine
  mine=" $(ancestor_pids | tr '\n' ' ')"
  while read -r pid elapsed cmd; do
    [ -n "$pid" ] || continue
    case "$mine" in *" $pid "*) continue ;; esac
    case "$cmd" in
      *docker-idle.sh*|*'/Applications/Docker.app'*|*"Docker Desktop"*) continue ;;
      grep\ *|*/grep\ *) continue ;;
    esac
    case "$cmd" in
      *"docker-compose"*|*com.docker.cli*|*"/docker "*|*" docker "*) ;;
      *) continue ;;
    esac
    case "$cmd" in
      *' build'*|*' up'*|*'--build'*) : ;;   # долгие — активны всегда
      *)
        if [ "${elapsed%%:*}" -gt "$STALE_MIN" ] 2>/dev/null; then
          log "игнорирую зависший процесс (${elapsed}): $(printf '%s' "$cmd" | cut -c1-80)"
          continue
        fi
        ;;
    esac
    printf '%s %s %s\n' "$pid" "$elapsed" "$(printf '%s' "$cmd" | cut -c1-120)"
  done <<EOF
$(ps -Ao pid=,etime=,command= 2>/dev/null \
    | grep -E 'docker-compose|com\.docker\.cli|(^|[/ ])docker (compose|exec|run|ps|logs|build|down|up|system|stats|cp|inspect|image|volume|network)' \
    | grep -vE "^\s*[0-9]+ +(ps|grep)" \
    | head -20)
EOF
}

# Хостовые процессы, которым стек реально нужен: dev-серверы, браузерные тесты,
# локальные тесты и работа с БД. Сверяемся по ИМЕНИ процесса, а не по тексту команды:
# иначе zsh-обёртка с упоминанием «pytest» в скрипте выглядела бы как работа.
project_hosts() {
  ps -Ao pid=,etime=,comm=,command= 2>/dev/null | awk -v proj="$PROJECT_DIR" '
    index($0, proj) == 0 { next }
    {
      comm = $3
      n = split("vite nuxt pytest psql pg_dump pg_restore pgbench k6 redis-cli uvicorn gunicorn playwright chromium chrome headless_shell", want, " ")
      for (i = 1; i <= n; i++)
        if (index(comm, want[i]) > 0) { print substr($0, 1, 140); break }
    }' | head -5
}

# Свежие следы работы с docker в других сессиях (свой след исключается).
fresh_marks() {
  local f now_s age mark
  now_s=$(now)
  mark="mark-$(printf '%s' "${1:-}" | tr -c 'A-Za-z0-9._-' '_')"
  for f in "$STATE_DIR"/mark-*; do
    [ -e "$f" ] || continue
    age=$(( now_s - $(date -r "$f" +%s 2>/dev/null || echo 0) ))
    if [ "$age" -ge "$IDLE_WINDOW" ]; then rm -f "$f" 2>/dev/null; continue; fi
    [ -n "${1:-}" ] && [ "$(basename "$f")" = "$mark" ] && continue
    printf '%s (%sм)\n' "$(basename "$f")" "$((age / 60))"
  done
}

running_containers() { docker ps -q 2>/dev/null | wc -l | tr -d ' '; }
project_containers() {
  docker ps --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" -q 2>/dev/null | wc -l | tr -d ' '
}
# Какие из нужных сервисов не работают: «есть хоть один контейнер» — недостаточно,
# после частичного подъёма web/nginx молча остались бы лежать.
missing_services() {
  local svc
  for svc in $SERVICES; do
    [ -n "$(docker ps --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
        --filter "label=com.docker.compose.service=$svc" -q 2>/dev/null)" ] || printf '%s ' "$svc"
  done
}

decide() { # $1 — id своей сессии (чтобы не считать свой след чужим)
  local c
  if [ "${DOCKER_IDLE_FORCE:-0}" != "1" ]; then
    c=$(docker_clients)
    [ -n "$c" ] && { printf 'работает docker CLI:\n%s\n' "$c"; return; }
    c=$(project_hosts)
    [ -n "$c" ] && { printf 'хостовые процессы проекта:\n%s\n' "$c"; return; }
  fi
  c=$(fresh_marks "${1:-}")
  [ -n "$c" ] && { printf 'свежая работа с docker в других сессиях: %s\n' "$c"; return; }
  if [ "$(running_containers)" -gt 0 ] && [ ! -f "$ACTIVITY" ]; then
    printf 'нет отметки активности, но контейнеры кто-то поднял вручную\n'
    return
  fi
  if [ -f "$CANCEL" ] && [ "$(now)" -lt "$(cat "$CANCEL" 2>/dev/null || echo 0)" ]; then
    printf 'отложенное выключение отменено\n'; return
  fi
  [ -f "$CANCEL" ] && rm -f "$CANCEL"
  return 0
}

# -------------------------------------------------------------------- действия --
stop_stack() {
  local n
  n=$(project_containers)
  [ "$n" = "0" ] && { log "нечего выключать: контейнеров проекта нет"; return 0; }
  log "выключаю стек: контейнеров $n"
  compose down >/dev/null 2>&1
  mark_activity
  if [ "$(running_containers)" = "0" ] && [ "${DOCKER_IDLE_KEEP_DESKTOP:-0}" != "1" ]; then
    log "контейнеров не осталось — выключаю Docker Desktop"
    docker desktop stop >/dev/null 2>&1 || osascript -e 'quit app "Docker"' >/dev/null 2>&1
  fi
  log "стек выключен"
}

# Локально стек живёт без minio/createbuckets: их образы уже не тянутся с Docker Hub,
# поэтому `docker compose up -d` без списка сервисов падает на pull. Держим рабочий набор.
SERVICES="${DOCKER_IDLE_SERVICES:-db redis api web nginx}"

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$COMPOSE_PROJECT" "$@"; }

ensure_stack() {
  daemon_up || {
    log "docker не запущен — поднимаю Docker Desktop"
    open -a Docker >/dev/null 2>&1
    local i=0
    while [ $i -lt 60 ] && ! daemon_up; do sleep 2; i=$((i + 1)); done
    daemon_up || { log "Docker Desktop не поднялся"; return 1; }
  }
  local missing
  missing=$(missing_services)
  [ -z "$missing" ] && { log "стек уже поднят"; return 0; }
  log "поднимаю: $missing"
  if ! compose up -d $missing >"$STATE_DIR/up.log" 2>&1; then
    log "compose up не удался: $(tail -3 "$STATE_DIR/up.log" 2>/dev/null | tr '\n' ' ')"
    return 1
  fi
  # compose иногда возвращает 0, не подняв всё: проверяем фактом.
  sleep 3
  missing=$(missing_services)
  [ -n "$missing" ] && { log "не поднялись: $missing"; return 1; }
  return 0
}

# --------------------------------------------------------------------- режимы --
case "${1:-check}" in
  hook-post)
    payload=$(cat 2>/dev/null || true)
    debug hook-post "$payload"
    sid=$(session_id_from "$payload")
    cmd=$(payload_field command "$payload")
    if [ -n "$cmd" ] && touches_docker "$cmd"; then
      [ -n "$sid" ] && : >"$STATE_DIR/mark-$(printf '%s' "$sid" | tr -c 'A-Za-z0-9._-' '_')" 2>/dev/null
      mark_activity
      cancel_pending
    fi
    exit 0
    ;;
  hook-stop)
    payload=$(cat 2>/dev/null || true)
    debug hook-stop "$payload"
    sid=$(session_id_from "$payload")
    daemon_up || exit 0
    [ "$(project_containers)" = "0" ] && exit 0
    if [ -f "$PENDING" ] && kill -0 "$(cat "$PENDING" 2>/dev/null || echo 0)" 2>/dev/null; then
      log "отложенная проверка уже запланирована"; exit 0
    fi
    log "планирую выключение через ${GRACE}с"
    ( nohup bash "$SELF" __delayed "$sid" >/dev/null 2>&1 & echo $! >"$PENDING" )
    exit 0
    ;;
  __delayed)
    sleep "$GRACE"
    daemon_up || exit 0
    if reason=$(decide "${2:-}") && [ -z "$reason" ]; then
      log "отложенная проверка: выключаю"
      stop_stack
    else
      log "отложенная проверка: оставляю ($reason)"
    fi
    rm -f "$PENDING"
    exit 0
    ;;
  check)
    if ! daemon_up; then echo "docker: не запущен"; exit 0; fi
    echo "docker: запущен, контейнеров проекта: $(project_containers) (всего: $(running_containers))"
    if reason=$(decide "${2:-}") && [ -z "$reason" ]; then
      echo "решение: можно выключать (окно ${IDLE_WINDOW}с, пауза ${GRACE}с)"
    else
      echo "решение: оставить — $reason"
    fi
    ;;
  stop)
    daemon_up || { echo "docker: не запущен"; exit 0; }
    if reason=$(decide "${2:-}") && [ -z "$reason" ]; then stop_stack; echo "стек выключен"
    else echo "оставляю — $reason"; fi
    ;;
  ensure)
    ensure_stack && echo "стек поднят" || echo "не удалось поднять стек"
    ;;
  cancel)
    mark_activity; cancel_pending; echo "отложенное выключение отменено"
    ;;
  *)
    echo "использование: $0 {hook-post|hook-stop|check|stop|ensure|cancel}" >&2; exit 2
    ;;
esac
