"""Сборка приложения: порт `buildApp()` / `index.js` из backend/src.

Контракт — источник истины: пути, коды ответов и формы ошибок повторяют
`backend/src/app.js`. Роуты разнесены по модулям app/api/*.py (по тегам
контракта), домен (app/domain) ничего не знает про FastAPI/БД, доступ к
данным — через app/infra/store.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    analytics,
    auth,
    availability,
    billing,
    bookings,
    calendars,
    event_types,
    guest,
    notification_settings,
    organizations,
    payments,
    public,
    series,
)
from app.domain.errors import DomainError
from app.infra.db import create_db_engine, run_migrations
from app.infra.notifications import process_reminders
from app.infra.seed import seed_if_empty
from app.infra.store import Store

logger = logging.getLogger("call_calendar")

REMINDER_INTERVAL_SECONDS = 60


def _field_errors_from_validation(exc: RequestValidationError) -> list[dict[str, str]]:
    errors = []
    for error in exc.errors():
        loc = [str(part) for part in error["loc"] if part not in ("body", "query", "path")]
        field = ".".join(loc) if loc else ""
        errors.append({"field": field, "message": error.get("msg", "invalid")})
    return errors


async def _reminder_loop(store: Store) -> None:
    while True:
        try:
            await process_reminders(store)
        except Exception:
            logger.exception("reminder loop tick failed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


def create_app(*, database_path: str | None = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(database_path)
        run_migrations(engine)
        seed_if_empty(engine)
        store = Store(engine)
        app.state.store = store

        reminder_task = asyncio.create_task(_reminder_loop(store))
        try:
            yield
        finally:
            reminder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminder_task
            engine.dispose()

    app = FastAPI(title="Call Calendar API", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(public.router)
    app.include_router(guest.router)
    app.include_router(event_types.router)
    app.include_router(bookings.router)
    app.include_router(availability.router)
    app.include_router(notification_settings.router)
    app.include_router(billing.router)
    app.include_router(calendars.router)
    app.include_router(organizations.router)
    app.include_router(series.router)
    app.include_router(analytics.router)
    app.include_router(payments.router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        content: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.errors:
            content["errors"] = exc.errors
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        if errors and all(e.get("type") == "json_invalid" for e in errors):
            # Битый JSON в теле запроса — не ошибка валидации полей (422),
            # а синтаксически некорректный запрос (400), как в Fastify/app.js
            # (там это ловит content-type parser, а не Ajv).
            return JSONResponse(
                status_code=400,
                content={"code": "bad_request", "message": "Некорректный запрос"},
            )
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Некорректные данные запроса",
                "errors": _field_errors_from_validation(exc),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404, content={"code": "not_found", "message": "Маршрут не найден"}
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": "bad_request", "message": str(exc.detail)},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Any:
        """Раздача собранного SPA (STATIC_DIR) + fallback на index.html для
        клиентских маршрутов React Router. Порт fastify-static + setNotFoundHandler
        из app.js — только для не-/api/ GET-путей."""
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404, content={"code": "not_found", "message": "Маршрут не найден"}
            )
        static_dir = os.environ.get("STATIC_DIR")
        if static_dir:
            base = Path(static_dir).resolve()
            candidate = (base / full_path).resolve()
            if candidate.is_file() and base in candidate.parents:
                return FileResponse(candidate)
            index = base / "index.html"
            if index.is_file():
                return FileResponse(index)
        return JSONResponse(
            status_code=404, content={"code": "not_found", "message": "Маршрут не найден"}
        )

    return app


app = create_app()
