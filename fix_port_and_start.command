#!/bin/bash
cd "$(dirname "$0")"
read -rsp "Пароль root VPS: " DEPLOY_PASS
echo ""
export DEPLOY_PASS
ASKPASS="$(mktemp)"
chmod 700 "$ASKPASS"
printf '%s\n' '#!/bin/sh' 'printf "%s\n" "$DEPLOY_PASS"' >"$ASKPASS"
export SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
trap 'rm -f "$ASKPASS"' EXIT

ssh -o StrictHostKeyChecking=no root@72.56.237.74 'bash -s' <<'REMOTE'
set -euo pipefail
cd /root/BOT/web_kp
bash scripts/free_port_8000.sh
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d --force-recreate
else
  docker compose up -d --force-recreate
fi
docker ps --filter name=kp-app
curl -sS http://127.0.0.1:8000/ -o /dev/null -w "backend HTTP %{http_code}\n" || true
REMOTE

echo ""
curl -sS --connect-timeout 10 "http://72.56.237.74/static/styles.css" | grep -q 'card-radius: 32px' \
  && echo "Дизайн на проде OK" || echo "CSS ещё старый — запустите force_design_deploy.sh"
read -p "Enter..."
