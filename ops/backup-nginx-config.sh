#!/usr/bin/env bash
# Еженедельный бэкап конфигурации reverse-proxy (system nginx + certbot).
# Подготовлен 2026-08-07 по technical-debt-roadmap § 7 (конфиги периметра живут вне репозитория).
#
#   bash backup-nginx-config.sh          # обычный запуск (из cron)
#   KEEP=20 bash backup-nginx-config.sh  # другая глубина хранения
#   FORCE=1 bash backup-nginx-config.sh  # снять копию даже если ничего не изменилось
#   DEST_DIR=/mnt/backups/nginx bash backup-nginx-config.sh
#
# Host-специфики в скрипте нет намеренно: имена сайтов вычитываются из самих
# vhost'ов, каталог назначения по умолчанию — $HOME/backups/nginx.
#
# Почему это нужно: публичный контур деплоя обслуживает СИСТЕМНЫЙ nginx, а не
# compose-сервис `caddy` (тот здесь никогда не запускался — см. BUG-090). Его
# конфигурация не под git, поэтому бэкап кода периметр не восстанавливает.
#
# Без sudo: `nginx -T` и `certbot certificates` требуют root, но исходные файлы
# читаемы всем и несут ту же информацию.
#
# Приватные ключи (/etc/letsencrypt/{live,archive}) НЕ сохраняются намеренно:
# root-only и не нужны — certbot перевыпускает сертификаты из renewal-конфигов.
#
# Спецификация, которой конфиг обязан удовлетворять:
#   TG_parser/docs/SERVER_ARCHITECTURE.md § Reverse proxy

set -uo pipefail   # без -e: при ошибке нужно дописать причину в лог

# cron даёт урезанный PATH (/usr/bin:/bin), в котором НЕТ /usr/sbin — а nginx
# лежит именно там. Без этой строки `nginx -v` под cron молча пишет
# "command not found" в service-state.txt. Проверено запуском в `env -i`.
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

DEST_DIR="${DEST_DIR:-$HOME/backups/nginx}"
LOG="${LOG:-$DEST_DIR/backup.log}"
KEEP="${KEEP:-8}"                       # 8 недель истории
FORCE="${FORCE:-0}"
STATE="$DEST_DIR/.last-content.sha256"  # отпечаток СОДЕРЖИМОГО, не архива
CHANGES_DIR="${CHANGES_DIR:-$DEST_DIR/changes}"   # diff'ы между версиями конфига
# Источники переопределяемы, чтобы поведение можно было проверить на копии, не
# трогая боевой /etc. Иначе ветку «конфиг изменился» невозможно протестировать.
NGINX_SRC="${NGINX_SRC:-/etc/nginx}"
LE_SRC="${LE_SRC:-/etc/letsencrypt}"
# Имена берём из включённых vhost'ов, а не из константы — иначе список протухнет
# при первом же новом сайте. Переопределяется через DOMAINS="a.example b.example".
# -R, не -r: sites-enabled состоит из симлинков, а -r по ним не идёт (даёт 0 строк).
DOMAINS="${DOMAINS:-$(grep -RhE '^[[:space:]]*server_name[[:space:]]' "$NGINX_SRC/sites-enabled/" 2>/dev/null \
    | sed -E 's/^[[:space:]]*server_name[[:space:]]+//; s/;.*$//' \
    | tr ' ' '\n' | grep -vE '^(_|)$' | sort -u | tr '\n' ' ')}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST_DIR" || exit 1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }

STAGE="$(mktemp -d "$DEST_DIR/.staging-XXXXXX")" || { log "FAIL: mktemp"; exit 1; }
trap 'rm -rf "$STAGE"' EXIT

# --- 1. конфигурация nginx -------------------------------------------------
mkdir -p "$STAGE/etc-nginx"
cp -a "$NGINX_SRC/nginx.conf" "$STAGE/etc-nginx/" 2>>"$LOG"
cp -a "$NGINX_SRC/conf.d" "$STAGE/etc-nginx/" 2>>"$LOG"
cp -a "$NGINX_SRC/sites-available" "$STAGE/etc-nginx/" 2>>"$LOG"
# какие vhost'ы РЕАЛЬНО включены — по sites-available это не восстановить
ls -l "$NGINX_SRC/sites-enabled/" > "$STAGE/etc-nginx/sites-enabled.symlinks.txt" 2>>"$LOG"

# --- 2. certbot: из чего перевыпускаются сертификаты ------------------------
mkdir -p "$STAGE/etc-letsencrypt"
cp -a "$LE_SRC/renewal" "$STAGE/etc-letsencrypt/" 2>>"$LOG"
cp -a "$LE_SRC/options-ssl-nginx.conf" "$STAGE/etc-letsencrypt/" 2>>"$LOG"

# Санити: без vhost'ов архив бессмысленен — не подменяем хорошую копию пустой.
if [ ! -s "$STAGE/etc-nginx/nginx.conf" ] || [ -z "$(ls -A "$STAGE/etc-nginx/sites-available" 2>/dev/null)" ]; then
    log "FAIL: nginx config unreadable or empty — keeping previous archive, nothing written"
    exit 1
fi

# --- 3. дедупликация по содержимому ----------------------------------------
# Хэш считаем по файлам, а не по .tar.gz: gzip пишет таймстамп, поэтому архивы
# с одинаковым содержимым всё равно отличались бы побайтово.
CONTENT_HASH="$(cd "$STAGE" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
if [ "$FORCE" != "1" ] && [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$CONTENT_HASH" ]; then
    log "unchanged (sha256=${CONTENT_HASH:0:12}) — new archive not created"
    exit 0
fi

# --- 3-bis. конфиг изменился — сказать об этом и показать ЧТО именно ---------
# Дешёвая замена ревью изменений: вторая копия конфига в git неизбежно разошлась
# бы с /etc/nginx (класс BUG-090), а здесь сравнение идёт с прошлым архивом, то
# есть источник правды остаётся один. Первый запуск изменением не считается —
# иначе сигнал начинается с ложной тревоги.
PREV_ARCHIVE="$(ls -1t "$DEST_DIR"/reverse-proxy-config-*.tar.gz 2>/dev/null | head -1)"
if [ -f "$STATE" ] && [ -n "$PREV_ARCHIVE" ]; then
    PREV_DIR="$(mktemp -d "$DEST_DIR/.prev-XXXXXX")" && {
        if tar -xzf "$PREV_ARCHIVE" -C "$PREV_DIR" 2>>"$LOG"; then
            # Волатильные файлы из сравнения исключаем: сроки сертификата и
            # uptime меняются сами, а тревожить должен только конфиг.
            mkdir -p "$CHANGES_DIR"
            DIFF_FILE="$CHANGES_DIR/config-changed-$TS.diff"
            if diff -ruN \
                 --exclude=tls-inventory.txt \
                 --exclude=service-state.txt \
                 --exclude=MANIFEST.txt \
                 "$PREV_DIR" "$STAGE" > "$DIFF_FILE" 2>/dev/null; then
                # различий вне волатильных файлов нет — файл не нужен
                rm -f "$DIFF_FILE"
            else
                CHANGED_FILES="$(grep -c '^diff -ruN' "$DIFF_FILE" 2>/dev/null || echo 0)"
                log "CHANGED: конфигурация периметра изменилась с $(basename "$PREV_ARCHIVE" | sed 's/reverse-proxy-config-//; s/\.tar\.gz//'), файлов затронуто: $CHANGED_FILES — см. $DIFF_FILE"
                grep '^diff -ruN' "$DIFF_FILE" 2>/dev/null | sed 's#.*/\.staging-[^/]*/#  ~ #' | while read -r l; do log "$l"; done
            fi
        else
            log "WARN: прошлый архив не распаковался, diff не построен"
        fi
        rm -rf "$PREV_DIR"
    }
fi

# --- 4. волатильные данные: только ПОСЛЕ проверки на изменения --------------
# (иначе меняющиеся сроки сертификата ломали бы дедупликацию каждую неделю)
{
    for d in $DOMAINS; do
        echo "### $d"
        echo | openssl s_client -connect "$d":443 -servername "$d" 2>/dev/null \
            | openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null
        echo
    done
} > "$STAGE/tls-inventory.txt" 2>>"$LOG"

{ nginx -v; systemctl is-active nginx; systemctl list-timers certbot.timer --no-pager; } \
    > "$STAGE/service-state.txt" 2>&1

cat > "$STAGE/MANIFEST.txt" <<EOF
TG_parser — reverse-proxy configuration backup
Taken: $TS (UTC)   Host: $(hostname)   By: backup-nginx-config.sh (weekly cron)

WHY
  The public perimeter of this deployment is a SYSTEM nginx (not the Compose
  "caddy" service, which has never run here — see BUG-090). Its configuration
  lives outside the git repository, so a code backup does not restore it.

WHAT IS INSIDE
  etc-nginx/nginx.conf, conf.d/, sites-available/   full perimeter configuration
  etc-nginx/sites-enabled.symlinks.txt              which vhosts are actually live
  etc-letsencrypt/renewal/, options-ssl-nginx.conf  what certbot re-issues from
  tls-inventory.txt                                 live issuer / validity / SANs
  service-state.txt                                 nginx version, unit, certbot.timer

WHAT IS **NOT** INSIDE (deliberately)
  Private keys and issued certificates (/etc/letsencrypt/{live,archive}) — root-only
  and not needed: certbot re-issues them from the renewal configs above.

RESTORE
  1. apt install nginx certbot python3-certbot-nginx
  2. Restore etc-nginx/* to /etc/nginx/; recreate the symlinks listed in
     sites-enabled.symlinks.txt.
  3. Restore etc-letsencrypt/renewal/* then: certbot renew --force-renewal
     (or certbot certonly --nginx -d <domains>).
  4. nginx -t && systemctl reload nginx
  5. Re-check the invariants in docs/SERVER_ARCHITECTURE.md § Reverse proxy:
     /metrics on the API host must answer 403; MCP must keep streaming alive.
EOF

# --- 5. упаковка и ротация --------------------------------------------------
ARCHIVE="$DEST_DIR/reverse-proxy-config-$TS.tar.gz"
if ! tar -czf "$ARCHIVE" -C "$STAGE" . 2>>"$LOG"; then
    log "FAIL: tar failed, removing partial archive"
    rm -f "$ARCHIVE"
    exit 1
fi
chmod 600 "$ARCHIVE"

if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
    log "FAIL: archive did not verify, removing"
    rm -f "$ARCHIVE"
    exit 1
fi

echo "$CONTENT_HASH" > "$STATE"
log "OK $(basename "$ARCHIVE") ($(stat -c%s "$ARCHIVE") bytes, $(tar -tzf "$ARCHIVE" | wc -l) entries, sha256=${CONTENT_HASH:0:12})"

# ротация: держим KEEP самых свежих
ls -1t "$DEST_DIR"/reverse-proxy-config-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old" && log "pruned $(basename "$old")"
done
# diff'ы живут по тому же правилу, что и архивы
ls -1t "$CHANGES_DIR"/config-changed-*.diff 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"
done

exit 0
