#!/bin/sh
set -eu
[ -n "${DEPLOY_PASS:-}" ] || { echo "Нет DEPLOY_PASS"; exit 1; }
ASKPASS_SCRIPT="$(mktemp)"
chmod 700 "$ASKPASS_SCRIPT"
printf '%s\n' '#!/bin/sh' 'exec printf "%s\n" "$DEPLOY_PASS"' >"$ASKPASS_SCRIPT"
export SSH_ASKPASS="$ASKPASS_SCRIPT" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
trap 'rm -f "$ASKPASS_SCRIPT"' EXIT
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=12 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  -o IdentitiesOnly=yes -o IdentityFile=/dev/null -o BatchMode=no \
  root@72.56.237.74 "echo SSH_OK; grep -m1 design-version /root/BOT/web_kp/static/styles.css"
