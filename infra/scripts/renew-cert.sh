#!/usr/bin/env bash
# ============================================================
#  Автопродление TLS-сертификата Let's Encrypt
#
#  Публичный вход: https://bublik.tail4fd7f3.ts.net/price/
#  TLS терминирует наш nginx (infra/nginx/nginx.prod.conf), а не Funnel.
#  Сертификат — Let's Encrypt для ts.net-домена, и выдать его может только
#  сам Tailscale (`tailscale cert`): отдельный ACME-клиент (certbot) с
#  ACME-челленджем на этот домен не справляется.
#
#  Логика:
#    1. `tailscale cert --min-validity 720h` — если до истечения больше
#       30 суток, Tailscale вернёт ТОТ ЖЕ сертификат (шаг ничего не меняет);
#       если меньше — выпустит новый.
#    2. Проверяем, что новый сертификат валиден и покрывает домен.
#    3. Подставляем файлы в infra/nginx/certs/ (каталог в .gitignore).
#    4. Перечитываем их в nginx через `nginx -s reload` — без рестарта
#       контейнера и без разрыва соединений.
#
#  Идемпотентен: безопасно запускать хоть каждый час.
#  Расписание на хосте — systemd-таймер (infra/systemd/price-cert-renew.*).
#  Процедура в docs/RUNBOOK.md («TLS-сертификат Let's Encrypt (автопродление)»).
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DOMAIN="${CERT_DOMAIN:-bublik.tail4fd7f3.ts.net}"
CERT_DIR="${CERT_DIR:-${REPO_ROOT}/infra/nginx/certs}"
MIN_VALIDITY="${CERT_MIN_VALIDITY:-720h}"          # 30 суток
NGINX_CONTAINER="${NGINX_CONTAINER:-pp-nginx}"

log() { printf '%s [cert-renew] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ОШИБКА: $*"; exit 1; }

command -v tailscale >/dev/null 2>&1 || fail "нет команды tailscale"
command -v openssl  >/dev/null 2>&1 || fail "нет команды openssl"
[ -d "${CERT_DIR}" ] || fail "нет каталога сертификатов: ${CERT_DIR}"

WORKDIR="$(mktemp -d)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

log "домен=${DOMAIN} каталог=${CERT_DIR} min-validity=${MIN_VALIDITY}"

# --- 1. Забрать сертификат у Tailscale ----------------------------------
tailscale cert \
  --cert-file "${WORKDIR}/fullchain.pem" \
  --key-file "${WORKDIR}/privkey.pem" \
  --min-validity "${MIN_VALIDITY}" \
  "${DOMAIN}" || fail "tailscale cert не отработал"

[ -s "${WORKDIR}/fullchain.pem" ] || fail "Tailscale не вернул сертификат"
[ -s "${WORKDIR}/privkey.pem" ]   || fail "Tailscale не вернул приватный ключ"

# --- 2. Проверить выданное ----------------------------------------------
openssl x509 -in "${WORKDIR}/fullchain.pem" -noout -checkend 604800 >/dev/null \
  || fail "выданный сертификат просрочен (или истекает меньше чем через 7 суток)"
if ! openssl x509 -in "${WORKDIR}/fullchain.pem" -noout -checkhost "${DOMAIN}" >/dev/null 2>&1; then
  fail "сертификат не покрывает домен ${DOMAIN}"
fi

# --- 3. Сравнить с текущим: продление нужно только если файлы изменились -
new_cert_sum="$(sha256sum "${WORKDIR}/fullchain.pem" | cut -d' ' -f1)"
new_key_sum="$(sha256sum "${WORKDIR}/privkey.pem" | cut -d' ' -f1)"

cur_cert_sum="none"
cur_key_sum="none"
[ -f "${CERT_DIR}/fullchain.pem" ] && cur_cert_sum="$(sha256sum "${CERT_DIR}/fullchain.pem" | cut -d' ' -f1)"
[ -f "${CERT_DIR}/privkey.pem" ]   && cur_key_sum="$(sha256sum "${CERT_DIR}/privkey.pem" | cut -d' ' -f1)"

if [ "${new_cert_sum}" = "${cur_cert_sum}" ] && [ "${new_key_sum}" = "${cur_key_sum}" ]; then
  log "сертификат не изменился — продление не требуется (действителен до $(openssl x509 -in "${CERT_DIR}/fullchain.pem" -noout -enddate | cut -d= -f2))"
  exit 0
fi

log "сертификат обновлён, устанавливаю файлы"
install -m 0644 "${WORKDIR}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
install -m 0600 "${WORKDIR}/privkey.pem" "${CERT_DIR}/privkey.pem"

# --- 4. Перечитать сертификат в nginx -----------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "ВНИМАНИЕ: нет команды docker — перезагрузите nginx вручную: docker exec ${NGINX_CONTAINER} nginx -s reload"
  exit 0
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${NGINX_CONTAINER}"; then
  log "ВНИМАНИЕ: контейнер ${NGINX_CONTAINER} не запущен — сертификат обновлён, nginx перечитает его при следующем старте"
  exit 0
fi

docker exec "${NGINX_CONTAINER}" nginx -t || fail "конфигурация nginx не проходит проверку"
docker exec "${NGINX_CONTAINER}" nginx -s reload || fail "не удалось перезагрузить nginx"
log "nginx перечитал сертификат (новый срок до $(openssl x509 -in "${CERT_DIR}/fullchain.pem" -noout -enddate | cut -d= -f2))"
