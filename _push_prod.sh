#!/usr/bin/env bash
set -euo pipefail
export SSH_ASKPASS=/Users/martyjazz/Projects/BOT/.deploy_askpass.sh
export SSH_ASKPASS_REQUIRE=force
export DISPLAY=:0
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password -o PubkeyAuthentication=no)
rsync -avz \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.db' \
  --exclude '.env' \
  -e "ssh ${SSH_OPTS[*]}" \
  /Users/martyjazz/Projects/BOT/web_kp/ root@72.56.237.74:/root/BOT/web_kp/
ssh "${SSH_OPTS[@]}" root@72.56.237.74 'cd /root/BOT/web_kp && docker compose up -d --build && docker compose ps'
