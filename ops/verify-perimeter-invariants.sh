#!/usr/bin/env bash
# Проверка инвариантов периметра (reverse proxy) — исполняемая форма спецификации
# docs/SERVER_ARCHITECTURE.md § Reverse proxy.
#
#   bash verify-perimeter-invariants.sh           # обычный запуск (из cron)
#   SKIP_LIVE=1 bash verify-perimeter-invariants.sh   # только статические проверки
#   NGINX_SRC=/tmp/fixture bash verify-perimeter-invariants.sh   # прогон на копии
#
# ЗАЧЕМ ЭТО, А НЕ РЕВЬЮ КОНФИГА.
# Конфигурация периметра сознательно не лежит в репозитории (ADR-0021 § 5), а
# требование «согласовать изменение до применения» предполагает вторую сторону,
# которой в single-operator модели нет: владелец согласовывает сам с собой.
# Поэтому риск закрывается не апрувом, а обнаружением — тем же способом, каким
# закрыли BUG-089: проверкой, которая падает в обе стороны, а не обещанием быть
# внимательнее. См. technical-debt-roadmap.md § 7.
#
# Молчание = здоров. Проблемы уходят в $ALERT_LOG тем же форматом, что пишет
# backup-watchdog.sh, чтобы оператор смотрел в одно место (Т-5 в ADR-0021).
# stdout печатается всегда — под cron он отбрасывается, а при ручном запуске
# даёт читаемый чек-лист.
#
# Host-специфики нет намеренно: хосты и апстрим-порты ВЫЧИСЛЯЮТСЯ (порты — из
# `docker compose port`, имена — из включённых vhost'ов), а не задаются
# константами. Инвариант 4 «порты читаются, а не вспоминаются» распространяется
# и на саму проверку — иначе она протухнет при первом же изменении порта.

set -uo pipefail

# cron даёт PATH без /usr/sbin, где лежит nginx. Тот же капкан, что поймали в
# backup-nginx-config.sh прогоном в `env -i`.
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

NGINX_SRC="${NGINX_SRC:-/etc/nginx}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/TG_parser}"
ALERT_LOG="${ALERT_LOG:-$HOME/backup-alert.log}"
HOST_OPS_COPY="${HOST_OPS_COPY:-$HOME/backup-nginx-config.sh}"
SKIP_LIVE="${SKIP_LIVE:-0}"
# certbot перевыпускает за 30 дней до истечения; 14 означает «продление уже
# просрочено», а не «скоро истечёт» — иначе тревога звучала бы каждый месяц.
CERT_MIN_DAYS="${CERT_MIN_DAYS:-14}"
# Инвариант 3 требует «таймаут в минутах, а не секундах». Дефолт nginx — 60s,
# и он молча обрезает длинные tool-call'ы; 120 — граница «минуты».
MCP_MIN_READ_TIMEOUT="${MCP_MIN_READ_TIMEOUT:-120}"

PROBLEMS=()
CHECKS_RUN=0

fail() { PROBLEMS+=("$1"); CHECKS_RUN=$((CHECKS_RUN + 1)); echo "FAIL  $1"; }
pass() { CHECKS_RUN=$((CHECKS_RUN + 1)); echo "ok    $1"; }
note() { echo "      $1"; }

# --- сбор фактов: какие апстримы опубликованы -------------------------------
# Пары "service:container_port". Контейнерный порт фиксирован, host-порт — нет
# (SERVER_ARCHITECTURE § Network topology), поэтому спрашиваем compose.
SERVICES="tg_parser:8000 mcp:8080 grafana:3000"

declare -A UPSTREAM      # service -> host:port, как его опубликовал compose
declare -A VHOST_FILE    # service -> путь к vhost'у, который на него проксирует
declare -A VHOST_NAME    # service -> server_name этого vhost'а

# Переопределяемо ради проверки: ветки «порт не на loopback» и «vhost разъехался
# с портом» иначе непроверяемы — пришлось бы менять публикацию портов на боевом
# хосте. Тот же приём, что NGINX_SRC/LE_SRC в backup-nginx-config.sh.
#   UPSTREAM_OVERRIDE="tg_parser=127.0.0.1:8000 mcp=127.0.0.1:8080 grafana=127.0.0.1:3001"
UPSTREAM_OVERRIDE="${UPSTREAM_OVERRIDE:-}"

lookup_override() {
    local svc="$1" pair
    for pair in $UPSTREAM_OVERRIDE; do
        [ "${pair%%=*}" = "$svc" ] && { echo "${pair#*=}"; return; }
    done
}

collect_upstreams() {
    local entry svc cport published
    for entry in $SERVICES; do
        svc="${entry%%:*}"
        cport="${entry##*:}"
        if [ -n "$UPSTREAM_OVERRIDE" ]; then
            published="$(lookup_override "$svc")"
        else
            published="$(cd "$PROJECT_DIR" 2>/dev/null && docker compose port "$svc" "$cport" 2>/dev/null | tr -d '\r')"
        fi
        if [ -z "$published" ]; then
            fail "апстрим $svc: \`docker compose port $svc $cport\` ничего не вернул (сервис не запущен или порт не опубликован)"
            continue
        fi
        UPSTREAM["$svc"]="$published"

        # Инвариант 1: апстримы только на loopback. Публикация на 0.0.0.0 выносит
        # сервис в интернет в обход терминатора — это дыра, а не стилистика.
        case "$published" in
            127.0.0.1:*|localhost:*|\[::1\]:*)
                pass "апстрим $svc опубликован на loopback ($published)" ;;
            *)
                fail "апстрим $svc опубликован НЕ на loopback: $published — сервис доступен в обход reverse proxy" ;;
        esac
    done
}

# --- сопоставление vhost'ов с апстримами ------------------------------------
# -R, не -r: sites-enabled состоит из симлинков, а -r по ним не идёт.
map_vhosts() {
    local enabled_dir="$NGINX_SRC/sites-enabled"
    if [ ! -d "$enabled_dir" ]; then
        fail "каталог $enabled_dir не найден — конфигурация nginx не читается"
        return
    fi

    local svc target port f
    for svc in "${!UPSTREAM[@]}"; do
        target="${UPSTREAM[$svc]}"
        port="${target##*:}"
        # Ищем vhost, который проксирует именно на этот порт. Сопоставление по
        # порту, а не по имени файла: имена host-специфичны, порт — факт.
        f="$(grep -RlE "proxy_pass[[:space:]]+https?://(127\.0\.0\.1|localhost):${port}(/|;|[[:space:]])" \
             "$enabled_dir/" 2>/dev/null | head -1)"
        if [ -z "$f" ]; then
            fail "инвариант 1/4: ни один включённый vhost не проксирует на апстрим $svc ($target) — имя опубликовано, но не обслуживается, либо порт разъехался с конфигом"
            continue
        fi
        VHOST_FILE["$svc"]="$f"
        VHOST_NAME["$svc"]="$(grep -hE '^[[:space:]]*server_name[[:space:]]' "$f" 2>/dev/null \
            | head -1 | sed -E 's/^[[:space:]]*server_name[[:space:]]+//; s/;.*$//' \
            | tr ' ' '\n' | grep -vE '^(_|)$' | head -1)"
        if [ -z "${VHOST_NAME[$svc]}" ]; then
            fail "инвариант 1: vhost для $svc ($f) не имеет server_name"
        else
            pass "инвариант 1: $svc обслуживается vhost'ом ${VHOST_NAME[$svc]} ($(basename "$f"))"
        fi
    done
}

# --- инвариант 2: /metrics не публичен --------------------------------------
check_metrics_blocked() {
    local f="${VHOST_FILE[tg_parser]:-}"
    [ -z "$f" ] && return   # уже отмечено в map_vhosts

    # Статически: в API-vhost'е должен быть location /metrics, отдающий 403.
    # awk-диапазон, а не grep -P: -P собран не везде, а поведение диапазона
    # «от location до первой }» здесь достаточно и переносимо.
    if awk '/location[[:space:]]+\/metrics/,/}/' "$f" 2>/dev/null | grep -qE 'return[[:space:]]+403'; then
        pass "инвариант 2: /metrics в конфиге API-vhost'а отдаёт 403"
    else
        fail "инвариант 2: в API-vhost'е ($(basename "$f")) нет location /metrics с return 403 — метрики уходят в интернет"
    fi
}

check_metrics_live() {
    local host="${VHOST_NAME[tg_parser]:-}"
    [ -z "$host" ] && return

    # Проверка устойчива к падению приложения: `return 403` не ходит в апстрим,
    # поэтому 502 здесь означал бы, что правило исчезло, а не что API лежит.
    local code
    code="$(curl -sS -o /dev/null -m 15 -w '%{http_code}' "https://$host/metrics" 2>/dev/null)"
    case "$code" in
        403) pass "инвариант 2 (живой): https://$host/metrics → 403" ;;
        200) fail "инвариант 2 (живой): https://$host/metrics → 200 — МЕТРИКИ ОТДАЮТСЯ В ИНТЕРНЕТ" ;;
        000) fail "инвариант 2 (живой): https://$host/metrics недоступен (нет ответа/TLS) — периметр не отвечает" ;;
        *)   fail "инвариант 2 (живой): https://$host/metrics → $code, ожидался 403" ;;
    esac
}

# --- инвариант 3: MCP не ломает стриминг ------------------------------------
check_mcp_streaming() {
    local f="${VHOST_FILE[mcp]:-}"
    [ -z "$f" ] && return

    grep -qE '^[[:space:]]*proxy_http_version[[:space:]]+1\.1[[:space:]]*;' "$f" \
        && pass "инвариант 3: MCP-vhost использует HTTP/1.1" \
        || fail "инвариант 3: в MCP-vhost'е ($(basename "$f")) нет proxy_http_version 1.1 — стриминг деградирует до HTTP/1.0"

    grep -qE '^[[:space:]]*proxy_set_header[[:space:]]+Upgrade[[:space:]]' "$f" \
        && pass "инвариант 3: MCP-vhost пробрасывает Upgrade" \
        || fail "инвариант 3: в MCP-vhost'е ($(basename "$f")) не пробрасывается заголовок Upgrade"

    grep -qE '^[[:space:]]*proxy_buffering[[:space:]]+off[[:space:]]*;' "$f" \
        && pass "инвариант 3: у MCP-vhost'а буферизация ответа выключена" \
        || fail "инвариант 3: в MCP-vhost'е ($(basename "$f")) нет proxy_buffering off — nginx буферизует SSE, события доходят пачками (спецификация: SERVER_ARCHITECTURE § Reverse proxy, инвариант 3; рецепт: PRODUCTION_DEPLOYMENT.md § Option B)"

    local t
    t="$(grep -hE '^[[:space:]]*proxy_read_timeout[[:space:]]' "$f" 2>/dev/null \
        | head -1 | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
    if [ -z "$t" ]; then
        fail "инвариант 3: в MCP-vhost'е ($(basename "$f")) не задан proxy_read_timeout — дефолтные 60s молча обрезают длинные tool-call'ы"
    elif [ "$t" -lt "$MCP_MIN_READ_TIMEOUT" ]; then
        fail "инвариант 3: proxy_read_timeout у MCP = ${t}s, требуются минуты (>= ${MCP_MIN_READ_TIMEOUT}s)"
    else
        pass "инвариант 3: proxy_read_timeout у MCP = ${t}s"
    fi
}

# --- инвариант 5: сертификаты ------------------------------------------------
check_certs() {
    local svc host seen="" end_date end_epoch now_epoch days
    for svc in "${!VHOST_NAME[@]}"; do
        host="${VHOST_NAME[$svc]}"
        [ -z "$host" ] && continue
        case " $seen " in *" $host "*) continue ;; esac
        seen="$seen $host"

        end_date="$(echo | timeout 15 openssl s_client -connect "$host:443" -servername "$host" 2>/dev/null \
            | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
        if [ -z "$end_date" ]; then
            fail "инвариант 5: не удалось прочитать сертификат $host — TLS не отвечает"
            continue
        fi
        end_epoch="$(date -d "$end_date" +%s 2>/dev/null)"
        now_epoch="$(date +%s)"
        if [ -z "$end_epoch" ]; then
            fail "инвариант 5: дата истечения сертификата $host не разобрана ($end_date)"
            continue
        fi
        days=$(( (end_epoch - now_epoch) / 86400 ))
        if [ "$days" -lt "$CERT_MIN_DAYS" ]; then
            fail "инвариант 5: сертификат $host истекает через ${days}д (порог ${CERT_MIN_DAYS}д) — автопродление certbot не сработало"
        else
            pass "инвариант 5: сертификат $host действителен ещё ${days}д"
        fi
    done
}

# --- дрейф копии репозиторного скрипта --------------------------------------
# Единственная копия, происходящая из репозитория и живущая на хосте. Остальные
# host-скрипты не версионируются вовсе (см. § 7, остаточное).
check_ops_copy_drift() {
    local repo_copy="$PROJECT_DIR/ops/backup-nginx-config.sh"
    if [ ! -f "$HOST_OPS_COPY" ] || [ ! -f "$repo_copy" ]; then
        note "проверка дрейфа пропущена: нет $HOST_OPS_COPY или $repo_copy"
        return
    fi
    if [ "$(sha256sum <"$HOST_OPS_COPY" | cut -d' ' -f1)" = "$(sha256sum <"$repo_copy" | cut -d' ' -f1)" ]; then
        pass "копия backup-nginx-config.sh на хосте совпадает с репозиторной"
    else
        fail "копия $HOST_OPS_COPY разошлась с $repo_copy — на хосте работает не тот скрипт, что в git"
    fi
}

# --- прогон ------------------------------------------------------------------
echo "Проверка инвариантов периметра — $(date '+%F %T')"
echo "  спецификация: docs/SERVER_ARCHITECTURE.md § Reverse proxy"
echo

collect_upstreams
map_vhosts
check_metrics_blocked
check_mcp_streaming
check_ops_copy_drift

if [ "$SKIP_LIVE" != "1" ]; then
    check_metrics_live
    check_certs
else
    note "живые проверки пропущены (SKIP_LIVE=1)"
fi

echo
if [ ${#PROBLEMS[@]} -eq 0 ]; then
    echo "Инварианты соблюдены ($CHECKS_RUN проверок)."
    exit 0
fi

# Формат строки повторяет backup-watchdog.sh, чтобы всё лежало в одном канале.
for p in "${PROBLEMS[@]}"; do
    echo "$(date '+%F %T') ТРЕВОГА: периметр — $p" >> "$ALERT_LOG"
done

echo "Нарушено инвариантов: ${#PROBLEMS[@]} из $CHECKS_RUN проверок. Записано в $ALERT_LOG."
exit 1
