#!/usr/bin/env bash
# Быстрый деплой только static + templates + перезапуск Docker.
# Нужен: brew install hudochenkov/sshpass/sshpass
set -euo pipefail

echo "=== deploy_quick $(date '+%H:%M:%S') ==="

HOST="root@72.56.237.74"
REMOTE="/root/BOT/web_kp"
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "${DEPLOY_PASS:-}" ]]; then
  echo 'Сначала: export DEPLOY_PASS="ваш_пароль"' >&2
  exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Установите sshpass (иначе скрипт зависает на пароле):" >&2
  echo "  brew install hudochenkov/sshpass/sshpass" >&2
  exit 1
fi

export SSHPASS="${DEPLOY_PASS}"
SSH_E=(sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20)

grep -Fq '.top-split' "${SRC}/static/styles.css" || { echo "Локально нет нового CSS"; exit 1; }
VER="$(sed -n 's/.*--design-version:[[:space:]]*\([0-9]*\).*/\1/p' "${SRC}/static/styles.css" | head -1)"
echo "Локальный дизайн: v${VER}"

echo ">>> SSH test"
"${SSH_E[@]}" "$HOST" "echo SSH_OK"

echo ">>> rsync static"
sshpass -e rsync -avz --progress \
  -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20" \
  "${SRC}/static/" "${HOST}:${REMOTE}/static/"

echo ">>> rsync templates"
sshpass -e rsync -avz --progress \
  -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20" \
  "${SRC}/templates/" "${HOST}:${REMOTE}/templates/"

echo ">>> rsync docker-compose.yml"
sshpass -e rsync -avz \
  -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20" \
  "${SRC}/docker-compose.yml" "${HOST}:${REMOTE}/"

echo ">>> проверка файлов на сервере"
"${SSH_E[@]}" "$HOST" "grep -m1 'design-version' ${REMOTE}/static/styles.css; grep -m1 'top-split' ${REMOTE}/static/styles.css; grep 'styles.css?v=' ${REMOTE}/templates/index.html | head -1"

echo ">>> docker recreate"
"${SSH_E[@]}" "$HOST" "cd ${REMOTE} && \
  (docker compose up -d --force-recreate 2>/dev/null || docker-compose up -d --force-recreate)"

echo ">>> проверка с интернета"
sleep 3
curl -sS --connect-timeout 15 "http://72.56.237.74/static/styles.css" | grep -E 'design-version|\.top-split' | head -3 || true
curl -sS --connect-timeout 15 "http://72.56.237.74/" | grep -o 'styles.css?v=[0-9]*' | head -1 || true
echo "Готово. Откройте http://72.56.237.74/ с Cmd+Shift+R"
