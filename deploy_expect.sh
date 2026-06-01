#!/usr/bin/expect -f
# export DEPLOY_PASS='пароль' && /usr/bin/expect -f deploy_expect.sh

set timeout 45
log_user 1
match_max 100000

proc say {msg} {
  puts $msg
  flush stdout
}

if {![info exists env(DEPLOY_PASS)] || $env(DEPLOY_PASS) eq ""} {
  say "export DEPLOY_PASS='пароль root'"
  exit 1
}

set pass $env(DEPLOY_PASS)
set host "72.56.237.74"
set remote "/root/BOT/web_kp"
set src [file dirname [info script]]

set ssh_base [list ssh \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=15 \
  -o ServerAliveInterval=10 \
  -o ServerAliveCountMax=3 \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o PasswordAuthentication=yes \
  -o KbdInteractiveAuthentication=no \
  -o IdentitiesOnly=yes \
  -o IdentityFile=/dev/null \
  -o NumberOfPasswordPrompts=1]

set rsync_ssh "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o PasswordAuthentication=yes -o IdentitiesOnly=yes -o IdentityFile=/dev/null"

set fp [open "$src/static/styles.css" r]
set css [read $fp]
close $fp

if {[string first "v60-top-split" $css] < 0} {
  say "Локально нет v60. Останов."
  exit 1
}
if {![regexp -- {--design-version:[ \t]*([0-9]+)} $css _ design_ver]} {
  say "Нет --design-version в styles.css"
  exit 1
}

say "=== Деплой v$design_ver на $host ==="
say "(если тишина >45с — сервер/SSH не отвечает; Ctrl+C)"

proc wait_ok {label} {
  catch wait result
  set code [lindex $result 3]
  if {$code != 0 && $code != ""} {
    say "ОШИБКА $label, код $code"
    exit 1
  }
}

# Ждём пароль и/или конец сессии. Не выходим по eof до таймаута, пока идёт docker.
proc session {pass {allow_long 0}} {
  global timeout
  if {$allow_long} {
    set timeout 300
    say "  (docker до 5 мин — смотрите вывод ниже)"
  }
  expect {
    -re -nocase "password:" {
      say "  → пароль отправлен"
      flush stdout
      send -- "$pass\r"
      exp_continue
    }
    -re "(?i)permission denied" {
      say "\nНеверный DEPLOY_PASS"
      exit 1
    }
    -re "(?i)too many authentication failures" {
      say "\nSSH заблокировал попытки — подождите 3 мин"
      exit 1
    }
    -re "(?i)connection timed out|operation timed out|no route to host" {
      say "\nСервер $::host недоступен"
      exit 1
    }
    timeout {
      say "\nТаймаут ${timeout}с — нет ответа SSH/rsync"
      say "Проверьте вручную: ssh root@$::host echo OK"
      exit 1
    }
    eof
  }
  set timeout 45
}

say "\n(1/7) SSH тест..."
eval spawn $ssh_base root@$host "echo SSH_OK"
session $pass
wait_ok "ssh-test"

say "\n(2/7) rsync static..."
spawn rsync -avz --info=progress2 -e $rsync_ssh $src/static/ root@$host:$remote/static/
session $pass
wait_ok "static"

say "\n(3/7) rsync templates..."
spawn rsync -avz -e $rsync_ssh $src/templates/ root@$host:$remote/templates/
session $pass
wait_ok "templates"

say "\n(4/7) rsync main.py..."
spawn rsync -avz -e $rsync_ssh $src/main.py root@$host:$remote/main.py
session $pass
wait_ok "main.py"

say "\n(5/7) rsync docker-compose.yml..."
spawn rsync -avz -e $rsync_ssh $src/docker-compose.yml root@$host:$remote/docker-compose.yml
session $pass
wait_ok "compose"

say "\n(6/7) проверка файлов на сервере..."
eval spawn $ssh_base root@$host "set -e; cd $remote; grep -Fq 'design-version: $design_ver' static/styles.css; grep -Fq v60-top-split static/styles.css; grep -Fq top-split templates/index.html; grep -Fq './static:/app/static' docker-compose.yml; wc -c static/styles.css"
session $pass
wait_ok "remote-check"

say "\n(7/7) docker recreate (без build)..."
eval spawn $ssh_base root@$host "cd $remote && docker-compose down --remove-orphans 2>/dev/null || docker compose down --remove-orphans 2>/dev/null || true; docker ps -aq --filter name=kp-app | xargs -r docker rm -f 2>/dev/null || true; docker rm -f kp-app bbf3029154c0_kp-app 2>/dev/null || true; fuser -k 8000/tcp 2>/dev/null; sleep 2; (docker compose up -d 2>/dev/null || docker-compose up -d); docker ps --filter name=kp-app"
session $pass 1
wait_ok "docker"

say "\nПроверка сайта..."
set ok 0
for {set i 0} {$i < 8} {incr i} {
  sleep 2
  if {[catch {exec curl -sS --connect-timeout 10 -L http://72.56.237.74/static/styles.css} css_out]} {
    say "  curl попытка [expr {$i+1}]: нет ответа"
    flush stdout
    continue
  }
  if {[string first "design-version: $design_ver" $css_out] >= 0 && [string first "v60-top-split" $css_out] >= 0} {
    set ok 1
    say "VERIFY_OK — CSS v$design_ver на проде"
    break
  }
  say "  curl попытка [expr {$i+1}]: ещё старый CSS..."
  flush stdout
}

if {!$ok} {
  say "VERIFY_FAILED — залито, но снаружи старый CSS (кэш nginx?)"
  say "На сервере: grep design-version $remote/static/styles.css"
  exit 1
}

say "\n=== ГОТОВО ==="
say "http://72.56.237.74/  Cmd+Shift+R"
