#!/usr/bin/env bash
# Только на VPS в /root/BOT/web_kp — полная пересборка образа.
# НЕ использовать для смены дизайна с Mac: docker build подхватывает старый код с диска сервера.
# Для дизайна: на Mac → ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "WARN: rebuild может откатить UI, если static на сервере старый." >&2
echo "Для дизайна с Mac используйте ./deploy.sh" >&2
read -r -p "Продолжить rebuild на VPS? [y/N] " ans
[[ "${ans,,}" == "y" ]] || exit 0

if [[ ! -f .env ]]; then
  echo "Создайте .env из .env.example"
  exit 1
fi

docker compose down
docker compose build --no-cache
docker compose up -d

sleep 3
docker compose logs --tail=30 kp-app
