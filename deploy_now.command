#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export DEPLOY_PASS="${DEPLOY_PASS:-}"
if [[ -z "$DEPLOY_PASS" ]]; then
  osascript -e 'display dialog "Сначала в Terminal:\nexport DEPLOY_PASS=\"ваш пароль\"\n\nПотом снова двойной клик или: ./deploy.sh" buttons {"OK"} default button 1'
  exit 1
fi
exec ./deploy.sh
