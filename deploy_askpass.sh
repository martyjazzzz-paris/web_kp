#!/bin/sh
# Деплой без expect (Mac Terminal). export DEPLOY_PASS=... && ./deploy_askpass.sh
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
"${ROOT}/scripts/verify_baseline.sh" || exit 1

if [ -z "${DEPLOY_PASS:-}" ]; then
  echo "export DEPLOY_PASS='пароль root'" >&2
  exit 1
fi

HOST="root@72.56.237.74"
REMOTE="/root/BOT/web_kp"
VER=$(sed -n 's/.*--design-version:[[:space:]]*\([0-9]*\).*/\1/p' static/styles.css | head -1)
echo "=== Деплой v${VER} ==="

ASKPASS_SCRIPT="$(mktemp)"
chmod 700 "$ASKPASS_SCRIPT"
printf '%s\n' '#!/bin/sh' 'exec printf "%s\n" "$DEPLOY_PASS"' >"$ASKPASS_SCRIPT"
export SSH_ASKPASS="$ASKPASS_SCRIPT" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
trap 'rm -f "$ASKPASS_SCRIPT"' EXIT

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o IdentitiesOnly=yes -o IdentityFile=/dev/null -o BatchMode=no"
RSYNC_E="ssh $SSH_OPTS"

step() { echo ""; echo "=== $1 ==="; }

step "1 SSH"
ssh $SSH_OPTS "$HOST" "echo SSH_OK"

step "2 static"
rsync -avz -e "$RSYNC_E" static/ "$HOST:$REMOTE/static/"

step "3 templates"
rsync -avz -e "$RSYNC_E" templates/ "$HOST:$REMOTE/templates/"

step "4 main.py + compose"
rsync -avz -e "$RSYNC_E" main.py docker-compose.yml "$HOST:$REMOTE/"

step "5 проверка на сервере"
ssh $SSH_OPTS "$HOST" "grep -Fq 'design-version: $VER' $REMOTE/static/styles.css && grep -Fq v60-top-split $REMOTE/static/styles.css"

step "6 docker"
ssh $SSH_OPTS "$HOST" "cd $REMOTE && \
  docker-compose down --remove-orphans 2>/dev/null || docker compose down --remove-orphans 2>/dev/null || true; \
  docker ps -aq --filter name=kp-app | xargs -r docker rm -f 2>/dev/null || true; \
  docker rm -f kp-app bbf3029154c0_kp-app 2>/dev/null || true; \
  fuser -k 8000/tcp 2>/dev/null || true; sleep 2; \
  (docker compose up -d 2>/dev/null || docker-compose up -d)"

step "7 curl"
sleep 3
if curl -sS -L --connect-timeout 12 "http://72.56.237.74/static/styles.css" | grep -Fq "design-version: $VER"; then
  echo "VERIFY_OK v$VER — http://72.56.237.74/"
else
  echo "VERIFY_FAILED" >&2
  exit 1
fi
