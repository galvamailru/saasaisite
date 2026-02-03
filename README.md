# CIP Backend (saasaisite)

Backend многопользовательской SaaS-платформы диалогового веб-сайта с AI-агентом (CIP): чат (REST + SSE), кабинет пользователя (диалоги, сохранённое, профиль). Реализация по [04-execution-spec.md](prompts/04-execution-spec.md).

## Стек

- Python 3.11+
- FastAPI, PostgreSQL (asyncpg), Alembic
- LLM: DeepSeek (HTTP API, стриминг)
- Docker, docker-compose

## Быстрый старт

1. Скопировать `.env.example` в `.env` и задать переменные (в т.ч. `DATABASE_URL`, `DEEPSEEK_API_KEY`, `PROMPT_FILE`).
2. Запуск через Docker Compose:

```bash
docker-compose up -d db
# Дождаться готовности БД, затем:
docker-compose run --rm app alembic upgrade head
docker-compose up app
```

3. Локально (без Docker):

```bash
pip install -r requirements.txt
# PostgreSQL должен быть запущен, DATABASE_URL в .env
alembic upgrade head
python run.py
```

Приложение: `http://localhost:8000`. Демо-тенант с slug `demo` создаётся миграцией 002.

## Маршруты

- **Чат:** `POST /api/v1/tenants/{tenant_id}/chat` — тело: `{ "user_id", "message", "dialog_id?" }` → SSE.
- **Кабинет:**  
  - `GET /api/v1/tenants/by-slug/{slug}` — тенант по slug.  
  - `GET /api/v1/tenants/{tenant_id}/me/dialogs` — список диалогов (заголовок `X-User-Id` или `Authorization: Bearer <JWT>`).  
  - `GET /api/v1/tenants/{tenant_id}/me/dialogs/{dialog_id}` — сообщения диалога.  
  - `GET/POST/DELETE /api/v1/tenants/{tenant_id}/me/saved` — сохранённое.  
  - `GET/PATCH /api/v1/tenants/{tenant_id}/me/profile` — профиль.
- **Регистрация и вход:**  
  - `POST /api/v1/tenants/{tenant_id}/register` — регистрация (email, пароль); отправляется письмо с ссылкой подтверждения.  
  - `GET /api/v1/tenants/by-slug/{slug}/confirm?token=...` — подтверждение email по ссылке из письма.  
  - `POST /api/v1/tenants/{tenant_id}/login` — вход (email, пароль) → JWT.
- **Статика:**  
  - `/{slug}/chat` — чат.  
  - `/{slug}/my`, `/{slug}/my/dialogs`, `/{slug}/my/saved`, `/{slug}/my/profile` — кабинет.  
  - `/{slug}/register`, `/{slug}/login`, `/{slug}/confirm?token=...` — регистрация, вход, подтверждение email.

## Тесты

```bash
pytest tests/ -v
```

Тесты используют in-memory SQLite (aiosqlite). Для полной совместимости с продакшеном (PostgreSQL UUID и т.д.) можно запускать тесты с реальной БД, задав `DATABASE_URL` в окружении.

## Конфигурация (.env)

- `DATABASE_URL` — PostgreSQL (async): `postgresql+asyncpg://user:pass@host:5432/db`
- `DEEPSEEK_API_URL`, `DEEPSEEK_API_KEY` — API DeepSeek
- `PROMPT_FILE` — путь к файлу системного промпта (относительно корня проекта или абсолютный)
- `APP_HOST`, `APP_PORT` — хост и порт uvicorn
- **Регистрация и email:**  
  - `JWT_SECRET` — секрет для подписи JWT (обязательно сменить в продакшене)  
  - `JWT_EXPIRE_MINUTES` — срок жизни токена (по умолчанию 10080 = 7 дней)  
  - `FRONTEND_BASE_URL` — базовый URL для ссылки подтверждения в письме (например `http://localhost:8000`)  
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` — отправка писем. Если SMTP не задан, письмо выводится в консоль (для разработки).
