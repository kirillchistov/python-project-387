"""Доступ к данным через SQLite. Роуты и бизнес-логика не знают про SQL.

Дословный порт `backend/src/store.js` — те же методы (в snake_case), те же
запросы, та же форма возвращаемых словарей (камелкейс-ключи — как в JSON-
контракте). Каждый метод открывает своё соединение/транзакцию из Engine
(SQLAlchemy 2.0, sync) — см. port-to-python-plan.md §3.1, §3.2.

Единственное сознательное отличие от JS-версии — `create_booking` и
`reschedule_booking_by_token` полагаются на уникальный частичный индекс
`idx_bookings_owner_slot_active` (миграция 0005) и перехватывают
`IntegrityError`, превращая гонку двойного бронирования в `SlotUnavailableError`
вместо тихой порчи данных. В однопоточном `node:sqlite` эта гонка была
невозможна благодаря рантайму — см. port-to-python-plan.md §2.3.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.domain.errors import (
    AlreadyExistsError,
    NotFoundError,
    SlotUnavailableError,
    ValidationError,
)
from app.domain.passwords import hash_password, verify_password
from app.domain.timeutil import now_iso

_DEFAULT_WEEKDAY_RULES = [
    {"weekday": w, "startTime": "10:00", "endTime": "18:00"} for w in (1, 2, 3, 4, 5)
]

_BOOKING_SELECT = """
    SELECT b.*, et.name AS event_type_name
    FROM bookings b
    JOIN event_types et ON et.id = b.event_type_id
"""


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _map_owner(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "slug": row["slug"],
        "plan": "pro" if row["plan"] == "pro" else "free",
    }


def _map_event_type(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {
        "id": row["id"],
        "name": row["name"],
        "durationMinutes": row["duration_minutes"],
        "priceRub": row["price_rub"] or 0,
    }
    if row["description"] not in (None, ""):
        data["description"] = row["description"]
    return data


def _map_booking(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {
        "id": row["id"],
        "eventTypeId": row["event_type_id"],
        "eventTypeName": row.get("event_type_name") or "Встреча",
        "startsAt": row["starts_at"],
        "endsAt": row["ends_at"],
        "guestName": row["guest_name"],
        "guestEmail": row["guest_email"],
        "status": row["status"],
        "paymentStatus": row["payment_status"] or "none",
        "createdAt": row["created_at"],
    }
    if row["comment"] not in (None, ""):
        data["comment"] = row["comment"]
    return data


def _map_booking_created(row: Any) -> dict[str, Any] | None:
    booking = _map_booking(row)
    if booking is None:
        return None
    return {**booking, "manageToken": row["manage_token"]}


def _map_availability(row: Any) -> dict[str, Any]:
    if row is None:
        return {"timezone": "Europe/Moscow", "bufferMinutes": 0, "rules": [], "exceptions": []}
    return {
        "timezone": row["timezone"],
        "bufferMinutes": row["buffer_minutes"] or 0,
        "rules": json.loads(row["rules_json"]),
        "exceptions": json.loads(row["exceptions_json"] or "[]"),
    }


def _map_calendar_connection(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {"id": row["id"], "kind": row["kind"], "label": row["label"]}
    if row["last_synced_at"]:
        data["lastSyncedAt"] = row["last_synced_at"]
    return data


def _map_payment(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "bookingId": row["booking_id"],
        "amountRub": row["amount_rub"],
        "status": row["status"],
        "confirmationUrl": row["confirmation_url"],
    }


class Store:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # --- владельцы / сессии ------------------------------------------------

    def find_owner_by_email(self, email: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM owners WHERE email = :email COLLATE NOCASE"), {"email": email}
            ).mappings().first()
            return _map_owner(row)

    def find_owner_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM owners WHERE slug = :slug COLLATE NOCASE"), {"slug": slug}
            ).mappings().first()
            return _map_owner(row)

    def find_owner_by_id(self, owner_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM owners WHERE id = :id"), {"id": owner_id}
            ).mappings().first()
            return _map_owner(row)

    def set_owner_plan(self, owner_id: int, plan: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE owners SET plan = :plan WHERE id = :id"), {"plan": plan, "id": owner_id}
            )
        return self.find_owner_by_id(owner_id)

    def get_owner_public(self, slug: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM owners WHERE slug = :slug COLLATE NOCASE"), {"slug": slug}
            ).mappings().first()
        if row is None:
            return None
        availability = self.get_availability(row["id"])
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "timezone": availability["timezone"],
        }

    def create_owner(
        self, *, name: str, email: str, password: str, slug: str
    ) -> dict[str, Any] | None:
        now = now_iso()
        rules = _DEFAULT_WEEKDAY_RULES
        try:
            with self._engine.begin() as conn:
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
                        "created_at": now,
                    },
                )
                owner_id = result.lastrowid
                conn.execute(
                    text(
                        """
                        INSERT INTO availability
                            (owner_id, timezone, rules_json, buffer_minutes, exceptions_json)
                        VALUES (:owner_id, 'Europe/Moscow', :rules_json, 0, '[]')
                        """
                    ),
                    {"owner_id": owner_id, "rules_json": json.dumps(rules)},
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
        except IntegrityError as exc:
            if "UNIQUE" in str(exc.orig):
                raise AlreadyExistsError("Email или slug уже заняты") from exc
            raise
        return self.find_owner_by_id(owner_id)

    def check_credentials(self, email: str, password: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM owners WHERE email = :email COLLATE NOCASE"), {"email": email}
            ).mappings().first()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return _map_owner(row)

    def create_session(self, owner_id: int) -> str:
        token = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sessions (token, owner_id, created_at) VALUES (:token, :owner_id, :created_at)"),
                {"token": token, "owner_id": owner_id, "created_at": now_iso()},
            )
        return token

    def get_session_owner(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT o.* FROM sessions s
                    JOIN owners o ON o.id = s.owner_id
                    WHERE s.token = :token
                    """
                ),
                {"token": token},
            ).mappings().first()
            return _map_owner(row)

    def destroy_session(self, token: str | None) -> None:
        if not token:
            return
        with self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE token = :token"), {"token": token})

    # --- типы событий --------------------------------------------------------

    def list_event_types(self, owner_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM event_types WHERE owner_id = :owner_id ORDER BY id"),
                {"owner_id": owner_id},
            ).mappings().all()
            return [_map_event_type(r) for r in rows]

    def find_event_type(self, owner_id: int, event_type_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM event_types WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": event_type_id},
            ).mappings().first()
            return _map_event_type(row)

    def create_event_type(
        self,
        owner_id: int,
        *,
        name: str,
        description: str | None,
        duration_minutes: int,
        price_rub: int | None,
    ) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO event_types (owner_id, name, description, duration_minutes, price_rub)
                    VALUES (:owner_id, :name, :description, :duration_minutes, :price_rub)
                    """
                ),
                {
                    "owner_id": owner_id,
                    "name": name,
                    "description": description,
                    "duration_minutes": duration_minutes,
                    "price_rub": price_rub or 0,
                },
            )
            event_type_id = result.lastrowid
        return self.find_event_type(owner_id, event_type_id)

    def update_event_type(
        self,
        owner_id: int,
        event_type_id: int,
        *,
        name: str,
        description: str | None,
        duration_minutes: int,
        price_rub: int | None,
    ) -> dict[str, Any] | None:
        current = self.find_event_type(owner_id, event_type_id)
        if current is None:
            return None
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE event_types
                    SET name = :name, description = :description,
                        duration_minutes = :duration_minutes, price_rub = :price_rub
                    WHERE owner_id = :owner_id AND id = :id
                    """
                ),
                {
                    "name": name,
                    "description": description,
                    "duration_minutes": duration_minutes,
                    "price_rub": price_rub if price_rub is not None else current["priceRub"],
                    "owner_id": owner_id,
                    "id": event_type_id,
                },
            )
            if result.rowcount == 0:
                return None
        return self.find_event_type(owner_id, event_type_id)

    def delete_event_type(self, owner_id: int, event_type_id: int) -> bool:
        with self._engine.connect() as conn:
            active = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS c FROM bookings
                    WHERE owner_id = :owner_id AND event_type_id = :event_type_id AND status = 'active'
                      AND starts_at > :now
                    """
                ),
                {"owner_id": owner_id, "event_type_id": event_type_id, "now": now_iso()},
            ).scalar_one()
        if active > 0:
            raise ValidationError("Нельзя удалить тип с активными будущими бронями")
        with self._engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM event_types WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": event_type_id},
            )
            return result.rowcount > 0

    # --- доступность -----------------------------------------------------

    def get_availability(self, owner_id: int) -> dict[str, Any]:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM availability WHERE owner_id = :owner_id"), {"owner_id": owner_id}
            ).mappings().first()
            return _map_availability(row)

    def set_availability(self, owner_id: int, availability: dict[str, Any]) -> dict[str, Any]:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO availability
                        (owner_id, timezone, rules_json, buffer_minutes, exceptions_json)
                    VALUES (:owner_id, :timezone, :rules_json, :buffer_minutes, :exceptions_json)
                    ON CONFLICT(owner_id) DO UPDATE SET
                        timezone = excluded.timezone,
                        rules_json = excluded.rules_json,
                        buffer_minutes = excluded.buffer_minutes,
                        exceptions_json = excluded.exceptions_json
                    """
                ),
                {
                    "owner_id": owner_id,
                    "timezone": availability["timezone"],
                    "rules_json": json.dumps(availability["rules"]),
                    "buffer_minutes": availability.get("bufferMinutes") or 0,
                    "exceptions_json": json.dumps(availability.get("exceptions") or []),
                },
            )
        return self.get_availability(owner_id)

    # --- брони -------------------------------------------------------------

    def get_active_bookings(self, owner_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"{_BOOKING_SELECT} WHERE b.owner_id = :owner_id AND b.status = 'active' ORDER BY b.starts_at"),
                {"owner_id": owner_id},
            ).mappings().all()
            return [_map_booking(r) for r in rows]

    def get_active_bookings_except(self, owner_id: int, booking_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"{_BOOKING_SELECT} WHERE b.owner_id = :owner_id AND b.status = 'active' "
                    "AND b.id != :booking_id ORDER BY b.starts_at"
                ),
                {"owner_id": owner_id, "booking_id": booking_id},
            ).mappings().all()
            return [_map_booking(r) for r in rows]

    def find_active_booking(self, owner_id: int, booking_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(f"{_BOOKING_SELECT} WHERE b.owner_id = :owner_id AND b.id = :id AND b.status = 'active'"),
                {"owner_id": owner_id, "id": booking_id},
            ).mappings().first()
            return _map_booking(row)

    def create_booking(self, owner_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        manage_token = str(uuid.uuid4())
        payment_status = data.get("paymentStatus") or "none"
        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO bookings (
                            owner_id, event_type_id, starts_at, ends_at,
                            guest_name, guest_email, comment, status, created_at, manage_token,
                            payment_status, series_id
                        ) VALUES (
                            :owner_id, :event_type_id, :starts_at, :ends_at,
                            :guest_name, :guest_email, :comment, 'active', :created_at, :manage_token,
                            :payment_status, :series_id
                        )
                        """
                    ),
                    {
                        "owner_id": owner_id,
                        "event_type_id": data["eventTypeId"],
                        "starts_at": data["startsAt"],
                        "ends_at": data["endsAt"],
                        "guest_name": data["guestName"],
                        "guest_email": data["guestEmail"],
                        "comment": data.get("comment"),
                        "created_at": now_iso(),
                        "manage_token": manage_token,
                        "payment_status": payment_status,
                        "series_id": data.get("seriesId"),
                    },
                )
                booking_id = result.lastrowid
                row = conn.execute(
                    text(f"{_BOOKING_SELECT} WHERE b.id = :id"), {"id": booking_id}
                ).mappings().first()
        except IntegrityError as exc:
            # Уникальный частичный индекс idx_bookings_owner_slot_active (0005) —
            # последний рубеж против гонки двойного бронирования, см. модуль docstring.
            raise SlotUnavailableError(
                "Слот уже занят, находится в прошлом или вне расписания"
            ) from exc
        return _map_booking_created(row)

    def cancel_booking(self, owner_id: int, booking_id: int) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM bookings WHERE owner_id = :owner_id AND id = :id AND status = 'active'"
                ),
                {"owner_id": owner_id, "id": booking_id},
            ).mappings().first()
            if row is None:
                return None
            conn.execute(text("UPDATE bookings SET status = 'cancelled' WHERE id = :id"), {"id": booking_id})
        return _map_booking_created({**row, "status": "cancelled"})

    def find_booking_by_manage_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM bookings WHERE manage_token = :token"), {"token": token}
            ).mappings().first()
            return _row(row)

    def get_guest_booking(self, token: str | None) -> dict[str, Any] | None:
        row = self.find_booking_by_manage_token(token)
        if row is None:
            return None
        owner = self.find_owner_by_id(row["owner_id"])
        event_type = self.find_event_type(row["owner_id"], row["event_type_id"])
        availability = self.get_availability(row["owner_id"])
        if owner is None or event_type is None:
            return None
        data = {
            "id": row["id"],
            "eventTypeName": event_type["name"],
            "durationMinutes": event_type["durationMinutes"],
            "ownerName": owner["name"],
            "ownerSlug": owner["slug"],
            "ownerTimezone": availability["timezone"],
            "startsAt": row["starts_at"],
            "endsAt": row["ends_at"],
            "guestName": row["guest_name"],
            "guestEmail": row["guest_email"],
            "status": row["status"],
            "paymentStatus": row["payment_status"] or "none",
            "_ownerId": row["owner_id"],
            "_eventTypeId": row["event_type_id"],
            "_manageToken": row["manage_token"],
        }
        if row["comment"]:
            data["comment"] = row["comment"]
        return data

    def cancel_booking_by_token(self, token: str | None) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM bookings WHERE manage_token = :token"), {"token": token}
            ).mappings().first() if token else None
            if row is None or row["status"] != "active":
                return None
            conn.execute(text("UPDATE bookings SET status = 'cancelled' WHERE id = :id"), {"id": row["id"]})
        return {**row, "status": "cancelled"}

    def reschedule_booking_by_token(
        self, token: str | None, *, starts_at: str, ends_at: str
    ) -> dict[str, Any] | None:
        row = self.find_booking_by_manage_token(token)
        if row is None or row["status"] != "active":
            return None
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE bookings SET starts_at = :starts_at, ends_at = :ends_at, reminder_sent_at = NULL
                        WHERE id = :id
                        """
                    ),
                    {"starts_at": starts_at, "ends_at": ends_at, "id": row["id"]},
                )
        except IntegrityError as exc:
            raise SlotUnavailableError(
                "Слот уже занят, находится в прошлом или вне расписания"
            ) from exc
        return self.get_guest_booking(token)

    # --- настройки уведомлений ---------------------------------------------

    def get_notification_settings(self, owner_id: int) -> dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM notification_settings WHERE owner_id = :owner_id"),
                {"owner_id": owner_id},
            ).mappings().first()
            if row is None:
                conn.execute(
                    text(
                        """
                        INSERT INTO notification_settings (owner_id, email_enabled, reminder_hours_before)
                        VALUES (:owner_id, 1, 24)
                        """
                    ),
                    {"owner_id": owner_id},
                )
                row = conn.execute(
                    text("SELECT * FROM notification_settings WHERE owner_id = :owner_id"),
                    {"owner_id": owner_id},
                ).mappings().first()
        data = {
            "emailEnabled": bool(row["email_enabled"]),
            "reminderHoursBefore": row["reminder_hours_before"],
        }
        if row["telegram_chat_id"]:
            data["telegramChatId"] = row["telegram_chat_id"]
        return data

    def set_notification_settings(self, owner_id: int, settings: dict[str, Any]) -> dict[str, Any]:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO notification_settings
                        (owner_id, email_enabled, telegram_chat_id, reminder_hours_before)
                    VALUES (:owner_id, :email_enabled, :telegram_chat_id, :reminder_hours_before)
                    ON CONFLICT(owner_id) DO UPDATE SET
                        email_enabled = excluded.email_enabled,
                        telegram_chat_id = excluded.telegram_chat_id,
                        reminder_hours_before = excluded.reminder_hours_before
                    """
                ),
                {
                    "owner_id": owner_id,
                    "email_enabled": 1 if settings.get("emailEnabled") else 0,
                    "telegram_chat_id": settings.get("telegramChatId") or None,
                    "reminder_hours_before": settings["reminderHoursBefore"],
                },
            )
        return self.get_notification_settings(owner_id)

    def list_due_reminders(self, now: str | None = None) -> list[dict[str, Any]]:
        now_value = now or now_iso()
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT b.*, o.email AS owner_email, o.name AS owner_name, o.slug AS owner_slug,
                           et.name AS event_type_name, et.duration_minutes,
                           ns.email_enabled, ns.telegram_chat_id, ns.reminder_hours_before
                    FROM bookings b
                    JOIN owners o ON o.id = b.owner_id
                    JOIN event_types et ON et.id = b.event_type_id
                    LEFT JOIN notification_settings ns ON ns.owner_id = b.owner_id
                    WHERE b.status = 'active'
                      AND b.reminder_sent_at IS NULL
                      AND b.starts_at > :now
                    """
                ),
                {"now": now_value},
            ).mappings().all()
        now_dt = datetime.fromisoformat(now_value)
        due = []
        for row in rows:
            hours = row["reminder_hours_before"] if row["reminder_hours_before"] is not None else 24
            starts_dt = datetime.fromisoformat(row["starts_at"])
            if starts_dt <= now_dt + timedelta(hours=hours):
                due.append(dict(row))
        return due

    def mark_reminder_sent(self, booking_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE bookings SET reminder_sent_at = :now WHERE id = :id"),
                {"now": now_iso(), "id": booking_id},
            )

    # --- P2: календари / busy-sync ------------------------------------------

    def list_calendar_connections(self, owner_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM calendar_connections WHERE owner_id = :owner_id ORDER BY id"),
                {"owner_id": owner_id},
            ).mappings().all()
            return [_map_calendar_connection(r) for r in rows]

    def find_calendar_connection(self, owner_id: int, connection_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM calendar_connections WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": connection_id},
            ).mappings().first()
            return _map_calendar_connection(row)

    def get_calendar_connection_row(self, owner_id: int, connection_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM calendar_connections WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": connection_id},
            ).mappings().first()
            return _row(row)

    def create_calendar_connection(
        self, owner_id: int, *, kind: str, label: str, config: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO calendar_connections (owner_id, kind, label, config_json, created_at)
                    VALUES (:owner_id, :kind, :label, :config_json, :created_at)
                    """
                ),
                {
                    "owner_id": owner_id,
                    "kind": kind,
                    "label": label,
                    "config_json": json.dumps(config or {}),
                    "created_at": now_iso(),
                },
            )
            connection_id = result.lastrowid
        return self.find_calendar_connection(owner_id, connection_id)

    def delete_calendar_connection(self, owner_id: int, connection_id: int) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM calendar_connections WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": connection_id},
            )
            return result.rowcount > 0

    def replace_busy_blocks(
        self, owner_id: int, connection_id: int, blocks: list[dict[str, str]]
    ) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM busy_blocks WHERE connection_id = :connection_id"),
                {"connection_id": connection_id},
            )
            for block in blocks:
                conn.execute(
                    text(
                        """
                        INSERT INTO busy_blocks (owner_id, connection_id, starts_at, ends_at)
                        VALUES (:owner_id, :connection_id, :starts_at, :ends_at)
                        """
                    ),
                    {
                        "owner_id": owner_id,
                        "connection_id": connection_id,
                        "starts_at": block["startsAt"],
                        "ends_at": block["endsAt"],
                    },
                )
            conn.execute(
                text("UPDATE calendar_connections SET last_synced_at = :now WHERE id = :id"),
                {"now": now_iso(), "id": connection_id},
            )
        return self.find_calendar_connection(owner_id, connection_id)

    def get_busy_blocks(self, owner_id: int, from_iso: str, to_iso: str) -> list[dict[str, str]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT starts_at AS startsAt, ends_at AS endsAt FROM busy_blocks
                    WHERE owner_id = :owner_id AND ends_at > :from_iso AND starts_at < :to_iso
                    ORDER BY starts_at
                    """
                ),
                {"owner_id": owner_id, "from_iso": from_iso, "to_iso": to_iso},
            ).mappings().all()
            return [{"startsAt": r["startsAt"], "endsAt": r["endsAt"]} for r in rows]

    # --- P2: организации -----------------------------------------------------

    def list_organizations_for_owner(self, owner_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT o.* FROM organizations o
                    JOIN organization_members m ON m.org_id = o.id
                    WHERE m.owner_id = :owner_id
                    ORDER BY o.id
                    """
                ),
                {"owner_id": owner_id},
            ).mappings().all()
            return [{"id": r["id"], "name": r["name"], "ownerId": r["owner_id"]} for r in rows]

    def find_organization(self, org_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM organizations WHERE id = :id"), {"id": org_id}
            ).mappings().first()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "ownerId": row["owner_id"]}

    def is_org_member(self, org_id: int, owner_id: int) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM organization_members WHERE org_id = :org_id AND owner_id = :owner_id"),
                {"org_id": org_id, "owner_id": owner_id},
            ).first()
            return row is not None

    def create_organization(self, owner_id: int, name: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text("INSERT INTO organizations (name, owner_id, created_at) VALUES (:name, :owner_id, :now)"),
                {"name": name, "owner_id": owner_id, "now": now_iso()},
            )
            org_id = result.lastrowid
            conn.execute(
                text(
                    "INSERT INTO organization_members (org_id, owner_id, role) VALUES (:org_id, :owner_id, 'owner')"
                ),
                {"org_id": org_id, "owner_id": owner_id},
            )
        return self.find_organization(org_id)

    def list_organization_members(self, org_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT o.id AS owner_id, o.name, o.email, o.slug, m.role
                    FROM organization_members m
                    JOIN owners o ON o.id = m.owner_id
                    WHERE m.org_id = :org_id
                    ORDER BY m.role DESC, o.id
                    """
                ),
                {"org_id": org_id},
            ).mappings().all()
            return [
                {
                    "ownerId": r["owner_id"],
                    "name": r["name"],
                    "email": r["email"],
                    "slug": r["slug"],
                    "role": r["role"],
                }
                for r in rows
            ]

    def create_organization_invite(self, org_id: int, email: str) -> dict[str, str]:
        token = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organization_invites (token, org_id, email, created_at) "
                    "VALUES (:token, :org_id, :email, :now)"
                ),
                {"token": token, "org_id": org_id, "email": email, "now": now_iso()},
            )
        return {"token": token, "joinPath": f"/team/join?token={token}"}

    def join_organization(self, owner: dict[str, Any], token: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            invite = conn.execute(
                text("SELECT * FROM organization_invites WHERE token = :token"), {"token": token}
            ).mappings().first()
            if invite is None:
                raise NotFoundError("Приглашение не найдено")
            if invite["email"].lower() != owner["email"].lower():
                raise ValidationError("Приглашение выдано на другой email")
            already_member = conn.execute(
                text("SELECT 1 FROM organization_members WHERE org_id = :org_id AND owner_id = :owner_id"),
                {"org_id": invite["org_id"], "owner_id": owner["id"]},
            ).first()
            if already_member is None:
                conn.execute(
                    text(
                        "INSERT INTO organization_members (org_id, owner_id, role) "
                        "VALUES (:org_id, :owner_id, 'member')"
                    ),
                    {"org_id": invite["org_id"], "owner_id": owner["id"]},
                )
            conn.execute(text("DELETE FROM organization_invites WHERE token = :token"), {"token": token})
            org_id = invite["org_id"]
        return self.find_organization(org_id)

    # --- P2: серии брони ------------------------------------------------------

    def _map_series(self, conn: Any, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        booking_ids = [
            r[0]
            for r in conn.execute(
                text("SELECT id FROM bookings WHERE series_id = :series_id ORDER BY starts_at"),
                {"series_id": row["id"]},
            ).all()
        ]
        data = {
            "id": row["id"],
            "eventTypeId": row["event_type_id"],
            "guestName": row["guest_name"],
            "guestEmail": row["guest_email"],
            "startsAt": row["starts_at"],
            "count": row["count"],
            "bookingIds": booking_ids,
        }
        if row["comment"]:
            data["comment"] = row["comment"]
        return data

    def list_booking_series(self, owner_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM booking_series WHERE owner_id = :owner_id ORDER BY id DESC"),
                {"owner_id": owner_id},
            ).mappings().all()
            return [self._map_series(conn, r) for r in rows]

    def find_booking_series(self, owner_id: int, series_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM booking_series WHERE owner_id = :owner_id AND id = :id"),
                {"owner_id": owner_id, "id": series_id},
            ).mappings().first()
            return self._map_series(conn, row)

    def create_booking_series_record(self, owner_id: int, data: dict[str, Any]) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO booking_series
                        (owner_id, event_type_id, guest_name, guest_email, comment, starts_at, count, created_at)
                    VALUES
                        (:owner_id, :event_type_id, :guest_name, :guest_email, :comment, :starts_at, :count, :now)
                    """
                ),
                {
                    "owner_id": owner_id,
                    "event_type_id": data["eventTypeId"],
                    "guest_name": data["guestName"],
                    "guest_email": data["guestEmail"],
                    "comment": data.get("comment"),
                    "starts_at": data["startsAt"],
                    "count": data["count"],
                    "now": now_iso(),
                },
            )
            return result.lastrowid

    def cancel_booking_series(self, owner_id: int, series_id: int) -> bool:
        series = self.find_booking_series(owner_id, series_id)
        if series is None:
            return False
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE bookings SET status = 'cancelled'
                    WHERE series_id = :series_id AND status = 'active' AND starts_at > :now
                    """
                ),
                {"series_id": series_id, "now": now_iso()},
            )
        return True

    # --- P2: аналитика ---------------------------------------------------------

    def get_analytics_summary(self, owner_id: int, from_date: str, to_date: str) -> dict[str, Any]:
        from_iso = f"{from_date}T00:00:00.000Z"
        to_exclusive = (
            datetime.fromisoformat(f"{to_date}T00:00:00+00:00") + timedelta(days=1)
        ).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        with self._engine.connect() as conn:
            created = conn.execute(
                text(
                    "SELECT COUNT(*) FROM bookings WHERE owner_id = :owner_id "
                    "AND created_at >= :from_iso AND created_at < :to_exclusive"
                ),
                {"owner_id": owner_id, "from_iso": from_iso, "to_exclusive": to_exclusive},
            ).scalar_one()
            cancelled = conn.execute(
                text(
                    "SELECT COUNT(*) FROM bookings WHERE owner_id = :owner_id AND status = 'cancelled' "
                    "AND created_at >= :from_iso AND created_at < :to_exclusive"
                ),
                {"owner_id": owner_id, "from_iso": from_iso, "to_exclusive": to_exclusive},
            ).scalar_one()
            upcoming = conn.execute(
                text(
                    "SELECT COUNT(*) FROM bookings WHERE owner_id = :owner_id AND status = 'active' "
                    "AND starts_at > :now"
                ),
                {"owner_id": owner_id, "now": now_iso()},
            ).scalar_one()
            rows = conn.execute(
                text(
                    "SELECT starts_at FROM bookings WHERE owner_id = :owner_id "
                    "AND created_at >= :from_iso AND created_at < :to_exclusive"
                ),
                {"owner_id": owner_id, "from_iso": from_iso, "to_exclusive": to_exclusive},
            ).all()

        by_weekday = [0, 0, 0, 0, 0, 0, 0]
        for (starts_at,) in rows:
            iso_weekday = datetime.fromisoformat(starts_at).isoweekday()
            by_weekday[iso_weekday - 1] += 1

        return {
            "from": from_date,
            "to": to_date,
            "created": created,
            "cancelled": cancelled,
            "upcoming": upcoming,
            "byWeekday": by_weekday,
        }

    # --- P2: платежи -----------------------------------------------------------

    def create_payment_record(
        self,
        *,
        booking_id: int,
        amount_rub: int,
        status: str,
        provider: str,
        provider_payment_id: str | None = None,
        confirmation_url: str,
    ) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO payments
                        (booking_id, amount_rub, status, provider, provider_payment_id, confirmation_url, created_at)
                    VALUES
                        (:booking_id, :amount_rub, :status, :provider, :provider_payment_id, :confirmation_url, :now)
                    """
                ),
                {
                    "booking_id": booking_id,
                    "amount_rub": amount_rub,
                    "status": status,
                    "provider": provider,
                    "provider_payment_id": provider_payment_id,
                    "confirmation_url": confirmation_url,
                    "now": now_iso(),
                },
            )
            payment_id = result.lastrowid
            row = conn.execute(
                text("SELECT * FROM payments WHERE id = :id"), {"id": payment_id}
            ).mappings().first()
        return _map_payment(row)

    def update_payment_details(
        self,
        payment_id: int,
        *,
        provider: str | None = None,
        provider_payment_id: str | None = None,
        confirmation_url: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE payments
                    SET provider = COALESCE(:provider, provider),
                        provider_payment_id = COALESCE(:provider_payment_id, provider_payment_id),
                        confirmation_url = COALESCE(:confirmation_url, confirmation_url),
                        status = COALESCE(:status, status)
                    WHERE id = :id
                    """
                ),
                {
                    "provider": provider,
                    "provider_payment_id": provider_payment_id,
                    "confirmation_url": confirmation_url,
                    "status": status,
                    "id": payment_id,
                },
            )
        return self.find_payment(payment_id)

    def find_payment(self, payment_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM payments WHERE id = :id"), {"id": payment_id}
            ).mappings().first()
            return _map_payment(row)

    def find_payment_by_booking(self, booking_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM payments WHERE booking_id = :booking_id ORDER BY id DESC LIMIT 1"),
                {"booking_id": booking_id},
            ).mappings().first()
            return _map_payment(row)

    def mark_payment_paid(self, payment_id: int) -> dict[str, Any] | None:
        payment = self.find_payment(payment_id)
        if payment is None:
            return None
        with self._engine.begin() as conn:
            conn.execute(text("UPDATE payments SET status = 'paid' WHERE id = :id"), {"id": payment_id})
            conn.execute(
                text("UPDATE bookings SET payment_status = 'paid' WHERE id = :id"),
                {"id": payment["bookingId"]},
            )
        return self.find_payment(payment_id)

    def find_payment_by_provider_id(self, provider_payment_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM payments WHERE provider_payment_id = :provider_payment_id"),
                {"provider_payment_id": provider_payment_id},
            ).mappings().first()
            return _map_payment(row)
