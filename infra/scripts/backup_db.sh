#!/usr/bin/env bash
# backup_db.sh — бэкап БД проекта (pg_dump -Fc) в infra/backups/ + ротация.
#
# Использование:
#   infra/scripts/backup_db.sh              # бэкап в infra/backups/, ротация
#   infra/scripts/backup_db.sh -o /tmp/bk   # другой каталог
#   infra/scripts/backup_db.sh -k 30        # хранить 30 дампов вместо 14
#   infra/scripts/backup_db.sh --list       # показать существующие дампы
#   infra/scripts/backup_db.sh --help
#
# Переменные окружения (значения флагов имеют приоритет над ними):
#   BACKUP_DIR=<путь>     каталог для дампов (по умолчанию <корень>/infra/backups)
#   BACKUP_KEEP=<N>       сколько последних дампов хранить (по умолчанию 14)
#   POSTGRES_USER=<user>  пользователь БД (по умолчанию — из <корень>/.env)
#   POSTGRES_DB=<db>      имя базы (по умолчанию — из <корень>/.env)
#
# Имя файла: price_portal_YYYYmmdd_HHMMSS.dump (custom format, -Fc — сжатый,
# выборочное восстановление, именно его ждёт pg_restore -Fc).
#
# Почему валидация magic-байтов обязательна: при обрыве связи/событии в контейнере
# pg_dump может оставить 0-байтный (или обрезанный) файл, а ротация потом спокойно
# удалит нормальные дампы. Непустой файл с сигнатурой PGDMP — единственная
# дешёвая проверка, что дамп пригоден для восстановления.
#
# Коды выхода: 0 — дамп сделан; 1 — ошибка окружения/БД; 2 — ошибка использования.
set -euo pipefail

SELF_NAME="$(basename "${BASH_SOURCE[0]}")"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/infra/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"
COMPOSE_PROJECT="price-portal"

# Каталог дампов и глубина ротации (1 = без ротации).
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/infra/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
KEEP="$BACKUP_KEEP"

TMP_DUMP=""; EXIT_CODE=0

# ------------------------------------------------------------------ вывод -----
# Цвета — только в TTY и только если не выставлен NO_COLOR (в CI/логах — plain).
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
$SELF_NAME — бэкап БД (pg_dump -Fc) с проверкой целостности и ротацией.

  -o, --out <каталог>   куда складывать дампы (по умолчанию infra/backups)
  -k, --keep <N>        сколько последних дампов хранить (по умолчанию 14; 0 — без ротации)
  -l, --list            показать существующие дампы и выйти
  -h, --help            эта справка

Примеры:
  infra/scripts/backup_db.sh                    # обычный бэкап (make backup)
  BACKUP_DIR=/mnt/backups infra/scripts/backup_db.sh -k 30
EOF
}

# ---------------------------------------------------------------- уборка -------
# Частичный файл после обрыва не должен остаться в каталоге бэкапов: иначе он
# попадёт под ротацию и в «список дампов» как валидный.
cleanup() {
  [ -n "$TMP_DUMP" ] && [ -e "$TMP_DUMP" ] && rm -f "$TMP_DUMP"
  return 0
}
on_exit() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    err "$SELF_NAME завершился с ошибкой (код $rc)"
    [ -n "$TMP_DUMP" ] && [ -e "$TMP_DUMP" ] && \
      dim "недописанный файл удалён: ${TMP_DUMP##*/}"
  fi
  cleanup
  exit "$rc"
}
trap on_exit EXIT
trap 'err "прервано (Ctrl-C)"; cleanup; exit 130' INT TERM

# ---------------------------------------------------------------- утилиты ------
env_value() { # $1 — ключ .env; пустая строка, если нет
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$ENV_FILE" | tail -1 \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

human_size() { # 1536 -> 1.5K
  local b="${1:-0}"
  if [ "$b" -ge 1048576 ]; then awk -v b="$b" 'BEGIN{printf "%.1fM", b/1048576}'
  elif [ "$b" -ge 1024 ]; then awk -v b="$b" 'BEGIN{printf "%.1fK", b/1024}'
  else printf '%sB' "$b"; fi
}

# ------------------------------------------------------------------- флаги -----
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--out)  BACKUP_DIR="${2:?нужен путь после $1}"; shift 2 ;;
    -k|--keep) KEEP="${2:?нужен N после $1}"; shift 2 ;;
    -l|--list) LIST_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "неизвестный аргумент: $1"; usage >&2; exit 2 ;;
  esac
done

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-price}"
DB_NAME="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
DB_NAME="${DB_NAME:-price_portal}"
DUMP_PREFIX="price_portal"

# -------------------------------------------------------------- окружение -----
[ -f "$COMPOSE_FILE" ] || { err "не найден $COMPOSE_FILE — запуск не из репозитория?"; exit 1; }
[ -f "$ENV_FILE" ] || warn "$ENV_FILE не найден — беру дефолты compose"

command -v docker >/dev/null 2>&1 || { err "docker не установлен"; exit 1; }
docker info >/dev/null 2>&1 || { err "docker daemon недоступен"; exit 1; }

case "$KEEP" in ''|*[!0-9]*) err "BACKUP_KEEP должен быть целым числом, получено: '$KEEP'"; exit 2 ;; esac

mkdir -p "$BACKUP_DIR" || { err "не удалось создать каталог $BACKUP_DIR"; exit 1; }
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

list_dumps() {
  # Имена хронологичны (YYYYmmdd_HHMMSS), поэтому sort по имени = sort по времени.
  find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DUMP_PREFIX}_*.dump" 2>/dev/null | sort
}

if [ "${LIST_ONLY:-0}" = 1 ]; then
  n=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    sz=$(wc -c <"$f" | tr -d ' ')
    printf '%-46s %8s  %s\n' "$(basename "$f")" "$(human_size "$sz")" "$(date -r "$f" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo '?')"
    n=$((n + 1))
  done <<EOF
$(list_dumps)
EOF
  echo "всего дампов: $n (каталог $BACKUP_DIR)"
  exit 0
fi

# Каталог бэкапов не должен попадать в git: дампы — это персональные данные клиентов.
ensure_gitignore() {
  if grep -qsE '^infra/backups/?$' "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    return 0
  fi
  if [ -f "$BACKUP_DIR/.gitignore" ]; then
    grep -qsE '^\*$' "$BACKUP_DIR/.gitignore" 2>/dev/null && return 0
  fi
  printf '*\n!.gitignore\n' >"$BACKUP_DIR/.gitignore" 2>/dev/null || {
    warn "не смог записать $BACKUP_DIR/.gitignore"; return 0; }
  warn "каталог бэкапов не был в .gitignore — создал $BACKUP_DIR/.gitignore (дампы игнорируются)"
}

ensure_gitignore

# ------------------------------------------------------------- доступность ----
db_size=$(compose exec -T db psql -U "$POSTGRES_USER" -d "$DB_NAME" -tAc \
  "select coalesce(pg_database_size(current_database()),0)" 2>/dev/null | tr -d '[:space:]' || echo "")
if [ -z "$db_size" ]; then
  err "БД $DB_NAME недоступна от пользователя $POSTGRES_USER (контейнер db не healthy?)"
  err "проверь: docker compose -f $COMPOSE_FILE ps db"
  exit 1
fi
db_size=${db_size:-0}

avail_kb=$(df -Pk "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "${avail_kb:-}" ] && [ "$db_size" -gt 0 ]; then
  avail_b=$((avail_kb * 1024))
  if [ "$avail_b" -lt "$db_size" ]; then
    warn "свободно $(human_size "$avail_b"), а база занимает $(human_size "$db_size") — места может не хватить"
  fi
fi

# ------------------------------------------------------------------- дамп -----
TS="$(date '+%Y%m%d_%H%M%S')"
FINAL="$BACKUP_DIR/${DUMP_PREFIX}_${TS}.dump"
TMP_DUMP="$BACKUP_DIR/.${DUMP_PREFIX}_${TS}.dump.partial"

info "Бэкап БД: $DB_NAME (пользователь $POSTGRES_USER)"
dim "каталог: $BACKUP_DIR"

# pg_dump пишет в stdout; -T отключает псевдо-TTY (иначе в дамп попадают
# управляющие последовательности). Ошибка pg_dump летит в stderr → падает под set -e.
if ! compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$DB_NAME" >"$TMP_DUMP" 2>/tmp/backup_db.err; then
  err "pg_dump завершился с ошибкой:"
  sed 's/^/    /' /tmp/backup_db.err >&2 || true
  exit 1
fi
[ -s /tmp/backup_db.err ] && sed 's/^/    /' /tmp/backup_db.err >&2
rm -f /tmp/backup_db.err

# --- валидация: размер + магические байты custom format (PGDMP) --------------
size=$(wc -c <"$TMP_DUMP" | tr -d ' ')
if [ "${size:-0}" -lt 1024 ]; then
  err "дамп подозрительно мал (${size} байт) — обрыв записи? Файл не принят."
  exit 1
fi
magic=$(head -c 5 "$TMP_DUMP" | LC_ALL=C tr -c '[:print:]' '.')
if [ "$magic" != "PGDMP" ]; then
  err "нет сигнатуры PGDMP (начало файла: '${magic}') — это не custom-формат pg_dump -Fc. Файл не принят."
  exit 1
fi
# Дополнительно: pg_restore --list обязан разобрать заголовок (ловит битый хвост
# на этапе чтения заголовка, а не после «успешного» пустого restore).
if ! compose exec -T db pg_restore --list <"$TMP_DUMP" >/dev/null 2>/tmp/backup_db.lst; then
  err "pg_restore --list не смог прочитать дамп — файл повреждён, он НЕ принят:"
  sed 's/^/    /' /tmp/backup_db.lst >&2 || true
  exit 1
fi
rm -f /tmp/backup_db.lst

mv -f "$TMP_DUMP" "$FINAL"
TMP_DUMP=""

printf '%s[ок]%s дамп создан: %s (%s)\n' "$C_GRN" "$C_OFF" "$(basename "$FINAL")" "$(human_size "$size")"

# --------------------------------------------------------------- ротация ------
if [ "$KEEP" -gt 0 ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    rm -f "$f" || warn "не удалось удалить старый дамп: $f"
    dim "удалён старый дамп: $(basename "$f")"
  done <<EOF
$(list_dumps | head -n "-$KEEP" 2>/dev/null || list_dumps)
EOF
fi

left=$(list_dumps | grep -c . || true)
info "Готово. Дампов в каталоге: ${left:-0} (храним последние $KEEP)"
info "Восстановление: infra/scripts/restore_db.sh --yes -f $FINAL"