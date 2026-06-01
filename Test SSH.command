#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [[ -z "${DEPLOY_PASS:-}" ]]; then
  DEPLOY_PASS="$(osascript -e 'display dialog "Пароль root для 72.56.237.74:" default answer "" with hidden answer buttons {"Отмена", "OK"} default button "OK"' -e 'text returned of result' 2>/dev/null || true)"
  export DEPLOY_PASS
fi

LOG="/tmp/kp-ssh-test.log"
if "$ROOT/ssh_test.sh" >"$LOG" 2>&1; then
  MSG="$(tail -6 "$LOG" | tr '\n' ' ')"
  osascript -e "display alert \"SSH OK\" message \"$MSG\" as informational"
else
  osascript -e "display alert \"SSH не отвечает\" message \"См. лог в TextEdit\" as critical"
  open -a TextEdit "$LOG"
fi
