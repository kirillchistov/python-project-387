"""Сид для локальной разработки, Docker и e2e. Порт `seedIfEmpty` из db.js.

Отдельно от `Store.create_owner` (используется при саморегистрации через API):
сид конфигурируется переменными окружения (`OWNER_*`), включая таймзону —
`Store.create_owner` таймзону всегда ставит `Europe/Moscow`, как и в JS.
"""

from __future__ import annotations

import json
import os

from sqlalchemy import Engine, text

from app.domain.passwords import hash_password
from app.domain.timeutil import now_iso

_DEFAULT_WEEKDAY_RULES = [
    {"weekday": w, "startTime": "10:00", "endTime": "18:00"} for w in (1, 2, 3, 4, 5)
]


def seed_if_empty(engine: Engine) -> None:
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM owners")).scalar_one()
        if count > 0:
            return

        email = os.environ.get("OWNER_EMAIL") or "owner@example.com"
        password = os.environ.get("OWNER_PASSWORD") or "secret"
        name = os.environ.get("OWNER_NAME") or "Кирилл Чистов"
        slug = os.environ.get("OWNER_SLUG") or "kirill"
        timezone = os.environ.get("OWNER_TIMEZONE") or "Europe/Moscow"

        result = conn.execute(
            text(
                """
                INSERT INTO owners (name, email, slug, password_hash, created_at, plan)
                VALUES (:name, :email, :slug, :password_hash, :created_at, 'free')
                """
            ),
            {
                "name": name,
                "email": email,
                "slug": slug,
                "password_hash": hash_password(password),
                "created_at": now_iso(),
            },
        )
        owner_id = result.lastrowid

        conn.execute(
            text(
                """
                INSERT INTO availability (owner_id, timezone, rules_json, buffer_minutes, exceptions_json)
                VALUES (:owner_id, :timezone, :rules_json, 0, '[]')
                """
            ),
            {
                "owner_id": owner_id,
                "timezone": timezone,
                "rules_json": json.dumps(_DEFAULT_WEEKDAY_RULES),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO notification_settings (owner_id, email_enabled, reminder_hours_before)
                VALUES (:owner_id, 1, 24)
                """
            ),
            {"owner_id": owner_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO event_types (owner_id, name, description, duration_minutes, price_rub)
                VALUES (:owner_id, 'Вводный звонок', 'Знакомство и обсуждение задачи', 30, 0)
                """
            ),
            {"owner_id": owner_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO event_types (owner_id, name, description, duration_minutes, price_rub)
                VALUES (:owner_id, 'Консультация', 'Разбор вопросов по проекту', 60, 0)
                """
            ),
            {"owner_id": owner_id},
        )
