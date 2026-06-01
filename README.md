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

Актуальный UI: **[DESIGN.md](DESIGN.md)** (v59). Прод зафиксирован: **[PRODUCTION.md](PRODUCTION.md)** (2026-06-01).

Деплой на сервер (без `brew` / `sshpass`):

```bash
export DEPLOY_PASS='пароль root'
cd ~/Projects/BOT/web_kp && ./deploy_expect.sh
```
