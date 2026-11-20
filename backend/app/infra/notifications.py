"""Уведомления: email (SMTP) + Telegram Bot API.

Порт `backend/src/notifications.js`. Без SMTP_URL / TELEGRAM_BOT_TOKEN
сообщения пишутся в лог (удобно для тестов и dev) — то же поведение,
что и в JS-версии.

Переменные:
- PUBLIC_BASE_URL — база ссылок для гостя (по умолчанию http://localhost:5173)
- SMTP_URL — например smtp://user:pass@smtp.example.com:587
- EMAIL_FROM — From: (по умолчанию Call Calendar <noreply@localhost>)
- TELEGRAM_BOT_TOKEN — токен бота @BotFather
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from babel.dates import format_datetime

from app.domain.timeutil import parse_iso
from app.infra.store import Store

logger = logging.getLogger("call_calendar.notifications")

NotificationKind = Literal["created", "cancelled", "rescheduled", "reminder"]

_TITLES: dict[str, str] = {
    "created": "Встреча забронирована",
    "cancelled": "Встреча отменена",
    "rescheduled": "Встреча перенесена",
    "reminder": "Напоминание о встрече",
}


def _public_base() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "http://localhost:5173").rstrip("/")


def _manage_url(token: str) -> str:
    return f"{_public_base()}/b/{token}"


def _format_when(iso: str, timezone: str) -> str:
    try:
        local = parse_iso(iso).astimezone(ZoneInfo(timezone))
        return format_datetime(local, format="long", locale="ru")
    except Exception:  # noqa: BLE001 — текст письма не должен падать из-за формата даты
        return iso


def _send_email_sync(*, to: str, subject: str, text: str) -> dict[str, bool]:
    smtp_url = os.environ.get("SMTP_URL")
    from_addr = os.environ.get("EMAIL_FROM") or "Call Calendar <noreply@localhost>"

    if not smtp_url:
        logger.info("[email:dry-run] to=%s subject=%s\n%s", to, subject, text)
        return {"dryRun": True}

    parsed = urlparse(smtp_url)
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)

    host = parsed.hostname or "localhost"
    port = parsed.port or (465 if parsed.scheme == "smtps" else 587)
    smtp_cls = smtplib.SMTP_SSL if parsed.scheme == "smtps" else smtplib.SMTP
    with smtp_cls(host, port, timeout=15) as client:
        if parsed.scheme != "smtps":
            client.starttls()
        if parsed.username:
            client.login(parsed.username, parsed.password or "")
        client.send_message(message)
    return {"dryRun": False}


async def _send_telegram(chat_id: str | None, text: str) -> dict[str, bool]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        if chat_id:
            logger.info("[telegram:dry-run] chat=%s\n%s", chat_id, text)
        return {"dryRun": True}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
    if response.is_error:
        raise RuntimeError(f"Telegram API {response.status_code}: {response.text}")
    return {"dryRun": False}


async def notify_booking_event(
    *,
    kind: NotificationKind,
    booking: dict[str, Any],
    owner: dict[str, Any],
    event_type: dict[str, Any],
    availability: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    when = _format_when(booking["startsAt"], availability["timezone"])
    manage_token = booking.get("manageToken")
    link = _manage_url(manage_token) if manage_token else None
    title = _TITLES.get(kind, "Уведомление о встрече")

    guest_lines = [
        title,
        f"{event_type['name']} · {event_type['durationMinutes']} мин",
        f"С {owner['name']}: {when} ({availability['timezone']})",
    ]
    if link:
        guest_lines.append(f"Управление записью: {link}")

    owner_lines = [
        title,
        f"{event_type['name']} с {booking['guestName']} <{booking['guestEmail']}>",
        f"Когда: {when} ({availability['timezone']})",
    ]
    if booking.get("comment"):
        owner_lines.append(f"Комментарий: {booking['comment']}")

    if settings.get("emailEnabled", True) is not False:
        _send_email_sync(
            to=booking["guestEmail"],
            subject=f"{title}: {event_type['name']}",
            text="\n".join(guest_lines),
        )
        _send_email_sync(
            to=owner["email"],
            subject=f"{title}: {booking['guestName']}",
            text="\n".join(owner_lines),
        )

    telegram_chat_id = settings.get("telegramChatId")
    if telegram_chat_id:
        try:
            await _send_telegram(telegram_chat_id, "\n".join(owner_lines))
        except Exception:
            logger.exception("telegram notification failed")


def _pick(row: dict[str, Any], camel: str, snake: str) -> Any:
    """`row[camel] ?? row[snake]` — брони приходят и из mapped-строк store.py
    (camelCase), и из «сырых» строк SQLite (snake_case), как и в JS-версии
    (см. notifyForOwnerBooking в app.js)."""
    value = row.get(camel)
    return value if value is not None else row.get(snake)


async def notify_for_owner_booking(
    store: Store, owner: dict[str, Any], booking_row: dict[str, Any], kind: NotificationKind
) -> None:
    """Порт `notifyForOwnerBooking` из app.js — общий путь для всех маршрутов,
    уведомляющих владельца/гостя о создании/отмене/переносе брони."""
    event_type_id = _pick(booking_row, "eventTypeId", "event_type_id")
    event_type = store.find_event_type(owner["id"], event_type_id)
    if event_type is None:
        return
    availability = store.get_availability(owner["id"])
    settings = store.get_notification_settings(owner["id"])
    booking = {
        "startsAt": _pick(booking_row, "startsAt", "starts_at"),
        "endsAt": _pick(booking_row, "endsAt", "ends_at"),
        "guestName": _pick(booking_row, "guestName", "guest_name"),
        "guestEmail": _pick(booking_row, "guestEmail", "guest_email"),
        "comment": booking_row.get("comment"),
        "manageToken": _pick(booking_row, "manageToken", "manage_token"),
    }
    await notify_booking_event(
        kind=kind, booking=booking, owner=owner, event_type=event_type,
        availability=availability, settings=settings,
    )


async def process_reminders(store: Store) -> None:
    """Фоновый проход напоминаний (вызывается из lifespan раз в минуту)."""
    for row in store.list_due_reminders():
        try:
            await notify_booking_event(
                kind="reminder",
                booking={
                    "startsAt": row["starts_at"],
                    "endsAt": row["ends_at"],
                    "guestName": row["guest_name"],
                    "guestEmail": row["guest_email"],
                    "comment": row["comment"],
                    "manageToken": row["manage_token"],
                },
                owner={
                    "id": row["owner_id"],
                    "name": row["owner_name"],
                    "email": row["owner_email"],
                    "slug": row["owner_slug"],
                },
                event_type={
                    "name": row["event_type_name"],
                    "durationMinutes": row["duration_minutes"],
                },
                availability=store.get_availability(row["owner_id"]),
                settings={
                    "emailEnabled": bool(row["email_enabled"]),
                    "telegramChatId": row["telegram_chat_id"] or None,
                    "reminderHoursBefore": row["reminder_hours_before"],
                },
            )
            store.mark_reminder_sent(row["id"])
        except Exception:
            logger.exception("reminder failed for booking %s", row["id"])
