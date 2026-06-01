# Дизайн web_kp

**Текущий baseline: v60** (на базе v59 prod + правки UI).

| Маркер | Значение |
|--------|----------|
| `design-mark: v60-top-split` | слепок |
| `.top-split` | inbox слева + форма справа |
| `--design-version: 60` | версия + `styles.css?v=60` |
| `#reload-page-btn` | «Перезагрузить» в шапке |

## Не возвращать

- 4 KPI `dashboard-grid` в HTML
- glass / lava фон (в v60 `body::before/after { display: none }`)
- скрипты с `docker build` без rsync

## Деплой после правок

1. Увеличить `--design-version` и `?v=` в `index.html` / `main.py` / `review_routes.py`
2. `export DEPLOY_PASS=... && ./deploy.sh`
3. Проверить `curl http://72.56.237.74/health/design`
