"""Домен слотов: порт `backend/src/slots.js`.

Правила доступности считаются в таймзоне владельца (stdlib `zoneinfo`),
хранение и сравнение — в UTC. Функции ниже работают с обычными словарями
(камелкейс-ключи — как в JSON-контракте), без зависимости от FastAPI/БД —
см. правило в `port-to-python-plan.md` §3.2.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.timeutil import now_utc, parse_iso, to_iso_z

GRID_MINUTES = 15
"""Базовая кратность интервалов доступности и длительности типов событий."""

BOOKING_HORIZON_DAYS = 14
"""Горизонт бронирования: слоты доступны на 14 дней вперёд, включая сегодня."""

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalize_availability(availability: dict[str, Any]) -> dict[str, Any]:
    buffer_minutes = availability.get("bufferMinutes")
    return {
        "timezone": availability["timezone"],
        "bufferMinutes": buffer_minutes if _is_plain_int(buffer_minutes) else 0,
        "rules": availability.get("rules") or [],
        "exceptions": availability.get("exceptions") or [],
    }


def intervals_for_day(availability: dict[str, Any], day_str: str) -> list[dict[str, str]]:
    """Интервалы работы на календарный день (с учётом исключений)."""
    avail = _normalize_availability(availability)
    exception = next((e for e in avail["exceptions"] if e.get("date") == day_str), None)
    if exception is not None:
        return list(exception.get("intervals") or [])

    day = date.fromisoformat(day_str)
    iso_weekday = day.isoweekday()  # Пн=1 … Вс=7 — как в JS-версии
    return [
        {"startTime": rule["startTime"], "endTime": rule["endTime"]}
        for rule in avail["rules"]
        if rule["weekday"] == iso_weekday
    ]


def compute_free_slots(
    *,
    availability: dict[str, Any],
    active_bookings: list[dict[str, Any]],
    external_busy: list[dict[str, Any]] | None = None,
    from_: str,
    to: str,
    duration_minutes: int,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Свободные слоты длительностью duration_minutes.

    Учитывает исключения, буфер вокруг активных броней и внешнюю занятость
    (календари).
    """
    external_busy = external_busy or []
    now = now or now_utc()

    if not _is_plain_int(duration_minutes) or duration_minutes < GRID_MINUTES:
        return []

    avail = _normalize_availability(availability)
    tz = ZoneInfo(avail["timezone"])
    buffer_delta = timedelta(minutes=avail["bufferMinutes"])

    blocked: list[tuple[datetime, datetime]] = [
        (parse_iso(b["startsAt"]) - buffer_delta, parse_iso(b["endsAt"]) + buffer_delta)
        for b in active_bookings
    ] + [(parse_iso(b["startsAt"]), parse_iso(b["endsAt"])) for b in external_busy]

    slots: list[dict[str, str]] = []

    today_in_tz = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_end = today_in_tz + timedelta(days=BOOKING_HORIZON_DAYS - 1)

    start = date.fromisoformat(from_)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=tz)
    start_dt = max(start_dt, today_in_tz)

    finish = date.fromisoformat(to)
    finish_dt = datetime(finish.year, finish.month, finish.day, tzinfo=tz)
    finish_dt = min(finish_dt, horizon_end)

    day = start_dt
    while day.date() <= finish_dt.date():
        day_str = day.strftime("%Y-%m-%d")
        for interval in intervals_for_day(avail, day_str):
            start_h, start_m = map(int, interval["startTime"].split(":"))
            end_h, end_m = map(int, interval["endTime"].split(":"))
            cursor = datetime(day.year, day.month, day.day, start_h, start_m, tzinfo=tz)
            end = datetime(day.year, day.month, day.day, end_h, end_m, tzinfo=tz)
            duration = timedelta(minutes=duration_minutes)
            while cursor + duration <= end:
                slot_start = cursor
                slot_end = cursor + duration
                conflict = any(
                    _overlaps(slot_start, slot_end, b_start, b_end) for b_start, b_end in blocked
                )
                if slot_start > now and not conflict:
                    slots.append(
                        {"startsAt": to_iso_z(slot_start), "endsAt": to_iso_z(slot_end)}
                    )
                cursor = cursor + duration
        day = day + timedelta(days=1)

    slots.sort(key=lambda s: s["startsAt"])
    return slots


def is_free_slot(
    *,
    availability: dict[str, Any],
    active_bookings: list[dict[str, Any]],
    external_busy: list[dict[str, Any]] | None = None,
    starts_at: str,
    duration_minutes: int,
    now: datetime | None = None,
) -> bool:
    now = now or now_utc()
    try:
        start = parse_iso(starts_at)
    except ValueError:
        return False
    if start <= now:
        return False

    tz = ZoneInfo(_normalize_availability(availability)["timezone"])
    day_in_owner_tz = start.astimezone(tz).strftime("%Y-%m-%d")
    slots = compute_free_slots(
        availability=availability,
        active_bookings=active_bookings,
        external_busy=external_busy,
        from_=day_in_owner_tz,
        to=day_in_owner_tz,
        duration_minutes=duration_minutes,
        now=now,
    )
    return any(parse_iso(s["startsAt"]) == start for s in slots)


def validate_duration_minutes(duration_minutes: Any) -> str | None:
    if not _is_plain_int(duration_minutes):
        return "Длительность должна быть целым числом минут"
    if duration_minutes < 15 or duration_minutes > 240:
        return "Длительность должна быть от 15 до 240 минут"
    if duration_minutes % GRID_MINUTES != 0:
        return f"Длительность должна быть кратна {GRID_MINUTES} минутам"
    return None


def _validate_intervals(
    intervals: list[dict[str, str]], field_prefix: str, errors: list[dict[str, str]]
) -> None:
    for i, interval in enumerate(intervals):
        start = _to_minutes(interval["startTime"])
        end = _to_minutes(interval["endTime"])
        if end <= start:
            errors.append(
                {"field": f"{field_prefix}[{i}]", "message": "Конец интервала должен быть позже начала"}
            )
        if (end - start) % GRID_MINUTES != 0:
            errors.append(
                {
                    "field": f"{field_prefix}[{i}]",
                    "message": f"Интервал должен быть кратен {GRID_MINUTES} минутам",
                }
            )
    for i in range(len(intervals)):
        a_start, a_end = _to_minutes(intervals[i]["startTime"]), _to_minutes(intervals[i]["endTime"])
        for j in range(i + 1, len(intervals)):
            b_start, b_end = _to_minutes(intervals[j]["startTime"]), _to_minutes(intervals[j]["endTime"])
            if a_start < b_end and b_start < a_end:
                errors.append(
                    {
                        "field": f"{field_prefix}[{j}]",
                        "message": f"Интервал пересекается с интервалом {i + 1}",
                    }
                )


def _is_valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_availability(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Валидация правил доступности, буфера и исключений."""
    availability = _normalize_availability(raw)
    errors: list[dict[str, str]] = []

    try:
        ZoneInfo(availability["timezone"])
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        errors.append({"field": "timezone", "message": "Неизвестный IANA-часовой пояс"})

    buffer_minutes = availability["bufferMinutes"]
    if (
        not _is_plain_int(buffer_minutes)
        or buffer_minutes < 0
        or buffer_minutes > 120
        or buffer_minutes % GRID_MINUTES != 0
    ):
        errors.append(
            {"field": "bufferMinutes", "message": f"Буфер: 0–120 минут, кратно {GRID_MINUTES}"}
        )

    # Группируем недельные правила по дню и проверяем как интервалы
    by_weekday: dict[int, list[dict[str, Any]]] = {}
    for i, rule in enumerate(availability["rules"]):
        start = _to_minutes(rule["startTime"])
        end = _to_minutes(rule["endTime"])
        if end <= start:
            errors.append({"field": f"rules[{i}]", "message": "Конец интервала должен быть позже начала"})
        if (end - start) % GRID_MINUTES != 0:
            errors.append(
                {"field": f"rules[{i}]", "message": f"Интервал должен быть кратен {GRID_MINUTES} минутам"}
            )
        by_weekday.setdefault(rule["weekday"], []).append({**rule, "_index": i})

    for day_rules in by_weekday.values():
        for i in range(len(day_rules)):
            a_start = _to_minutes(day_rules[i]["startTime"])
            a_end = _to_minutes(day_rules[i]["endTime"])
            for j in range(i + 1, len(day_rules)):
                b_start = _to_minutes(day_rules[j]["startTime"])
                b_end = _to_minutes(day_rules[j]["endTime"])
                if a_start < b_end and b_start < a_end:
                    errors.append(
                        {
                            "field": f"rules[{day_rules[j]['_index']}]",
                            "message": f"Интервал пересекается с правилом {day_rules[i]['_index'] + 1} в тот же день",
                        }
                    )

    seen_dates: set[str] = set()
    for i, exception in enumerate(availability["exceptions"]):
        exception_date = exception.get("date", "")
        if not _DATE_RE.match(exception_date) or not _is_valid_date(exception_date):
            errors.append({"field": f"exceptions[{i}].date", "message": "Ожидается дата YYYY-MM-DD"})
        if exception_date in seen_dates:
            errors.append({"field": f"exceptions[{i}].date", "message": "Дата исключения уже указана"})
        seen_dates.add(exception_date)
        _validate_intervals(exception.get("intervals") or [], f"exceptions[{i}].intervals", errors)

    return errors
