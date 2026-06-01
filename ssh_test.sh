#!/bin/sh
# Быстрая проверка SSH (10–20 с). export DEPLOY_PASS=... && ./ssh_test.sh
cd "$(dirname "$0")" || exit 1
if [ -z "${DEPLOY_PASS:-}" ]; then
  echo "export DEPLOY_PASS='пароль'"
  exit 1
fi
exec /usr/bin/expect -f - <<'EXPECT'
set timeout 20
log_user 1
set pass $env(DEPLOY_PASS)
set host "72.56.237.74"
puts "Проверка SSH $host (20с)..."
flush stdout
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=12 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o IdentitiesOnly=yes -o IdentityFile=/dev/null root@$host "echo SSH_OK && grep -m1 design-version /root/BOT/web_kp/static/styles.css"
expect {
  -re -nocase "password:" { send -- "$pass\r"; exp_continue }
  timeout { puts "\nТАЙМАУТ — сервер не отвечает"; exit 1 }
  eof
}
catch wait r
exit [lindex $r 3]
EXPECT
