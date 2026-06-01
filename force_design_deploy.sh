#!/usr/bin/env bash
# Заливает static/templates на прод и перезапускает kp-app.
# Рекомендуется: ./deploy.sh (expect, те же проверки + /health/design).
set -euo pipefail

echo "[deploy] старт $(date '+%H:%M:%S')" >&2

HOST="root@72.56.237.74"
REMOTE="/root/BOT/web_kp"
SRC="$(cd "$(dirname "$0")" && pwd)"
STYLES_CSS="${SRC}/static/styles.css"
INDEX_HTML="${SRC}/templates/index.html"

if [[ ! -f "${STYLES_CSS}" ]] || [[ ! -f "${INDEX_HTML}" ]]; then
  echo "Нет styles.css или templates/index.html в ${SRC}" >&2
  exit 1
fi

if [[ -z "${DEPLOY_PASS:-}" ]]; then
  echo "export DEPLOY_PASS='пароль root'" >&2
  exit 1
fi
export DEPLOY_PASS

if ! grep -Fq '.top-split' "${STYLES_CSS}"; then
  echo "Локальный CSS устарел: нет .top-split" >&2
  exit 1
fi
if ! grep -Fq '.btn-remove-row' "${STYLES_CSS}"; then
  echo "Локальный CSS устарел: нет .btn-remove-row" >&2
  exit 1
fi

DESIGN_VERSION="$(sed -n 's/.*--design-version:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "${STYLES_CSS}" | head -1)"
DESIGN_VERSION="${DESIGN_VERSION//$'\r'/}"
if [[ -z "${DESIGN_VERSION}" ]]; then
  echo "Нет --design-version в styles.css" >&2
  exit 1
fi
echo "[deploy] дизайн v${DESIGN_VERSION}" >&2

SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=20
  -o ServerAliveInterval=10
  -o ServerAliveCountMax=3
  -o PreferredAuthentications=password
  -o PubkeyAuthentication=no
)

ASKPASS_SCRIPT="$(mktemp)"
chmod 700 "$ASKPASS_SCRIPT"
_esc_pass="${DEPLOY_PASS//\'/\'\\\'\'}"
printf '%s\n' '#!/bin/sh' "printf '%s\\n' '${_esc_pass}'" >"$ASKPASS_SCRIPT"

SSH_RSH_BASE=(ssh "${SSH_OPTS[@]}")
if command -v sshpass >/dev/null 2>&1; then
  echo "[deploy] auth: sshpass" >&2
  export SSHPASS="${DEPLOY_PASS}"
  SSH_CMD=(sshpass -e ssh "${SSH_OPTS[@]}")
  RSYNC_RSH=(sshpass -e ssh "${SSH_OPTS[@]}")
else
  echo "[deploy] auth: SSH_ASKPASS (если зависло — brew install hudochenkov/sshpass/sshpass)" >&2
  export SSH_ASKPASS="$ASKPASS_SCRIPT"
  export SSH_ASKPASS_REQUIRE=force
  export DISPLAY="${DISPLAY:-:0}"
  SSH_CMD=("${SSH_RSH_BASE[@]}")
  RSYNC_RSH=("${SSH_RSH_BASE[@]}")
fi
trap 'rm -f "$ASKPASS_SCRIPT"' EXIT

echo "[deploy] проверка SSH…" >&2
if ! "${SSH_CMD[@]}" "$HOST" "echo SSH_OK" </dev/null; then
  echo "SSH не отвечает (таймаут 20 с или неверный пароль)" >&2
  exit 1
fi

rsync_do() {
  rsync -avz --progress -e "$(printf '%q ' "${RSYNC_RSH[@]}")" "$@"
}

echo "=== 1/4 rsync ===" >&2
rsync_do "${SRC}/static/" "${HOST}:${REMOTE}/static/"
rsync_do "${SRC}/templates/" "${HOST}:${REMOTE}/templates/"
rsync_do "${SRC}/docker-compose.yml" "${SRC}/main.py" "${SRC}/review_routes.py" "${HOST}:${REMOTE}/"
rsync_do "${SRC}/scripts/" "${HOST}:${REMOTE}/scripts/" 2>/dev/null || true

echo "=== 2/4 проверка на сервере ===" >&2
"${SSH_CMD[@]}" "$HOST" bash -s <<REMOTE_CHECK
set -euo pipefail
REMOTE="${REMOTE}"
grep -Fq '.top-split' "\${REMOTE}/static/styles.css"
grep -Fq '.btn-remove-row' "\${REMOTE}/static/styles.css"
grep -Fq 'design-version: ${DESIGN_VERSION}' "\${REMOTE}/static/styles.css"
grep -Fq 'styles.css?v=${DESIGN_VERSION}' "\${REMOTE}/templates/index.html"
echo "OK on disk: v${DESIGN_VERSION}"
wc -c "\${REMOTE}/static/styles.css"
REMOTE_CHECK

echo "=== 3/4 docker recreate ===" >&2
"${SSH_CMD[@]}" "$HOST" "cd ${REMOTE} && mkdir -p data && \
  bash scripts/free_port_8000.sh 2>/dev/null || true; \
  run_dc() { if command -v docker-compose >/dev/null 2>&1; then docker-compose \"\$@\"; else docker compose \"\$@\"; fi; }; \
  if ! grep -q './static:/app/static' docker-compose.yml; then \
    echo 'WARN: нет volume static в docker-compose.yml'; exit 1; \
  fi; \
  run_dc up -d --force-recreate"

echo "=== 4/4 проверка с интернета ===" >&2
sleep 4
VERIFY_OK=0
for _ in 1 2 3 4 5; do
  CSS="$(curl -sS --connect-timeout 15 "http://72.56.237.74/static/styles.css" || true)"
  if echo "$CSS" | grep -Fq '.top-split' && echo "$CSS" | grep -Fq "design-version: ${DESIGN_VERSION}"; then
    VERIFY_OK=1
    break
  fi
  sleep 2
done

VER=$(curl -sS --connect-timeout 15 "http://72.56.237.74/" 2>/dev/null | grep -o 'styles.css?v=[0-9]*' | head -1 || true)
if [[ "$VERIFY_OK" -eq 1 ]]; then
  echo "VERIFY_OK design v${DESIGN_VERSION}. HTML: ${VER:-?}"
  echo "http://72.56.237.74/ — Cmd+Shift+R"
else
  echo "VERIFY_FAILED" >&2
  exit 1
fi
