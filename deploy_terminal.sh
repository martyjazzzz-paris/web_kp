#!/bin/sh
# Деплой v60 из Terminal (Mac). Скопируйте команды ниже целиком.
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "KP deploy — v60"
echo "Папка: $ROOT"

if [ -z "${DEPLOY_PASS:-}" ]; then
  printf "Пароль root: "
  stty -echo 2>/dev/null || true
  read -r DEPLOY_PASS
  stty echo 2>/dev/null || true
  echo ""
  export DEPLOY_PASS
fi

export DISPLAY="${DISPLAY:-:0}"
exec /bin/sh "$ROOT/deploy_askpass.sh"
