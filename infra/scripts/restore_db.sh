#!/usr/bin/env bash
# restore_db.sh — восстановление БД из дампа (pg_dump -Fc, как делает backup_db.sh).
#
# ВНИМАНИЕ: операция УНИЧТОЖАЕТ содержимое базы (pg_restore --clean --if-exists
# сначала дропает объекты, потом заливает данные из дампа). Поэтому скрипт
# требует явного --yes; без него он только печатает предупреждение и выходит
# с ненулевым кодом. Это защита от `make restore-test`, cron'а и автодополнения
# в командной строке: восстановление из не того файла необратимо.
#
# Использование:
#   infra/scripts/restore_db.sh --yes                       # свежий дамп из infra/backups/
#   infra/scripts/restore_db.sh --yes -f путь/к/дампу.dump   # конкретный дамп
#   infra/scripts/restore_db.sh --yes --list                # список дампов, без изменений
#   infra/scripts/restore_db.sh --test --yes                # восстановление в одноразовую БД
#                                                               # (проверка бэкапа, §16 п.30),
#                                                               # база удаляется после проверки
#
# Переменные окружения:
#   BACKUP_DIR=<путь>    где искать дампы (по умолчанию <корень>/infra/backups)
#   POSTGRES_USER=<user> / POSTGRES_DB=<db> — из <корень>/.env, если не заданы
#
# Что именно делает скрипт (в порядке шагов):
#   1) проверяет файл: существует, не пуст, начинается с PGDMP, читается pg_restore;
#   2) закрывает чужие соединения с целевой БД (иначе DROP из --clean упрётся в api/celery);
#   3) pg_restore --clean --if-exists из дампа (STDIN, -Fc);
#   4) проверяет результат фактом (pg_restore -l + SELECT из восстановленной базы).
#
# Коды выхода: 0 — восстановлено; 1 — ошибка окружения/БД/дампа; 2 — не передано --yes.
set -euo pipefail

SELF_NAME="$(basename "${BASH_SOURCE[0]}")"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/infra/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"
TEST_DB_SUFFIX="_restore_test"

BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/infra/backups}"
CONFIRMED=0
LIST_ONLY=0
TEST_MODE=0
DUMP_FILE=""

PG_ERR=""
TEST_DB=""

# ------------------------------------------------------------------ вывод -----
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_DIM=""; C_OFF=""
fi
info() { printf '%s==>%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%s[внимание]%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
err()  { printf '%s[ошибка]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
dim()  { printf '    %s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }

usage() {
  cat <<EOF
$SELF_NAME — восстановление БД из дампа (pg_restore --clean --if-exists).

  -y, --yes            ОБЯЗАТЕЛЬНОЕ подтверждение: без него скрипт откажется работать.
  -f, --file <файл>    дамп .dump (по умолчанию — самый свежий в BACKUP_DIR)
      --list           показать доступные дампы и выйти
      --test           восстановить во временную БД и удалить её после проверки
                       (проверка бэкапа без риска для рабочих данных)
  -h, --help           эта справка

Примеры:
  $SELF_NAME --yes                              # восстановить свежий дамп в \$POSTGRES_DB
  $SELF_NAME --yes --test                       # «проверить бэкап» (make restore-test)
  $SELF_NAME --yes -f infra/backups/price_portal_20260101_030000.dump
EOF
}

cleanup() {
  [ -n "$PG_ERR" ] && [ -e "$PG_ERR" ] && rm -f "$PG_ERR"
  # Временную БД сносим даже при ошибке — иначе после неудачного прогона
  # в кластере остаётся мусор, который потом не отличить от рабочих данных.
  # Две отдельные команды -c: DROP DATABASE нельзя выполнять внутри
  # транзакции, а несколько statements в одном -c psk оборачивает именно в неё.
  if [ "$TEST_MODE" = 1 ] && [ -n "$TEST_DB" ]; then
    if compose exec -T db psql -U "$POSTGRES_USER" -d postgres -q \
         -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='$TEST_DB'" \
         -c "drop database if exists \"$TEST_DB\"" >/dev/null 2>&1; then
      dim "временная БД $TEST_DB удалена"
    else
      warn "не удалось удалить временную БД $TEST_DB — снесите вручную:"
      warn "  docker compose exec db psql -U $POSTGRES_USER -d postgres -c 'drop database \"$TEST_DB\"'"
    fi
  fi
  return 0
}
on_exit() {
  rc=$?
  # Код 2 — осознанный отказ (нет --yes / неизвестный аргумент): сообщение о нём
  # уже напечатано, второй раз не дублируем.
  [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ] && err "$SELF_NAME завершился с ошибкой (код $rc)"
  cleanup
  exit "$rc"
}
trap on_exit EXIT
trap 'err "прервано (Ctrl-C)"; cleanup; exit 130' INT TERM

# ---------------------------------------------------------------- утилиты ------
env_value() {
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$ENV_FILE" | tail -1 \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }
psql_q() { # $1 — база, $2 — запрос
  compose exec -T db psql -U "$POSTGRES_USER" -d "$1" -tAc "$2" 2>/dev/null | tr -d '[:space:]'
}
human_size() {
  local b="${1:-0}"
  if [ "$b" -ge 1048576 ]; then awk -v b="$b" 'BEGIN{printf "%.1fM", b/1048576}'
  elif [ "$b" -ge 1024 ]; then awk -v b="$b" 'BEGIN{printf "%.1fK", b/1024}'
  else printf '%sB' "$b"; fi
}

# ------------------------------------------------------------------- флаги -----
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)   CONFIRMED=1; shift ;;
    -f|--file)  DUMP_FILE="${2:?нужен путь после $1}"; shift 2 ;;
    --list)     LIST_ONLY=1; shift ;;
    --test)     TEST_MODE=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) err "неизвестный аргумент: $1"; usage >&2; exit 2 ;;
  esac
done

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-price}"
DB_NAME="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
DB_NAME="${DB_NAME:-price_portal}"

# ------------------------------------------------------------- окружение ------
[ -f "$COMPOSE_FILE" ] || { err "не найден $COMPOSE_FILE"; exit 1; }
command -v docker >/dev/null 2>&1 || { err "docker не установлен"; exit 1; }
docker info >/dev/null 2>&1 || { err "docker daemon недоступен"; exit 1; }
PG_ERR="$(mktemp "${TMPDIR:-/tmp}/restore_db.XXXXXX")"

list_dumps() {
  [ -d "$BACKUP_DIR" ] || return 0
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'price_portal_*.dump' 2>/dev/null | sort
}

if [ "$LIST_ONLY" = 1 ]; then
  n=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    printf '%-46s %8s  %s\n' "$(basename "$f")" "$(human_size "$(wc -c <"$f" | tr -d ' ')")" \
      "$(date -r "$f" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo '?')"
    n=$((n + 1))
  done <<EOF
$(list_dumps)
EOF
  echo "всего дампов: $n (каталог $BACKUP_DIR)"
  exit 0
fi

# ---- ГЛАВНЫЙ БАРЬЕР: без --yes не делаем ничего --------------------------------
if [ "$CONFIRMED" != 1 ]; then
  cat >&2 <<EOF

  ВНИМАНИЕ: $SELF_NAME УНИЧТОЖАЕТ данные в базе «${POSTGRES_DB:-$DB_NAME}».
  Команда pg_restore --clean --if-exists удалит все таблицы, представления,
  типы и последовательности этой базы и загрузит состояние из дампа.
  Отменить это нельзя.

  Возврат данных из резервной копии делается вручную и с проверкой.

  Если нужно:
    * восстановить свежий дамп в рабочую базу  →  $SELF_NAME --yes
    * просто проверить бэкап (во временную БД) →  $SELF_NAME --test --yes

EOF
  err "подтверждение не передано: добавьте --yes (код выхода 2)"
  exit 2
fi

# ------------------------------------------------------- выбор дампа -----------
if [ -z "$DUMP_FILE" ]; then
  DUMP_FILE=$(list_dumps | tail -1)
  [ -n "$DUMP_FILE" ] || {
    err "в каталоге $BACKUP_DIR нет дампов (сначала infra/scripts/backup_db.sh)"
    exit 1
  }
  dim "дамп не указан — беру самый свежий"
fi
[ -f "$DUMP_FILE" ] || {
  err "файл дампа не найден: $DUMP_FILE"
  err "доступные дампы:"
  list_dumps | sed 's/^/    /' >&2 || true
  exit 1
}
DUMP_FILE="$(cd "$(dirname "$DUMP_FILE")" && pwd)/$(basename "$DUMP_FILE")"

# ---- проверка файла ДО любых изменений ----------------------------------------
size=$(wc -c <"$DUMP_FILE" | tr -d ' ')
if [ "${size:-0}" -lt 1024 ]; then
  err "дамп пустой или обрезан (${size:-0} байт): $DUMP_FILE — восстановление невозможно"
  exit 1
fi
magic=$(head -c 5 "$DUMP_FILE" | LC_ALL=C tr -c '[:print:]' '.')
if [ "$magic" != "PGDMP" ]; then
  err "нет сигнатуры PGDMP (начало: '${magic}') — это не custom-формат (-Fc). Ожидался дамп из backup_db.sh."
  exit 1
fi
# Строки TOC из pg_restore --list начинаются с id объекта; «;» — это комментарии
# заголовка (кто, когда, какая версия), их не считаем объектами.
entries=$(compose exec -T db pg_restore --list <"$DUMP_FILE" 2>"$PG_ERR" | grep -c '^[0-9]' || true)
if [ "${entries:-0}" -eq 0 ]; then
  err "pg_restore --list не увидел ни одного объекта в дампе:"
  sed 's/^/    /' "$PG_ERR" >&2 || true
  exit 1
fi

if [ "$TEST_MODE" = 1 ]; then
  TARGET_DB="${DB_NAME}${TEST_DB_SUFFIX}"
  TEST_DB="$TARGET_DB"
else
  TARGET_DB="$DB_NAME"
fi

printf '\n%s==>%s Восстановление БД\n' "$C_GRN" "$C_OFF"
dim "дамп:      $DUMP_FILE ($(human_size "$size"), объектов: $entries)"
dim "база:      $TARGET_DB (пользователь $POSTGRES_USER)"
[ "$TEST_MODE" = 1 ] && dim "режим:     --test (одноразовая БД, рабочие данные не трогаются)"

# ---- закрываем чужие соединения (иначе DROP из --clean упрётся в api/celery) ---
if [ "$TEST_MODE" != 1 ]; then
  compose exec -T db psql -U "$POSTGRES_USER" -d postgres -qc \
    "select pg_terminate_backend(pid) from pg_stat_activity where datname='$TARGET_DB' and pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || warn "не удалось закрыть соединения с $TARGET_DB (возможно, их и не было)"
fi

# ---- создаём одноразовую БД, если --test --------------------------------------
if [ "$TEST_MODE" = 1 ]; then
  compose exec -T db psql -U "$POSTGRES_USER" -d postgres -qc \
    "drop database if exists \"$TARGET_DB\";" >/dev/null 2>&1 || true
  compose exec -T db psql -U "$POSTGRES_USER" -d postgres -qc \
    "create database \"$TARGET_DB\";" >/dev/null 2>&1 || {
    err "не удалось создать временную БД $TARGET_DB"
    exit 1
  }
fi

# ---- сам restore ---------------------------------------------------------------
# -d "$TARGET_DB" + данные на STDIN: -Fc-дамп бинарный, перенаправлять файл внутрь
# контейнера не нужно (и не сработало бы: путь хоста там не существует).
set +e
compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$TARGET_DB" \
  --clean --if-exists --single-transaction <"$DUMP_FILE" >>"$PG_ERR" 2>&1
rc=$?
set -e

if grep -qE 'pg_restore: error:|FATAL:' "$PG_ERR"; then
  err "pg_restore сообщил об ошибках (см. детали ниже):"
  grep -E 'pg_restore: error:|FATAL:' "$PG_ERR" | head -10 | sed 's/^/    /' >&2
  exit 1
fi
if [ "$rc" -ne 0 ]; then
  err "pg_restore завершился с кодом $rc:"
  tail -10 "$PG_ERR" | sed 's/^/    /' >&2
  exit 1
fi

# ---- проверка результата фактом, а не «по коду выхода» -------------------------
# pg_restore не собирает статистику: без ANALYZE планировщик смотрит в пустую
# статистику (плохие планы сразу после восстановления), а pg_stat отдаёт нули.
# Для базы такого размера это дешёвая операция, поэтому делаем её всегда.
psql_q "$TARGET_DB" "analyze" >/dev/null 2>&1 || warn "ANALYZE не отработал (это не критично)"

tables=$(psql_q "$TARGET_DB" "select count(*) from information_schema.tables where table_schema='public'")
rows=$(psql_q "$TARGET_DB" "select coalesce(sum(n_live_tup),0) from pg_stat_user_tables")
[ -n "${tables:-}" ] || { err "БД $TARGET_DB недоступна после restore"; exit 1; }
if [ "${tables:-0}" -eq 0 ]; then
  err "в $TARGET_DB нет ни одной таблицы — дамп восстановился не полностью"
  exit 1
fi

printf '%s[ок]%s БД %s восстановлена: таблиц в public — %s, строк — %s\n' \
  "$C_GRN" "$C_OFF" "$TARGET_DB" "$tables" "${rows:-?}"
dim "размер БД на диске: $(psql_q "$TARGET_DB" 'select pg_size_pretty(pg_database_size(current_database()))')"

if [ "$TEST_MODE" = 1 ]; then
  info "Проверка бэкапа успешна — временная БД будет удалена."
else
  cat <<EOF

  Что дальше:
    * alembic-миграции на дампе могут отставать от кода — сверь:
        docker compose -f $COMPOSE_FILE exec api alembic current
    * перезапусти API/воркеры, чтобы они подхватили восстановленную схему:
        make up

EOF
fi