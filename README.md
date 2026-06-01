# Web KP (MVP)

Коммерческие предложения: форма, PDF, почта, AI-черновики, web-ревью, админ-бот.

## Запуск

Из корня проекта (после `./scripts/setup.sh`):

```bash
source .venv/bin/activate
cd web_kp
uvicorn main:app --reload --port 8080
```

Админ-бот (отдельный терминал):

```bash
cd web_kp && python telegram_bot.py
```

## Ассеты

Положите `BEZ.pdf` в `assets/` (см. `assets/README.md`). Логотип и подпись — в `static/`.

## Переменные

См. `web_kp/.env.example` и корневой `.env.example`.

## Дизайн и прод

**Зафиксированный baseline: v60** — см. [WORKFLOW.md](WORKFLOW.md), [DESIGN_BASELINE.json](DESIGN_BASELINE.json), [DESIGN.md](DESIGN.md).

```bash
./scripts/verify_baseline.sh   # проверка локально
./fix_prod_now.sh              # деплой на 72.56.237.74
```

После правок UI: `./scripts/bump_design.sh 61 v61-top-split`
