# Один образ: FastAPI-бэкенд отдаёт API и собранный фронтенд.
# Приложение слушает порт из переменной окружения PORT (по умолчанию 5001).

# --- Сборка фронтенда ------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Сборка зависимостей бэкенда --------------------------------------------
FROM python:3.12-slim AS backend-deps
RUN pip install --no-cache-dir uv
WORKDIR /build/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# --- Продакшен-образ ---------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY --from=backend-deps /build/backend/.venv backend/.venv
COPY backend/app backend/app
COPY backend/migrations backend/migrations
COPY backend/alembic.ini backend/alembic.ini
COPY --from=frontend /build/frontend/dist public

ENV STATIC_DIR=/app/public
ENV DATABASE_PATH=/app/data/call-calendar.sqlite
ENV PATH="/app/backend/.venv/bin:${PATH}"
RUN mkdir -p /app/data
EXPOSE 5001

WORKDIR /app/backend
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-5001}
