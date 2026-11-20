# Port to Python — промпт и архитектура для агента

Документ для ИИ-агента (и человека): как воспроизвести **Call Calendar (AI version)** —
сервис записи на звонки по мотивам Cal.com + организационную обвязку с GitHub-агентом —
на **Python**, сохранив Design First, Conventional Commits и агентный процесс.

Скопируйте блок **«Промпт агенту»** целиком в новый чат/репозиторий. Разделы выше
промпта — обоснование стека; их можно дать агенту как контекст или держать отдельно.

---

## 1. Целевой продукт (что должно получиться)

Два слоя, как в исходном проекте:

### 1.1. Продукт Call Calendar

- Владелец регистрируется, настраивает типы встреч (15–240 мин), расписание
  (таймзона, правила, перерывы, буфер), смотрит/отменяет брони.
- Публичная страница `/u/{slug}`: гость выбирает слот в своём часовом поясе и
  бронирует без регистрации; управление бронью по `manage_token`.
- Горизонт записи ограничен (например 14 дней); занятый/прошедший слот → 409.
- Персистентность (SQLite → позже Postgres); уведомления (email/Telegram dry-run
  без ключей); опционально busy-sync (ICS/stub), команды, серии, аналитика,
  freemium, stub-оплата.
- Демо-режим фронтенда для GitHub Pages (API в браузере / localStorage) —
  желательно; полный стек — Docker + Render/Railway.

### 1.2. Агентная обвязка (организационный слой)

- OpenCode GitHub App (не обход через `GITHUB_TOKEN` раннера).
- Интерактив: `/oc` / `/opencode` в issue и review-comment.
- Автотриаж: `issues: opened` + `prompt` + фильтр ботов.
- Авторевью: `pull_request` + `prompt` + без draft/ботов.
- Ночной Lighthouse (`schedule` + `workflow_dispatch`): артефакт отчёта;
  агент создаёт **один** issue на конкретную находку (не issue-«отчёт за день»).
- Conventional Commits + commitlint + release-please.
- `AGENTS.md`: Design First, коммиты, команды запуска и проверок.

---

## 2. Рекомендуемый стек и обоснование

### 2.1. Контракт API — TypeSpec → OpenAPI 3 (как сейчас)

| Выбор | Почему |
|---|---|
| **TypeSpec** (`spec/*.tsp`) → `docs/api/openapi.yaml` | Тот же Design First, что в JS-версии; один контракт для Python-бэкенда и TS-клиента. Не дублировать модели в Pydantic «с нуля» как источник истины. |
| Альтернатива: чистый OpenAPI YAML | Хуже DX для больших контрактов; TypeSpec уже отработан в референсе. |
| Не Code-First FastAPI как источник | Ломает принцип «контракт правит руками, код следует»; регрессии ловятся только на ревью. |

Генерация:

- бэкенд: `datamodel-code-generator` или `openapi-python-client` → Pydantic v2 модели;
- фронтенд: `openapi-typescript` + `openapi-fetch` (как сейчас).

### 2.2. Бэкенд — FastAPI + Uvicorn

| Выбор | Почему |
|---|---|
| **FastAPI** | Нативный OpenAPI/JSON Schema, async, зависимость-инъекция, отличная стыковка с Pydantic v2. Ближайший аналог Fastify+AJV по роли «HTTP + валидация по схемам». |
| Uvicorn / Gunicorn+UvicornWorker | Стандарт ASGI для продакшена и Docker. |
| Не Django | Избыточен для API-first Cal.com-клона; ORM/admin уводят от контракта. |
| Не Flask «голый» | Нет первоклассной OpenAPI-валидации из коробки. |
| Connexion 3 | Валидный Design-First вариант «маршруты из spec»; FastAPI гибче для слотов/таймзон и проще экосистема тестов. |

Структура пакетов (пример):

```text
backend/
  app/
    main.py           # create_app(), lifespan, static SPA
    api/              # роутеры по тегам контракта
    domain/           # slots, availability, booking rules (чистая логика)
    infra/            # db, mail, telegram, ics, payments stubs
    auth/             # sessions / cookies
  tests/
  pyproject.toml
```

Правило: **бизнес-правила слотов** (таймзоны, буфер, горизонт, пересечения) —
в `domain/`, без FastAPI Request; роутеры только адаптируют HTTP ↔ domain.
Так проще тестировать без ASGI и проще агенту править одну зону ответственности.

### 2.3. Данные — SQLAlchemy 2.0 + SQLite (aiosqlite), позже Postgres

| Выбор | Почему |
|---|---|
| **SQLAlchemy 2.0 + SQLModel или чистый SA** | Явные модели, миграции Alembic, лёгкий переход SQLite → Postgres (`DATABASE_URL`). |
| SQLite для MVP/учебного деплоя | Как в JS-версии; один файл, простой Docker. |
| Alembic | Схема не «CREATE IF NOT EXISTS в коде навсегда» — агенты и люди меняют схему предсказуемо. |
| Не raw sqlite3 по всему проекту | Сложно масштабировать и тестировать транзакции/гонки слотов. |

Критично: уникальный индекс `(owner_id, starts_at)` WHERE status=active + транзакция
при создании брони — защита от гонки двойного бронирования.

### 2.4. Время — zoneinfo + datetime (UTC внутри)

| Выбор | Почему |
|---|---|
| **stdlib `zoneinfo`** + хранение UTC ISO | Без тяжёлой зависимости; IANA-таймзоны как в dayjs-timezone. |
| `python-dateutil` — опционально | Для ICS/RRULE серий, если дойдёте до P2. |

Правило домена: правила доступности считаются в таймзоне владельца; API отдаёт UTC;
гость видит локальное время на клиенте.

### 2.5. Фронтенд — оставить React + Vite + TypeScript + Mantine

| Выбор | Почему |
|---|---|
| **Тот же SPA**, что в референсе | Сложный UX календаря/DatePicker/доступности уже решён; порт «на Python» не обязан переписывать UI. Контракт общий — клиент генерируется из того же OpenAPI. |
| Демо-режим `VITE_DEMO` | GitHub Pages без бэкенда. |
| Не Reflex/NiceGUI/Streamlit как основной UI | Хуже контроль a11y/Lighthouse и паритет с Cal.com-UX; Streamlit не для публичного booking-flow. |
| HTMX+Jinja — допустимый Plan B | Если курс требует «весь стек на Python»; тогда упростить UI и явно зафиксировать отказ от Mantine. |

Итог: **полиглот-монорепо** — Python API + TS UI — нормальная и предпочтительная архитектура.

### 2.6. Тесты и качество

| Слой | Инструмент | Зачем |
|---|---|---|
| Unit/domain | **pytest** | Слоты, валидация availability без HTTP. |
| API | pytest + **httpx.AsyncClient** + FastAPI `lifespan` | Аналог `fastify.inject`. |
| Контракт | CI: `tsp compile` + diff `openapi.yaml`; опционально schemathesis | Не дать разъехаться коду и spec. |
| Frontend | oxlint/tsc + Playwright CT | Как в референсе. |
| E2E | Playwright | Полный путь гостя и конфликт слота. |
| Коммиты | commitlint + Conventional Commits | release-please. |
| Ночной UX | Lighthouse CLI + агент → один issue | Как в задании AI-версии. |

### 2.7. Упаковка, деплой, агент

| Выбор | Почему |
|---|---|
| **uv** (+ `pyproject.toml`) | Быстрый lockfile, удобно в CI/Docker. Poetry — ок как альтернатива. |
| Docker multi-stage | Stage: frontend build → stage: Python deps → runtime: Uvicorn + `STATIC_DIR` со SPA. |
| Healthcheck | `GET /api/health` → 200 (не авторизованный `/api/event-types`). |
| Render Blueprint | `runtime: docker`, `healthCheckPath: /api/health`. |
| OpenCode GitHub App | OIDC (`id-token: write`), `persist-credentials: false`, без `use_github_token`. |

---

## 3. Архитектура (логическая)

```text
┌─────────────┐     OpenAPI      ┌──────────────────┐
│  TypeSpec   │ ───────────────► │ docs/api/        │
│  spec/*.tsp │   tsp compile    │ openapi.yaml     │
└─────────────┘                  └────────┬─────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
     Pydantic models              FastAPI routers              TS client
     (codegen)                    + domain/slots               openapi-fetch
              │                           │                           │
              └──────────► SQLAlchemy ◄───┘                           │
                           SQLite/Postgres                            │
                                                                      ▼
                                                              React + Mantine
                                                              (Vite, :5173)
```

Поток бронирования:

1. Гость `GET /api/public/{slug}/slots` → domain вычитает правила, буфер, брони, busy.
2. `POST /api/public/{slug}/bookings` → транзакция + проверка «слот ещё свободен» → 201 или 409.
3. Уведомления async/background (можно `BackgroundTasks` на MVP).
4. Владелец cookie-сессия; гость — manage_token в ссылке.

Агентный контур (не в runtime приложения):

```text
issue opened ──► opencode-triage (prompt)
comment /oc  ──► opencode (interactive, App token)
PR opened    ──► opencode-review (prompt)
cron 03:30   ──► lighthouse → artifact → opencode → 1 fix-issue
```

---

## 4. Структура репозитория (целевая)

```text
.
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── package.json              # только TypeSpec + Prism (+ опционально корневые scripts)
├── spec/                     # TypeSpec
├── docs/api/openapi.yaml     # generated
├── backend/                  # Python (uv/pyproject)
├── frontend/                 # React (можно перенести из референса и сменить BASE API)
├── e2e/                      # Playwright
├── .github/workflows/
│   ├── ci.yml
│   ├── opencode.yml
│   ├── opencode-triage.yml
│   ├── opencode-review.yml
│   ├── lighthouse-nightly.yml
│   ├── deploy-pages.yml
│   └── release-please.yml
├── Dockerfile
└── render.yaml
```

---

## 5. Промпт агенту (копировать ниже)

````markdown
# Задача

Создай с нуля учебный fullstack-репозиторий **Call Calendar (Python + AI process)** —
аналог сервиса записи на звонки (Cal.com) с организационной обвязкой GitHub-агента OpenCode.

Работай Design First. Не коммить без явной просьбы. Язык коммитов и issue —
русский, Conventional Commits, повелительное наклонение.

## Стек (зафиксирован, не менять без обоснования в PR)

- Контракт: TypeSpec → `docs/api/openapi.yaml` (руками yaml не редактировать).
- Backend: Python 3.12+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.0, Alembic,
  SQLite (aiosqlite) через `DATABASE_URL`/`DATABASE_PATH`, pytest + httpx.
- Управление зависимостями: uv + `backend/pyproject.toml`.
- Frontend: React + Vite + TypeScript + Mantine; клиент из OpenAPI
  (`openapi-typescript` + `openapi-fetch`); демо-режим для GitHub Pages.
- E2E: Playwright. CI: контракт up-to-date, backend tests, frontend lint/build,
  e2e, commitlint. Релизы: release-please.
- Деплой: Dockerfile (frontend build + Python runtime, раздача SPA из FastAPI),
  `GET /api/health`, render.yaml, healthCheckPath `/api/health`.
- Агент: OpenCode **GitHub App** (OIDC). Не использовать `use_github_token: true`
  как основной режим.

## Продуктовый MVP (вертикальный срез, затем наращивание)

1. TypeSpec: Owner, EventType, Availability, Slot, Booking, Session;
   публичные маршруты `/api/public/{slug}…`, сессия владельца, CRUD типов/доступности.
2. Backend domain: слоты 30 мин (или duration из EventType), таймзона владельца,
   горизонт 14 дней, 409 на занятый/прошлый слот, транзакция + уникальность слота.
3. Регистрация/логин cookie-сессия; seed-владелец через env
   (`OWNER_EMAIL`/`OWNER_PASSWORD`/`OWNER_SLUG`/`OWNER_TIMEZONE`).
4. Frontend: `/u/:slug` бронирование, логин, кабинет владельца (встречи, availability).
5. Тесты API на конфликт брони и горизонт; один e2e happy-path + конфликт.
6. Docker + README с командами запуска:
   - backend `:8000` (или `:5001` для паритета — зафиксируй один порт в README/AGENTS);
   - frontend `:5173`, proxy `/api` → backend.

## Агентный слой (обязательные workflow)

1. `.github/workflows/opencode.yml` — `issue_comment` + `pull_request_review_comment`;
   триггеры `/oc` и `/opencode` (не голая подстрока без границ); `user.type != Bot`;
   `permissions: id-token: write`; `persist-credentials: false`; модель Zen
   (например `opencode/big-pickle`); секрет `OPENCODE_API_KEY` при необходимости.
2. `opencode-triage.yml` — `issues: [opened]`, prompt triage на русском, без PR/коммитов.
3. `opencode-review.yml` — `pull_request` (не draft), prompt code review, без коммитов.
4. `lighthouse-nightly.yml` — `schedule` + `workflow_dispatch`; Lighthouse по URL демо;
   артефакт HTML/JSON + summary; затем OpenCode с prompt: создать **ровно один**
   issue на конкретный дефект (не issue вида «Ночной Lighthouse-отчёт …»).
   Если всё ≥ 90 — issue не создавать.

## AGENTS.md

Включи: Design First; Conventional Commits; команды запуска backend/frontend/env;
проверки перед коммитом (`pytest`, lint/build, e2e).

## Порядок работы

1. Каркас монорепо + TypeSpec MVP + пустой FastAPI `/api/health`.
2. Генерация моделей из OpenAPI, store/SQLAlchemy, слоты, тесты.
3. Frontend против контракта (или перенос UI из референса с заменой base URL).
4. CI, Docker, render.yaml.
5. OpenCode workflows (App-first).
6. ROADMAP.md с P1/P2 (busy-sync, команды, серии, оплата) — не блокировать MVP.

## Критерии готовности MVP

- [ ] `tsp compile` и CI-проверка актуальности `openapi.yaml`.
- [ ] `cd backend && uv run pytest` зелёный (минимум: слоты, 409, авторизация).
- [ ] Локально: UI на 5173 бронирует через Python API.
- [ ] Docker: один контейнер отдаёт UI + API, healthcheck 200.
- [ ] Четыре агентных workflow на месте; README объясняет установку OpenCode App.
- [ ] Коммиты — Conventional Commits на русском.

## Чего не делать

- Не делать FastAPI Code-First источником контракта.
- Не хранить брони только in-memory в «готовом» MVP.
- Не подменять GitHub App обходом `use_github_token` без пометки «временный fallback».
- Не создавать ночной issue-отчёт вместо задачи на фикс.
- Не переписывать фронт на Streamlit/Reflex без отдельного решения владельца.
````

---

## 6. Краткое сравнение с JS-референсом

| Область | JS (референс) | Python (этот порт) |
|---|---|---|
| HTTP | Fastify + AJV из OpenAPI | FastAPI + Pydantic (codegen из OpenAPI) |
| Слоты | dayjs + timezone | zoneinfo + domain-модуль |
| БД | better-sqlite3 / SQL | SQLAlchemy + Alembic + SQLite |
| UI | React + Mantine | **тот же** (полиглот) |
| Агент | OpenCode App | OpenCode App (те же события) |
| Контракт | TypeSpec | TypeSpec (общий язык команды) |

Смысл порта: бэкенд и доменные правила на Python (удобно для data/async/агентных скриптов и типичного бэкенд-стека курса), UI и агентный GitHub-процесс сохраняют проверенные решения референса.
