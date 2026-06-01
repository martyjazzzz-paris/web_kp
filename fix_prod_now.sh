#!/bin/sh
# Одной командой с Mac: залить всё + перезапуск + диагностика.
# cd ~/Projects/BOT/web_kp && ./fix_prod_now.sh
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
HOST="root@72.56.237.74"
REMOTE="/root/BOT/web_kp"

echo "=== Локально ==="
grep -m1 'design-version' static/styles.css
grep -m1 'design-mark' static/styles.css

echo ""
echo "=== rsync ==="
rsync -avz static/ "$HOST:$REMOTE/static/"
rsync -avz templates/ "$HOST:$REMOTE/templates/"
rsync -avz docker-compose.yml main.py "$HOST:$REMOTE/"
rsync -avz scripts/free_port_8000.sh "$HOST:$REMOTE/scripts/" 2>/dev/null || true

echo ""
echo "=== на сервере: docker (без --force-recreate — иначе ContainerConfig) ==="
ssh "$HOST" "set -e
cd $REMOTE
mkdir -p scripts data
echo '--- файл на диске ---'
grep -m1 design-version static/styles.css
grep -m1 design-mark static/styles.css
grep 'styles.css?v=' templates/index.html | head -1
echo '--- убираем старый bbf3029154c0_kp-app и др. ---'
docker-compose down --remove-orphans 2>/dev/null || docker compose down --remove-orphans 2>/dev/null || true
docker ps -aq --filter name=kp-app | xargs -r docker rm -f 2>/dev/null || true
docker rm -f kp-app bbf3029154c0_kp-app 2>/dev/null || true
if [ -f scripts/free_port_8000.sh ]; then bash scripts/free_port_8000.sh; else fuser -k 8000/tcp 2>/dev/null || true; sleep 2; fi
echo '--- docker up (новый контейнер) ---'
if docker compose version >/dev/null 2>&1; then
  docker compose up -d
else
  docker-compose up -d
fi
sleep 4
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'kp|NAMES'
echo '--- CSS внутри контейнера ---'
docker exec kp-app grep -m1 design-version /app/static/styles.css
echo '--- backend :8000 ---'
curl -sS http://127.0.0.1:8000/static/styles.css | grep -m1 design-version
curl -sS http://127.0.0.1:8000/ | grep -o 'styles.css?v=[0-9]*' | head -1
"

echo ""
echo "=== снаружи ==="
curl -sS -L "http://72.56.237.74/static/styles.css" | grep -E 'design-version|design-mark' | head -3
curl -sS -L "http://72.56.237.74/" | grep -o 'styles.css?v=[0-9]*' | head -1
echo ""
echo "Safari: http://72.56.237.74/ Cmd+Shift+R"
