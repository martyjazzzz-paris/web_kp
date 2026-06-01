# Прод: http://72.56.237.74/

| | |
|---|---|
| **Дизайн** | v60 (`--design-version: 60`, `design-mark: v60-top-split`) |
| **Путь на VPS** | `/root/BOT/web_kp` |
| **Контейнер** | `kp-app`, порт `127.0.0.1:8000` |

## Как НЕ откатить дизайн

**Не запускайте** (откатывают на «утренний» UI):

- `restart_docker.command` — отключён
- `docker compose build` / `up --build` на сервере **без** свежего rsync с Mac
- старый `deploy_production.sh` с полным rsync + build

**Используйте только:**

```bash
cd ~/Projects/BOT/web_kp
export DEPLOY_PASS='пароль root'
./deploy.sh
```

Скрипт: rsync `static/` + `templates/` + `docker-compose.yml` → `docker compose up -d --force-recreate` **без build** → проверка `/health/design`.

## Проверка после деплоя

```bash
curl -s http://72.56.237.74/health/design
# design_version: 60, has_top_split: true

curl -s http://72.56.237.74/static/styles.css | grep -E 'design-version: 60|v60-top-split'
curl -s http://72.56.237.74/ | grep -o 'styles.css?v=60'
```

В браузере: **Cmd+Shift+R**.

## Почему «снова утро»

Docker-образ собирается из кода **на сервере**. Если перезапускали только `docker build` без заливки v60 с Mac — контейнер поднимается со старым CSS. В `docker-compose.yml` static/templates смонтированы с диска — после rsync достаточно recreate **без** build.
