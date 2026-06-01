#!/bin/bash
# Двойной клик в Finder — деплой v60 без ручного Terminal.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:$PATH"

osascript -e 'display notification "Старт деплоя v60…" with title "KP Deploy"'

if [[ -z "${DEPLOY_PASS:-}" ]]; then
  DEPLOY_PASS="$(osascript -e 'display dialog "Пароль root для 72.56.237.74:" default answer "" with hidden answer buttons {"Отмена", "OK"} default button "OK"' -e 'text returned of result' 2>/dev/null || true)"
  if [[ -z "${DEPLOY_PASS:-}" ]]; then
    osascript -e 'display alert "Отменено" message "Пароль не введён."'
    exit 1
  fi
  export DEPLOY_PASS
fi

LOG="/tmp/kp-deploy-$(date +%Y%m%d-%H%M%S).log"
if /usr/bin/expect -f "$ROOT/deploy_expect.sh" >"$LOG" 2>&1; then
  osascript -e 'display alert "Готово" message "v60 на http://72.56.237.74/\nВ Safari: Cmd+Shift+R" as informational'
  open "http://72.56.237.74/"
else
  ERR="$(tail -20 "$LOG" | sed 's/"/\\"/g')"
  osascript -e "display alert \"Ошибка деплоя\" message \"$ERR\n\nЛог: $LOG\" as critical"
  open -a TextEdit "$LOG"
  exit 1
fi
