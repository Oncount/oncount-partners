# OnCount Partner Platform

Партнёрская платформа OnCount: личный кабинет партнёра + Telegram-бот «Community Business Experts» на единой БД.

План реализации: [`../plans/2026-05-18-partner-platform-railway.md`](../plans/2026-05-18-partner-platform-railway.md).

## Стек

- Python 3.11 + FastAPI + Jinja2
- PostgreSQL + SQLAlchemy 2 + Alembic
- aiogram 3 (Telegram-бот)
- Авторизация: Telegram Login Widget + JWT в cookie
- Хостинг: Railway

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
cp .env.example .env       # заполнить BOT_TOKEN и DATABASE_URL

# Postgres локально через Docker:
docker run -d --name oncount-pg -e POSTGRES_USER=oncount -e POSTGRES_PASSWORD=oncount -e POSTGRES_DB=oncount_partners -p 5432:5432 postgres:16

# Миграции:
alembic upgrade head

# Веб:
uvicorn app.main:app --reload
# → http://localhost:8000

# Бот (в отдельном терминале):
python -m app.bot
```

## Деплой на Railway

1. `git push` в private-репо `nikolhillton/oncount-partners`.
2. В Railway создать сервис из репо, добавить Postgres plugin.
3. Указать env vars из `.env.example`.
4. Procfile сам запустит `web` и `worker`.

## Структура

```
app/
├── main.py            # FastAPI app + entry
├── bot.py             # aiogram 3 polling
├── auth.py            # Telegram Login Widget verify + JWT
├── config.py          # настройки из env
├── db.py              # engine + session
├── models.py          # SQLAlchemy
├── kommo.py           # Kommo API client (фаза 8)
├── refgen.py          # генерация ref_slug
├── routes/            # FastAPI-роуты по разделам ЛК
└── templates/         # Jinja2

static/
├── css/oncount.css
└── img/logo.png
```
