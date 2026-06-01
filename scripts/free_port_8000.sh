#!/usr/bin/env bash
# Освободить 127.0.0.1:8000 на VPS. Запуск: bash scripts/free_port_8000.sh (из каталога web_kp)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Останавливаем compose ==="
docker-compose down --remove-orphans 2>/dev/null || docker compose down --remove-orphans 2>/dev/null || true

echo "=== Удаляем контейнеры kp-app и всё на порту 8000 ==="
docker rm -f kp-app 2>/dev/null || true
docker ps -aq --filter "name=kp-app" | xargs -r docker rm -f 2>/dev/null || true
docker ps -aq --filter "publish=8000" | xargs -r docker rm -f 2>/dev/null || true

while read -r cid; do
  [[ -z "$cid" ]] && continue
  if docker port "$cid" 2>/dev/null | grep -q ':8000'; then
    echo "rm container $cid (uses 8000)"
    docker rm -f "$cid" 2>/dev/null || true
  fi
done < <(docker ps -aq 2>/dev/null || true)

echo "=== Процессы на хосте (не Docker) ==="
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp 2>/dev/null || true
fi
pkill -f "uvicorn main:app" 2>/dev/null || true

if command -v ss >/dev/null 2>&1 && ss -tlnp 2>/dev/null | grep -q ':8000 '; then
  echo "Порт 8000 ещё занят:"
  ss -tlnp | grep ':8000 ' || true
  pid="$(ss -tlnp 2>/dev/null | sed -n 's/.*:8000 .*pid=\([0-9]*\).*/\1/p' | head -1)"
  if [[ -n "${pid:-}" ]]; then
    echo "kill -9 $pid"
    kill -9 "$pid" 2>/dev/null || true
  fi
fi

sleep 2
if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
  echo "ERROR: порт 8000 всё ещё занят — пришлите: ss -tlnp | grep 8000" >&2
  exit 1
fi
echo "OK: порт 8000 свободен"
