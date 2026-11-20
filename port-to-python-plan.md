# План порта Call Calendar backend на Python — спецификация и архитектура

Рабочий план для переноса **этого репозитория** (`fullstack-javascript-project-387`,
он же `python-project-387`) на Python-бэкенд. Основан на [`port-to-python-agent.md`](./port-to-python-agent.md)
(общий промпт/стек для чистого репозитория) и на фактическом состоянии кода
на момент составления плана (2026-09-11): `backend/` — Fastify + `node:sqlite`,
22/22 теста, продукт синхронизирован с sprint11 (регистрация, таймзоны, буфер,
гостевое управление бронью, уведомления, busy-sync, команды, серии, аналитика,
платные встречи, freemium — см. [ROADMAP.md](./ROADMAP.md)).

**Это порт, а не переписывание продукта.** Контракт (`spec/*.tsp` →
`docs/api/openapi.yaml`), фронтенд (`frontend/`), e2e (`e2e/`) и агентные
GitHub-workflow остаются как есть — меняется только `backend/` и то, что от
него зависит (Dockerfile, CI-джоба `backend-tests`, `AGENTS.md`/`README.md` в
части команд запуска).

---

## 1. Рамки (scope)

### Меняется
- `backend/` — Fastify (JS) → FastAPI (Python). Полная замена реализации при
  сохранении контракта и поведения API.
- `Dockerfile` — стадия сборки бэкенда: Node → Python (uv).
- `.github/workflows/ci.yml` — джоба `backend-tests`.
- `AGENTS.md`, `README.md` — команды запуска/проверки для нового бэкенда.
- `backend/test/*` — переписываются в `pytest`.

### Не меняется
- `spec/*.tsp`, `docs/api/openapi.yaml` — контракт остаётся источником истины
  для запросов/ответов, ровно с теми же операциями и моделями.
- `frontend/` — тот же React + Vite + Mantine SPA, тот же сгенерированный
  клиент (`openapi-typescript` + `openapi-fetch`), демо-режим для GitHub Pages
  не трогаем.
- `e2e/` (Playwright) — сценарии не переписываются; они должны пройти
  **без изменений** против нового бэкенда (это и есть приёмочный критерий).
- `.github/workflows/opencode*.yml`, `lighthouse-nightly.yml`,
  `release-please.yml`, `deploy-pages.yml`, `hexlet-check.yml` — агентный слой
  не зависит от языка бэкенда.
- `render.yaml` — деплой через Docker-образ, интерфейс (`healthCheckPath`,
  переменные окружения) сохраняется 1:1.

### 1.1. GitHub Pages — жёсткое требование, уже выполнено архитектурой

GitHub Pages (`.github/workflows/deploy-pages.yml`, `npm run build:demo` во
`frontend/`) остаётся рабочим и **не зависит от языка бэкенда** — это чисто
статическая сборка, где `frontend/src/api/demo.ts` подменяет транспорт
(`fetch`) на in-browser эмуляцию контракта поверх `localStorage`, без единого
запроса к настоящему API. Проверено чтением `demo.ts`: он уже сам по себе
«урезанная демо-версия» относительно полноценного бэкенда —

- логин по `POST /api/session` принимает любые данные и всегда пускает
  (`state.loggedIn = true`), реальной проверки пароля нет;
- один глобальный «владелец» в `localStorage` браузера, без мультитенантности
  между вкладками/устройствами;
- P2-функции (busy-sync, серии, организации) присутствуют частично или
  заглушками (`GET` → `[]`), без реальной синхронизации.

Порт бэкенда на Python не трогает `demo.ts` и `deploy-pages.yml` — значит
**условие пользователя уже выполнено само по себе**: даже если полноценная
Python-версия с реальной авторизацией (деплой на Render, `render.yaml`,
§7.3) на каком-то этапе не готова или откладывается, урезанное демо на
GitHub Pages продолжает работать независимо, весь порт-план его не
затрагивает. Единственное, что нужно проверить в фазе 6 (§8) и в DoD (§6.3) —
что `frontend/build:demo` и джоба `deploy-pages` не сломались побочно (они
не должны были даже коснуться бэкенда, но это стоит явно прогнать).

---

## 2. Текущее состояние (as-is), зафиксированное для порта

### 2.1. Инвентарь backend/src (JS → что переносим)

| Файл | Строк | Назначение | Целевой модуль (Python) |
|---|---|---|---|
| `app.js` | 1042 | Fastify-инстанс, все роуты, `requireOwner`/`requirePro`, error handler | `app/main.py` + `app/api/*.py` (роутеры по тегам контракта) |
| `store.js` | 874 | Доступ к данным (SQL) для всех сущностей | `app/infra/store.py` |
| `db.js` | 241 | Открытие БД, миграции (`ALTER TABLE ...`), сид демо-владельца | `app/infra/db.py` + Alembic-миграции + `seed.py` |
| `slots.js` | 268 | Домен: свободные слоты, валидация availability/длительности | `app/domain/slots.py` (портируется максимально дословно) |
| `notifications.js` | 178 | Email (SMTP dry-run) / Telegram dry-run уведомления | `app/infra/notifications.py` |
| `payments.js` | 73 | YooKassa/stub-подтверждение платежа, код активации Pro | `app/infra/payments.py` |
| `ics.js` | 69 | Минимальный парсер ICS (VEVENT DTSTART/DTEND) для busy-sync | `app/domain/ics.py` |
| `contract.js` | 49 | Загрузка JSON Schema прямо из `openapi.yaml` для Ajv | заменяется генерацией Pydantic-моделей (см. §4.2) |
| `passwords.js` | 19 | scrypt-хэш пароля `saltHex:hashHex` | `app/domain/passwords.py` (см. §4.4 — формат совместим) |
| `index.js` | 24 | Точка входа, `setInterval` для напоминаний раз в минуту | `app/main.py` (lifespan) + фоновая задача напоминаний |
| `test/api.test.js` | 706 | 22 сценария (node:test) | `backend/tests/*.py` (pytest, 1:1 по сценариям) |

### 2.2. Эндпоинты (из `docs/api/openapi.yaml` / `spec/routes.tsp`)

Полный список групп операций, которые должны быть воспроизведены как есть
(пути, коды ответов, тела ошибок):

- **Health**: `GET /api/health` (без авторизации, всегда 200 — health-check Render).
- **Аккаунт**: `POST /api/owners`, `POST /api/session`, `GET /api/session`,
  `DELETE /api/session`.
- **Публичное бронирование**: `GET /api/public/{slug}`,
  `GET /api/public/{slug}/event-types`, `GET /api/public/{slug}/slots`,
  `POST /api/public/{slug}/bookings`.
- **Гость по manage_token**: `GET/DELETE /api/guest/bookings/{token}`,
  `PATCH /api/guest/bookings/{token}` (перенос встречи).
- **Кабинет владельца**: `GET/POST/PUT/DELETE /api/event-types[/{id}]`,
  `GET /api/bookings`, `DELETE /api/bookings/{id}`,
  `GET/PUT /api/availability`, `GET/PUT /api/notification-settings`.
- **P2 — календари (busy-sync)**: `GET/POST /api/calendars`,
  `POST /api/calendars/google/start`, `POST /api/calendars/{id}/sync`,
  `DELETE /api/calendars/{id}` (требуют `requirePro`).
- **P2 — команды**: `GET/POST /api/organizations`,
  `GET /api/organizations/{id}/members`, `POST /api/organizations/{id}/invite`,
  `POST /api/organizations/join`.
- **P2 — серии**: `GET/POST /api/series`, `DELETE /api/series/{id}`.
- **P2 — аналитика**: `GET /api/analytics/summary`.
- **P2 — биллинг**: `POST /api/billing/activate` (freemium free/pro).
- **P2 — платежи**: `GET /api/payments/{id}`, `POST /api/payments/{id}/stub-confirm`,
  `POST /api/payments/yookassa/webhook`.

Ошибки везде в одном формате (`spec/models.tsp`): `{ code, message }`, для
`ValidationError` дополнительно `errors: FieldError[]` (`{ field, message }`).
Коды состояний: 401 `unauthorized`, 403 `forbidden` (Pro-гейт), 404 `not_found`,
409 `slot_unavailable`/`already_exists`, 422 `validation_error`. Это должно
воспроизводиться байт-в-байт — от этого зависят и фронтенд, и e2e.

### 2.3. Модель данных (SQLite, `db.js`)

Таблицы: `owners`, `sessions`, `event_types`, `availability`, `bookings`,
`notification_settings`, `calendar_connections`, `busy_blocks`, `organizations`,
`organization_members`, `organization_invites`, `booking_series`, `payments`.
Ключевые индексы: `idx_bookings_owner_status(owner_id, status, starts_at)`,
`idx_bookings_manage_token(manage_token)`, `idx_busy_owner_range`,
`idx_payments_booking`. Правила доступности и исключения хранятся как JSON
в текстовых колонках (`rules_json`, `exceptions_json`, `config_json`) — не
раскладываются в отдельные таблицы, это сознательное решение JS-версии,
которое стоит сохранить (упрощает `store.py`, домен и так валидирует форму).

### 2.4. Критичная деталь конкурентности (важно для порта, не только для старта с нуля)

`node:sqlite` (`DatabaseSync`) — **синхронный** API, и весь путь
`POST /api/public/{slug}/bookings` в `app.js` (проверка `isFreeSlot` →
`store.createBooking`) выполняется без единого `await` между чтением и
записью. В однопоточном Node.js event loop это делает проверку-и-вставку
фактически атомарной **без явной транзакции или уникального индекса** —
гонка двойного бронирования невозможна не благодаря дизайну БД, а благодаря
рантайму.

**В FastAPI/async-рантайме эта гарантия пропадает** (несколько воркеров/
корутин могут перемежаться между проверкой и вставкой). Поэтому порт обязан
добавить то, что в JS-версии было не нужно:

1. Уникальный частичный индекс:
   ```sql
   CREATE UNIQUE INDEX idx_bookings_owner_slot_active
     ON bookings(owner_id, starts_at)
     WHERE status = 'active';
   ```
2. `INSERT` брони — в транзакции; `IntegrityError` (нарушение уникальности)
   ловится и превращается в тот же ответ `409 slot_unavailable`, что уже
   возвращает `isFreeSlot`-проверка. Проверка `isFreeSlot` остаётся как
   быстрый path (даёт понятные 409 на «слот в прошлом» /
   «вне расписания» / «буфер»), уникальный индекс — как последний рубеж
   против гонки.

Это единственное осознанное изменение поведения относительно JS-версии —
остальной порт должен быть максимально дословным.

---

## 3. Целевой стек (Python-бэкенд)

Стек зафиксирован по [`port-to-python-agent.md`](./port-to-python-agent.md#2-рекомендуемый-стек-и-обоснование)
(раздел 2), с одним уточнением по слою БД (см. §3.1):

| Слой | Выбор |
|---|---|
| Язык/раннер | Python 3.12+, `uv` (`backend/pyproject.toml`, `uv.lock`) |
| HTTP | FastAPI + Uvicorn |
| Валидация | Pydantic v2 модели, сгенерированные из `docs/api/openapi.yaml` |
| БД | SQLAlchemy 2.0 (см. §3.1 про sync/async) + SQLite (`DATABASE_PATH`) |
| Миграции | Alembic (заменяет ручные `ALTER TABLE ... IF NOT EXISTS` из `db.js`) |
| Время | stdlib `zoneinfo` + UTC ISO-строки в БД (как сейчас) |
| Тесты | `pytest` + `httpx.AsyncClient` (аналог `fastify.inject`) |
| HTTP-клиент (исходящий) | `httpx` (Telegram API, YooKassa, ICS-фиды) |
| Email | stdlib `smtplib`/`email.message` (dry-run лог при отсутствии `SMTP_URL`, как в `notifications.js`) |
| Пароли | stdlib `hashlib.scrypt` (см. §4.4) |
| Lint/format | `ruff` |

### 3.1. Sync или async доступ к БД — уточнение относительно §2.3 `port-to-python-agent.md`

`port-to-python-agent.md` называет `SQLAlchemy 2.0 + SQLite (aiosqlite)` как
зафиксированный выбор. Предлагаю **синхронный** движок SQLAlchemy
(драйвер `sqlite3`) вместо `aiosqlite`, с обоснованием (по правилу AGENTS.md
«не менять стек без обоснования в PR»):

- `aiosqlite` не даёт настоящего параллелизма записи — SQLite всё равно
  пишет из одного потока внутри `aiosqlite`; выгода асинхронности здесь
  иллюзорна, а сложность (async-сессии, event loop в тестах) реальна.
- FastAPI сам диспатчит `def`-хендлеры (не `async def`) в threadpool —
  это даёт тот же эффект «не блокируем event loop», что и `aiosqlite`, но
  с синхронным, линейным кодом в `store.py`, который проще один-в-один
  сверять с `store.js`.
- Исходящие сетевые вызовы (Telegram, YooKassa, ICS-фиды), которые в
  JS-версии асинхронны, в Python делаем через `httpx.AsyncClient` в
  `async def`-хендлерах конкретно для тех операций, где это нужно (busy-sync,
  платежи, уведомления) — это не требует async БД.
- Защита от гонки бронирования (§2.3) не зависит от sync/async — обеспечивается
  уникальным индексом + обработкой `IntegrityError`.

Если владелец репозитория предпочитает буквально следовать
`port-to-python-agent.md` (async + `aiosqlite`), это меняет только слой
`infra/db.py`/`infra/store.py` — домен (`domain/slots.py`) и роуты не
зависят от выбора. Указать явно перед стартом реализации.

### 3.2. Структура пакета

```text
backend/
  pyproject.toml
  uv.lock
  alembic.ini
  migrations/                  # Alembic env + версии (заменяют migrate() из db.js)
  app/
    main.py                    # create_app(), lifespan (открыть БД, засеять demo-владельца, запустить напоминания), раздача SPA (STATIC_DIR)
    api/
      deps.py                  # requireOwner/requirePro как FastAPI-зависимости, cookie-сессия
      health.py
      auth.py                  # /api/owners, /api/session
      public.py                # /api/public/*
      guest.py                 # /api/guest/bookings/*
      event_types.py
      bookings.py
      availability.py
      notification_settings.py
      calendars.py             # P2
      organizations.py         # P2
      series.py                # P2
      analytics.py             # P2
      billing.py               # P2
      payments.py              # P2
      schemas/
        generated.py           # datamodel-code-generator из openapi.yaml — НЕ редактируется руками
    domain/
      slots.py                 # computeFreeSlots/isFreeSlot/validateAvailability/validateDurationMinutes — дословный порт slots.js
      ics.py                   # parseIcsBusy/fetchIcsBusy
      passwords.py             # hash_password/verify_password (scrypt)
    infra/
      db.py                    # engine, session factory, seed_if_empty()
      store.py                 # Store — один класс, методы 1:1 с store.js (snake_case)
      notifications.py         # notify_booking_event, process_reminders
      payments.py              # create_payment_confirmation, is_valid_pro_code, is_yookassa_configured
  tests/
    conftest.py                # fixture: приложение на :memory:, httpx.AsyncClient
    test_auth.py
    test_public_booking.py     # включая тест на гонку двойного бронирования (§2.3)
    test_guest_booking.py
    test_event_types.py
    test_bookings.py
    test_availability.py
    test_notification_settings.py
    test_p2_*.py               # calendars/organizations/series/analytics/billing/payments
```

Правило из `port-to-python-agent.md` сохраняется: бизнес-правила слотов —
в `domain/`, без `Request`/`Depends`; роутеры только адаптируют HTTP ↔ domain
↔ `infra/store.py`.

---

## 4. Спецификация порта (что именно и как переносим)

### 4.1. Контракт остаётся неизменным

`spec/*.tsp` не трогаем. `docs/api/openapi.yaml` компилируется тем же
`npm run spec:build` из корня — эта команда и её CI-проверка (`ci.yml` →
джоба `contract`) не меняются.

### 4.2. Валидация запросов/ответов — вместо `contract.js`

JS-версия не дублирует схемы руками: `contract.js` читает `openapi.yaml` и
подключает JSON Schema напрямую в Ajv (Fastify). Идиоматичный FastAPI обычно
наоборот — Pydantic-модели являются источником `openapi.json`. Чтобы не
нарушить Design First (контракт правит, код следует — см. `AGENTS.md`),
порт использует генерацию, а не ручное дублирование:

1. `datamodel-code-generator` генерирует `app/api/schemas/generated.py` из
   `docs/api/openapi.yaml` (Pydantic v2 модели, по одной на каждую схему
   `components.schemas`).
2. Роутеры используют только сгенерированные модели как типы тел запросов
   и `response_model`.
3. В `backend/pyproject.toml` — скрипт (например `uv run poe schemas` или
   Makefile-таргет) для регенерации.
4. В `ci.yml`, в той же джобе `contract` (или отдельной `backend-schemas`),
   добавляется шаг: перегенерировать `generated.py` и
   `git diff --exit-code` — по аналогии с уже существующей проверкой
   `openapi.yaml` и с `frontend/src/api/schema.d.ts`. Итого три
   генерируемых артефакта из одного контракта, все проверяются в CI одинаково.

Это даёт то же свойство, что и `contract.js`: модели невозможно незаметно
рассинхронизировать с контрактом, но естественным для FastAPI способом.

### 4.3. Домен слотов — дословный перенос

`domain/slots.py` переносит `slots.js` функция-в-функцию:

- `GRID_MINUTES = 15`, `BOOKING_HORIZON_DAYS = 14`.
- `intervals_for_day(availability, day) -> list[DayInterval]` — с учётом
  `exceptions`.
- `compute_free_slots(availability, active_bookings, external_busy, from_, to,
  duration_minutes, now) -> list[Slot]` — та же логика буфера
  (`bufferMinutes` вокруг активных броней), тот же горизонт, та же сортировка.
- `is_free_slot(...) -> bool`.
- `validate_duration_minutes(minutes) -> str | None`.
- `validate_availability(raw) -> list[FieldError]` — включая проверку IANA
  таймзоны (`zoneinfo.available_timezones()` / `try: ZoneInfo(tz)`), пересечения
  правил по дню недели, пересечения интервалов внутри исключения.

Таймзонная арифметика: `dayjs.tz` → `datetime` с `ZoneInfo(availability.timezone)`;
хранение и сравнение — в UTC (`.astimezone(UTC)` перед сравнением/сортировкой),
как и в JS-версии.

### 4.4. Пароли — формат хэша совместим, миграция данных не нужна

`passwords.js` использует `scrypt` с параметрами `N=16384, r=8, p=1, maxmem=64MiB`,
хранит как `saltHex:hashHex`. Python `hashlib.scrypt(password, salt=salt, n=16384,
r=8, p=1, dklen=32, maxmem=64*1024*1024)` даёт побитово идентичный результат
(тот же алгоритм, тот же формат параметров). **Существующие БД с реальными
паролями (если такие есть в проде) не потребуют сброса паролей** — только
сравнение через `hmac.compare_digest`/`secrets.compare_digest` вместо
`crypto.timingSafeEqual`. Если стартуем с чистой БД (учебный проект,
`OWNER_PASSWORD=secret` по умолчанию) — вопрос неактуален, но фиксируем как
намеренное решение, а не забытый риск.

### 4.5. Сессии и авторизация

- Cookie `session` (httpOnly, `SameSite=Lax`, `path=/`), значение — `uuid4`
  в таблице `sessions` (без изменений формата).
- `requireOwner` → FastAPI `Depends(require_owner)`, читает cookie через
  `Request.cookies`, поднимает `HTTPException(401, ...)` в едином формате ошибок.
- `requirePro` → `Depends(require_pro)`, 403 с тем же телом
  (`{ code: 'forbidden', message: '...' }`).
- Общий error handler (аналог `app.setErrorHandler` в `app.js`) —
  `@app.exception_handler` в `main.py`: `RequestValidationError` → 422
  с `errors: [{field, message}]` в том же виде, что сейчас формирует Ajv-ветка;
  доменные исключения (`ValidationError`, `NotFoundError`, `ConflictError`,
  `AlreadyExistsError` — как в `store.js`, через `err.code`) → соответствующий
  статус; всё прочее → 500 `internal_error` (с логированием, без утечки текста
  наружу — как сейчас).

### 4.6. Уведомления, платежи, busy-sync — поведенческая эквивалентность

- `infra/notifications.py`: без `SMTP_URL` — лог `[email:dry-run] ...` (как
  сейчас, для тестов и dev); без `TELEGRAM_BOT_TOKEN` — аналогично. С заданными
  переменными — реальная отправка (`smtplib`/`httpx`). Тексты писем/сообщений
  (заголовки `Встреча забронирована/отменена/перенесена`, форматирование
  даты через локаль `ru-RU` — в Python эквивалент через `babel` или ручное
  форматирование, т.к. `Intl.DateTimeFormat('ru-RU', ...)` не имеет прямого
  stdlib-аналога) переносятся дословно по содержанию.
- `infra/payments.py`: без `YOOKASSA_SHOP_ID`/`YOOKASSA_SECRET_KEY` —
  `stub`-провайдер с `confirmationUrl = {PUBLIC_BASE_URL}/pay/stub/{id}` (как
  сейчас, нужен для e2e/демо без ключей); с ключами — реальный запрос к
  YooKassa API через `httpx`. `is_valid_pro_code` — сравнение с
  `BILLING_PRO_CODE` (по умолчанию `pro-dev`).
- `domain/ics.py`: минимальный парсер `BEGIN:VEVENT`/`DTSTART`/`DTEND`,
  без полного RFC5545 — ровно как сейчас (достаточно для busy-sync MVP).

### 4.7. Переменные окружения — без изменений имён

`PORT`, `HOST`, `OWNER_EMAIL`, `OWNER_PASSWORD`, `OWNER_NAME`, `OWNER_SLUG`,
`OWNER_TIMEZONE`, `DATABASE_PATH`, `PUBLIC_BASE_URL`, `SMTP_URL`, `EMAIL_FROM`,
`TELEGRAM_BOT_TOKEN`, `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`,
`BILLING_PRO_CODE`, `STATIC_DIR` — все имена сохраняются, чтобы `render.yaml`,
`AGENTS.md` и локальные привычки не потребовали правок сверх необходимого.

---

## 5. Данные: миграции и сид

`db.js.migrate()` — императивные `CREATE TABLE IF NOT EXISTS` +
последовательные `ALTER TABLE ... ADD COLUMN` (P1/P2, с проверкой
`columnExists`) — заменяется на явные версионированные Alembic-миграции:

1. `0001_initial` — таблицы P0/P1 из первого блока `db.exec(...)`
   (owners, sessions, event_types, availability, bookings,
   notification_settings + индекс `idx_bookings_owner_status`).
2. `0002_p1_columns` — `buffer_minutes`, `exceptions_json`, `manage_token`,
   `reminder_sent_at`.
3. `0003_p2` — `owners.plan`, `event_types.price_rub`,
   `bookings.payment_status`, `bookings.series_id`, новые таблицы
   (`calendar_connections`, `busy_blocks`, `organizations`,
   `organization_members`, `organization_invites`, `booking_series`,
   `payments`) + их индексы.
4. `0004_manage_token_index` — `idx_bookings_manage_token` + backfill
   `manage_token` для строк, где он пуст (`uuid4()` per row — как
   `cryptoRandom()` в JS).
5. `0005_booking_slot_unique` — **новая** миграция порта: частичный уникальный
   индекс `idx_bookings_owner_slot_active` (см. §2.3) — единственная миграция
   без прямого аналога в JS-версии.

`seed_if_empty()` в `infra/db.py` (или отдельный `alembic` data-скрипт,
запускаемый из `main.py` lifespan при пустой таблице `owners`) — переносится
дословно: те же переменные окружения, те же дефолты (`owner@example.com`/
`secret`/`Кирилл Чистов`/`kirill`/`Europe/Moscow`), то же расписание Пн–Пт
10:00–18:00, те же два демо-типа встреч.

---

## 6. Тестовая стратегия и критерии приёмки

### 6.1. Backend unit/API-тесты

`backend/test/api.test.js` (706 строк, 22 теста, `node:test`) — источник
сценариев для `pytest`. Переносим по одному файлу на область (см. структуру
§3.2), сохраняя формулировки сценариев (в т.ч. русскоязычные describe/it,
если такие есть) как комментарии/имена тестов. Обязательно включить:

- регистрация с занятым email/slug → `409 already_exists`;
- логин/логаут/`GET /api/session` без и с cookie;
- расчёт слотов с буфером и исключениями availability;
- бронирование прошедшего/несуществующего/вне-расписания слота → `409`;
- **новый тест**: параллельные `POST /api/public/{slug}/bookings` на один и
  тот же `startsAt` — ровно один `201`, остальные `409 slot_unavailable`
  (регресс-тест на §2.3, которого не было и не могло быть в синхронном
  JS-варианте — тест, доказывающий необходимость и корректность
  уникального индекса);
- отмена/перенос брони гостем по `manage_token`, включая невалидный токен;
- CRUD типов встреч, включая запрет удаления типа с активными будущими
  бронями;
- P2: Pro-гейт (`403`) на busy-sync/организации/аналитику для `plan=free`;
  активация Pro кодом; серии; аналитика; платежи (stub-подтверждение,
  webhook).

Критерий: **не меньше** сценариев и ветвлений, чем в текущих 22 тестах,
плюс новый тест на гонку.

### 6.2. Контрактные и фронтенд-тесты — без изменений

- `npm run spec:build` + `git diff --exit-code docs/api/openapi.yaml` — как
  сейчас (контракт не менялся).
- `frontend`: lint/build/CT (`npm run test:ct`) — не трогаются; фронтенд не
  знает, на чём написан бэкенд.
- `e2e/` (Playwright) — **не переписывается**. Прогон `cd e2e && npm test`
  против Python-бэкенда на порту 5001 (или зафиксированном в README) — это и
  есть сквозной приёмочный тест порта: happy path бронирования, конфликт
  слота, оба должны проходить без модификации файлов в `e2e/tests`.

### 6.3. Определение готовности (Definition of Done)

- [ ] `cd backend && uv run pytest` — зелёный, покрытие ≥ прежних 22 сценариев + тест гонки.
- [ ] `npm run spec:build` — контракт компилируется, diff чист.
- [ ] Регенерация `backend/app/api/schemas/generated.py` — diff чист (см. §4.2).
- [ ] `cd frontend && npm run lint && npm run build` — без изменений в `frontend/`.
- [ ] `cd e2e && npm test` — проходит против Python-бэкенда без правок сценариев.
- [ ] `docker build .` + `docker run` — контейнер отдаёт UI и API на одном порту,
      `GET /api/health` → 200 (см. §7).
- [ ] `render.yaml` не потребовал изменений интерфейса (только внутренняя сборка).
- [ ] `AGENTS.md`/`README.md` — команды запуска/проверки обновлены на `uv`/`pytest`.
- [ ] Старый `backend/` (Node) удалён из репозитория (не оставляем два бэкенда).
- [ ] `cd frontend && npm run build:demo` и workflow `deploy-pages.yml`
      (можно прогнать вручную через `workflow_dispatch`) — без изменений и без
      ошибок; демо на GitHub Pages остаётся рабочим независимо от готовности
      Python-бэкенда (см. §1.1).

---

## 7. Инфраструктура

### 7.1. Dockerfile

Схема остаётся multi-stage: frontend build → backend deps → runtime.
Меняется только стадия бэкенда:

```text
FROM node:22-alpine AS frontend        # без изменений
...
FROM python:3.12-slim AS backend-deps  # было node:22-alpine + node-gyp toolchain
WORKDIR /build/backend
RUN pip install uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=backend-deps /build/backend/.venv backend/.venv
COPY docs/api/openapi.yaml docs/api/openapi.yaml   # если ещё нужен рантайму — уточнить по §4.2
COPY backend/app backend/app
COPY backend/migrations backend/migrations
COPY backend/alembic.ini backend/alembic.ini
COPY --from=frontend /build/frontend/dist public

ENV STATIC_DIR=/app/public
ENV DATABASE_PATH=/app/data/call-calendar.sqlite
RUN mkdir -p /app/data
EXPOSE 5001
CMD ["backend/.venv/bin/uvicorn", "app.main:app", "--app-dir", "backend", \
     "--host", "0.0.0.0", "--port", "5001"]
```

Toolchain `python3 make g++` для `better-sqlite3`, который сейчас нужен
Node-бэкенду, в Python-версии не нужен — `sqlite3` в stdlib.

### 7.2. CI (`ci.yml`)

Джоба `backend-tests` меняется с Node/`npm test` на:

```yaml
backend-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v3
    - run: uv sync --frozen
      working-directory: backend
    - run: uv run pytest
      working-directory: backend
```

Джобы `contract`, `frontend-build`, `component-tests`, `e2e`,
`commitlint` — без изменений (e2e-джоба по-прежнему поднимает бэкенд, но
теперь через `uv run uvicorn ...` вместо `npm start`).

### 7.3. Прочее

- Корневой `package.json` (`spec:build`, `api:mock`) — не меняется, бэкенда
  не касается.
- `render.yaml` — не меняется (Docker-образ уже абстрагирует язык рантайма).
- `AGENTS.md` §«Запуск приложения локально» — команды `cd backend && npm install
  && npm start` заменяются на `cd backend && uv sync && uv run uvicorn app.main:app
  --reload --port 5001` (или `uv run fastapi dev`), переменные окружения —
  без изменений набора.

---

## 8. Порядок работ (фазы/PR)

Каждая фаза — отдельный PR с Conventional Commit (`feat(backend): ...` /
`refactor(backend): ...` / `ci: ...`), проверяемый по AGENTS.md перед
коммитом. Порядок рассчитан так, чтобы `main` не ломался между PR
(Node-бэкенд продолжает работать до фазы 6).

1. **Каркас**: `backend-py/` (временная директория рядом с текущим `backend/`,
   чтобы не сломать CI) — `pyproject.toml`, `uv.lock`, `app/main.py` с
   `GET /api/health`, Alembic init, пустая `tests/`. CI: новая необязательная
   джоба (`continue-on-error` или ручной `workflow_dispatch`) параллельно
   основной.
2. **Данные**: Alembic-миграции 0001–0005 (§5), `infra/db.py`, `seed_if_empty`,
   `infra/store.py` — портирование всех методов `store.js` (§2.1) с юнит-тестами
   на слое store (без HTTP).
3. **Домен**: `domain/slots.py`, `domain/ics.py`, `domain/passwords.py` —
   портирование `slots.js`/`ics.js`/`passwords.js`, тесты домена
   (без FastAPI/БД, как заповедано в `port-to-python-agent.md` §2.2).
4. **Контракт → Pydantic**: генерация `schemas/generated.py`
   (`datamodel-code-generator`), CI-шаг регенерации+diff.
5. **API P0/P1**: роутеры `auth`, `public`, `guest`, `event_types`,
   `bookings`, `availability`, `notification_settings` + `deps.py`
   (`require_owner`) + error handler. Портирование `pytest`-сценариев
   из `api.test.js` для этой части. **Здесь же — тест и защита гонки
   бронирования (§2.3, §6.1).**
6. **Переключение**: `backend-py/` → `backend/` (удалить Node-версию и её
   `package.json`/`node_modules`/тесты одним коммитом), обновить
   `Dockerfile`, `ci.yml`, `AGENTS.md`, `README.md`. Прогнать `e2e/`
   против нового бэкенда — это приёмка фазы.
7. **API P2**: `calendars`, `organizations`, `series`, `analytics`,
   `billing`, `payments` — по одному роутеру за PR, с `requirePro`-тестами.
8. **Уведомления и платежи**: `infra/notifications.py`, `infra/payments.py`
   с дословным dry-run поведением; напоминания — фоновая задача в lifespan
   (аналог `setInterval` из `index.js`, например через `asyncio.create_task`
   с периодом 60 c).
9. **Финальная сверка**: полный прогон DoD-чеклиста (§6.3), обновление
   `ROADMAP.md`/`project-spec.md`/`how-it-works.md` (они и так помечены как
   требующие актуализации — см. `ROADMAP.md` → «Дальше»).

Фазы 1–5 можно вести в одном PR при желании ускорить учебный процесс, но
раздельные PR лучше ложатся на agentный ревью-цикл (`opencode-review.yml`)
и на Conventional Commits (один коммит — одно логическое изменение, per
`AGENTS.md`).

---

## 9. Решения (подтверждены владельцем 2026-09-15)

| # | Вопрос | Решение |
|---|---|---|
| 1 | Sync или async слой БД (§3.1) | SQLAlchemy sync engine + threadpool |
| 2 | Валидация запросов (§4.2) | Codegen Pydantic из `openapi.yaml`, CI diff-проверка |
| 3 | Путь миграции (§8) | `backend-py/` рядом, переключение в фазе 6 |
| 4 | Формат русской даты в уведомлениях (§4.6) | `babel` (или ручной словарь месяцев) |

Реализация идёт по рекомендованным вариантам без дополнительных уточнений.

---

## 10. Чего не делать

- Не менять контракт (`spec/*.tsp`) ради удобства порта — если чего-то не
  хватает в схеме, это отдельный Design First PR, а не побочный эффект
  переноса бэкенда.
- Не переписывать `frontend/` и `e2e/` — они не должны знать, что бэкенд
  сменился.
- Не терять уведомления/платежи/busy-sync/серии/аналитику как «P2, потом
  как-нибудь» — они уже в продукте (см. `ROADMAP.md` → «Уже в продукте»),
  порт обязан их сохранить, а не откатить до P0.
- Не хранить два работающих бэкенда в `main` дольше, чем нужно для одного
  цикла ревью (фаза 6 — явная точка отсечения).
- Не молчать про изменение поведения (§2.3) — это единственное сознательное
  расхождение с JS-версией, и оно должно быть явно описано в PR, который его
  вносит.
