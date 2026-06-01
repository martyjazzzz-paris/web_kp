#!/bin/bash
# УСТАРЕЛО: раньше делал docker-compose up --build и откатывал дизайн.
# Используйте deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
osascript -e 'display alert "Скрипт отключён" message "restart_docker.command откатывал дизайн (docker build без rsync).\n\nВ Terminal:\nexport DEPLOY_PASS=\"пароль\"\n./deploy.sh" as critical'
exit 1
