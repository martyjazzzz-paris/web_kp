# Как работать с дизайном (без откатов)

## Зафиксированный baseline: **v60**

Файл-якорь: **`DESIGN_BASELINE.json`**

Проверка локально:

```bash
./scripts/verify_baseline.sh
./scripts/check_design.sh
```

## Деплой на прод (единственный надёжный способ)

```bash
cd ~/Projects/BOT/web_kp
./fix_prod_now.sh
```

Пароль root спросит несколько раз. Скрипт:
- заливает static + templates + compose
- **не** использует `docker build` и **не** `--force-recreate` (баг ContainerConfig)
- проверяет v60 на диске и в контейнере

## Когда меняете UI

1. Правите `static/styles.css`, `templates/index.html`, при необходимости `app.js`
2. **Не возвращайте** `dashboard-grid`, lava/glass в HTML
3. Увеличьте версию:
   ```bash
   ./scripts/bump_design.sh 61 v61-top-split
   ./scripts/verify_baseline.sh
   ```
4. `./fix_prod_now.sh`
5. Safari: Cmd+Shift+R

## Не запускать (ломают прод)

| Скрипт | Почему |
|--------|--------|
| `restart_docker.command` | docker build без rsync |
| `rebuild_on_vps.sh` | пересборка образа со старым кодом |
| `_push_prod.sh`, `deploy_quick.sh` | `--build` / `--force-recreate` |
| `docker compose up --build` на VPS | откат CSS из образа |

## Git

Baseline закоммичен. Тег:

```bash
git tag design-v60
```

Перед большими правками: `git checkout -b design-v61`.
