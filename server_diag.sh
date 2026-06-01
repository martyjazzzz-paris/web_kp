#!/usr/bin/env bash
# Запустить НА СЕРВЕРЕ в каталоге web_kp (рядом с docker-compose.yml)
set -euo pipefail
cd "$(dirname "$0")"

mask() {
  local v="$1"
  if [[ -z "$v" ]]; then
    echo "(пусто)"
  elif [[ ${#v} -le 4 ]]; then
    echo "****"
  else
    echo "${v:0:2}***${v: -2} (длина ${#v})"
  fi
}

echo "=== kp-maker / web_kp диагностика ==="
date
echo ""

if [[ -f .env ]]; then
  echo "--- .env (маскировано) ---"
  while IFS= read -r line; do
    [[ "$line" =~ ^# ]] && continue
    [[ -z "$line" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in
      *PASSWORD*|*SECRET*|*API_KEY*|*TOKEN*|SITE_ACCESS_CODE)
        printf "%s=%s\n" "$key" "$(mask "$val")"
        ;;
      *)
        printf "%s=%s\n" "$key" "$val"
        ;;
    esac
  done < .env
else
  echo "Нет файла .env в $(pwd)"
fi

echo ""
echo "--- docker ---"
if docker compose ps 2>/dev/null || docker-compose ps 2>/dev/null; then
  docker compose images 2>/dev/null || true
else
  echo "Docker недоступен (запустите скрипт на VPS, где крутится kp-app)"
fi

echo ""
echo "--- переменные внутри контейнера (маскировано) ---"
for v in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM \
         IMAP_HOST IMAP_PORT IMAP_USER IMAP_PASSWORD \
         LLM_PROVIDER YANDEX_API_KEY YANDEX_FOLDER_ID PUBLIC_BASE_URL; do
  raw=$(docker compose exec -T kp-app printenv "$v" 2>/dev/null || true)
  case "$v" in
    *PASSWORD*|*API_KEY*) printf "%s=%s\n" "$v" "$(mask "${raw:-}")" ;;
    *) printf "%s=%s\n" "$v" "${raw:-}" ;;
  esac
done

echo ""
echo "--- проверка портов с хоста ---"
python3 - <<'PY'
import socket
for host, port in [("smtp.mail.ru", 465), ("smtp.mail.ru", 587), ("imap.mail.ru", 993)]:
    try:
        s = socket.create_connection((host, port), timeout=8)
        s.close()
        print(f"  OK   {host}:{port}")
    except Exception as e:
        print(f"  FAIL {host}:{port} -> {e}")
PY

echo ""
echo "--- integrations (если образ свежий) ---"
docker compose exec -T kp-app python -c "
try:
    from integrations import run_all_checks
    import json
    print(json.dumps(run_all_checks(), ensure_ascii=False, indent=2))
except Exception as e:
    print('Модуль integrations недоступен — нужен деплой новой версии:', e)
" 2>/dev/null || echo "Контейнер kp-app не запущен"

echo ""
echo "--- последние логи ---"
docker compose logs --tail=40 kp-app 2>/dev/null || true
