#!/usr/bin/env bash
# Деплой БЕЗ sshpass/brew — пароль спросит 3–4 раза вручную.
set -euo pipefail

cd "$(dirname "$0")"
HOST="root@72.56.237.74"
REMOTE="/root/BOT/web_kp"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30"

echo "Пароль root вводите когда SSH/rsync спросит (несколько раз)."
echo "Локальный дизайн: $(grep 'design-version' static/styles.css | head -1)"
echo ""

echo "=== 1/4 rsync static ==="
rsync -avz -e "$SSH" static/ "${HOST}:${REMOTE}/static/"

echo "=== 2/4 rsync templates + compose ==="
rsync -avz -e "$SSH" templates/ "${HOST}:${REMOTE}/templates/"
rsync -avz -e "$SSH" docker-compose.yml "${HOST}:${REMOTE}/"

echo "=== 3/4 docker restart ==="
$SSH "${HOST}" "cd ${REMOTE} && docker rm -f kp-app 2>/dev/null; (docker compose up -d 2>/dev/null || docker-compose up -d)"

echo "=== 4/4 проверка ==="
sleep 3
curl -s http://72.56.237.74/static/styles.css | grep -E 'design-version|top-split' | head -3 || true
curl -s http://72.56.237.74/ | grep -o 'styles.css?v=[0-9]*' | head -1 || true
echo "Готово: http://72.56.237.74/ — Cmd+Shift+R"
