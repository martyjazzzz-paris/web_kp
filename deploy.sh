#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ -z "${DEPLOY_PASS:-}" ]; then
  echo "export DEPLOY_PASS='пароль root'"
  exit 1
fi
export DISPLAY="${DISPLAY:-:0}"
exec /bin/sh ./deploy_askpass.sh
