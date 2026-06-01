#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${DEPLOY_PASS:-}" ]]; then
  osascript -e 'display dialog "В Terminal:\nexport DEPLOY_PASS=\"ваш пароль\"\n./deploy.sh" buttons {"OK"} default button 1'
  exit 1
fi
exec ./deploy.sh
