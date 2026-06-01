#!/usr/bin/env bash
# Запуск на сервере: bash /root/BOT/web_kp/scripts/recover_incoming_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Файлы БД на хосте ==="
ls -la web_kp.db data/web_kp.db 2>/dev/null || true

echo "=== Старые контейнеры kp-app (если остались) ==="
docker ps -a --filter name=kp-app --format '{{.ID}} {{.Status}} {{.CreatedAt}}' || true

OLD_CID="$(docker ps -aq --filter name=kp-app | head -1)"
if [[ -n "${OLD_CID}" ]]; then
  echo "=== Пробуем вытащить БД из контейнера ${OLD_CID} ==="
  mkdir -p data
  for path in /app/data/web_kp.db /app/web_kp.db; do
    if docker exec "${OLD_CID}" test -f "${path}" 2>/dev/null; then
      docker cp "${OLD_CID}:${path}" data/web_kp.db.recovered
      echo "Скопировано: ${path} -> data/web_kp.db.recovered"
      ls -la data/web_kp.db.recovered
    fi
  done
fi

if [[ -f data/web_kp.db.recovered && ! -f data/web_kp.db ]]; then
  mv data/web_kp.db.recovered data/web_kp.db
  echo "Восстановлено: data/web_kp.db"
fi

if [[ -f data/web_kp.db ]]; then
  echo "=== Черновики в data/web_kp.db ==="
  sqlite3 data/web_kp.db "SELECT COUNT(*) AS drafts FROM quote_drafts;" 2>/dev/null || echo "(sqlite3 не установлен)"
else
  echo "Файл data/web_kp.db не найден — черновики только через повторный ingest почты."
fi
