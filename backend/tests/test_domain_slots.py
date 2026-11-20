"""Тесты домена слотов — сверены с эталонным выводом `backend/src/slots.js`
(см. port-to-python-plan.md §4.3) на тех же входных данных."""

from datetime import UTC, datetime

from app.domain.slots import (
    compute_free_slots,
    intervals_for_day,
    is_free_slot,
    validate_availability,
    validate_duration_minutes,
)

WEEKDAY_AVAILABILITY = {
    "timezone": "Europe/Moscow",
    "bufferMinutes": 0,
    "rules": [
        {"weekday": w, "startTime": "10:00", "endTime": "18:00"} for w in (1, 2, 3, 4, 5)
    ],
    "exceptions": [],
}


def test_intervals_for_day_uses_weekday_rule():
    # 2026-09-15 — вторник (isoweekday=2)
    assert intervals_for_day(WEEKDAY_AVAILABILITY, "2026-09-15") == [
        {"startTime": "10:00", "endTime": "18:00"}
    ]
    # 2026-09-19 — суббота, правил нет
    assert intervals_for_day(WEEKDAY_AVAILABILITY, "2026-09-19") == []


def test_intervals_for_day_exception_overrides_rules():
    availability = {
        **WEEKDAY_AVAILABILITY,
        "exceptions": [{"date": "2026-09-15", "intervals": [{"startTime": "12:00", "endTime": "14:00"}]}],
    }
    assert intervals_for_day(availability, "2026-09-15") == [
        {"startTime": "12:00", "endTime": "14:00"}
    ]


def test_compute_free_slots_matches_js_reference():
    """Эталонный вывод получен вызовом computeFreeSlots из backend/src/slots.js
    с теми же аргументами (см. историю разработки порта)."""
    availability = {
        "timezone": "Europe/Moscow",
        "bufferMinutes": 15,
        "rules": [
            {"weekday": w, "startTime": "10:00", "endTime": "18:00"} for w in (1, 2, 3, 4, 5)
        ],
        "exceptions": [
            {"date": "2026-09-17", "intervals": [{"startTime": "12:00", "endTime": "14:00"}]}
        ],
    }
    active_bookings = [
        {"startsAt": "2026-09-16T08:00:00.000Z", "endsAt": "2026-09-16T08:30:00.000Z"}
    ]
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

    slots = compute_free_slots(
        availability=availability,
        active_bookings=active_bookings,
        external_busy=[],
        from_="2026-09-15",
        to="2026-09-20",
        duration_minutes=30,
        now=now,
    )

    assert len(slots) == 38
    assert slots[0] == {"startsAt": "2026-09-15T12:30:00.000Z", "endsAt": "2026-09-15T13:00:00.000Z"}
    # буфер 15 минут вокруг брони 08:00–08:30Z не даёт слотов 07:30Z и 08:30Z в этот день
    day_16 = [s for s in slots if s["startsAt"].startswith("2026-09-16")]
    assert {"startsAt": "2026-09-16T07:30:00.000Z", "endsAt": "2026-09-16T08:00:00.000Z"} not in day_16
    assert {"startsAt": "2026-09-16T08:30:00.000Z", "endsAt": "2026-09-16T09:00:00.000Z"} not in day_16
    # исключение 17-го ограничивает день интервалом 12:00–14:00 по Москве (09:00–11:00Z)
    day_17 = [s for s in slots if s["startsAt"].startswith("2026-09-17")]
    assert day_17 == [
        {"startsAt": "2026-09-17T09:00:00.000Z", "endsAt": "2026-09-17T09:30:00.000Z"},
        {"startsAt": "2026-09-17T09:30:00.000Z", "endsAt": "2026-09-17T10:00:00.000Z"},
        {"startsAt": "2026-09-17T10:00:00.000Z", "endsAt": "2026-09-17T10:30:00.000Z"},
        {"startsAt": "2026-09-17T10:30:00.000Z", "endsAt": "2026-09-17T11:00:00.000Z"},
    ]
    # горизонт — 14 дней от «сегодня» (now), 20-е за пределами горизонта не должно быть слотов
    assert all(not s["startsAt"].startswith("2026-09-20") for s in slots)


def test_compute_free_slots_short_duration_returns_empty():
    assert (
        compute_free_slots(
            availability=WEEKDAY_AVAILABILITY,
            active_bookings=[],
            from_="2026-09-15",
            to="2026-09-15",
            duration_minutes=10,
        )
        == []
    )


def test_is_free_slot_true_for_open_slot_in_future():
    now = datetime(2026, 9, 15, 6, 0, 0, tzinfo=UTC)  # 09:00 MSK
    assert is_free_slot(
        availability=WEEKDAY_AVAILABILITY,
        active_bookings=[],
        starts_at="2026-09-15T07:00:00.000Z",  # 10:00 MSK
        duration_minutes=30,
        now=now,
    )


def test_is_free_slot_false_for_past_slot():
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    assert not is_free_slot(
        availability=WEEKDAY_AVAILABILITY,
        active_bookings=[],
        starts_at="2026-09-15T07:00:00.000Z",
        duration_minutes=30,
        now=now,
    )


def test_is_free_slot_false_when_booked():
    now = datetime(2026, 9, 15, 6, 0, 0, tzinfo=UTC)
    active_bookings = [
        {"startsAt": "2026-09-15T07:00:00.000Z", "endsAt": "2026-09-15T07:30:00.000Z"}
    ]
    assert not is_free_slot(
        availability=WEEKDAY_AVAILABILITY,
        active_bookings=active_bookings,
        starts_at="2026-09-15T07:00:00.000Z",
        duration_minutes=30,
        now=now,
    )


def test_validate_duration_minutes():
    assert validate_duration_minutes(30) is None
    assert validate_duration_minutes(10) is not None  # меньше 15
    assert validate_duration_minutes(250) is not None  # больше 240
    assert validate_duration_minutes(20) is not None  # не кратно 15
    assert validate_duration_minutes(True) is not None  # bool — не целое число минут
    assert validate_duration_minutes("30") is not None


def test_validate_availability_matches_js_reference():
    cases_and_expected = [
        (
            {"timezone": "Not/AZone", "bufferMinutes": 10, "rules": [], "exceptions": []},
            [
                {"field": "timezone", "message": "Неизвестный IANA-часовой пояс"},
                {"field": "bufferMinutes", "message": "Буфер: 0–120 минут, кратно 15"},
            ],
        ),
        (
            {
                "timezone": "Europe/Moscow",
                "bufferMinutes": 7,
                "rules": [
                    {"weekday": 1, "startTime": "10:00", "endTime": "11:00"},
                    {"weekday": 1, "startTime": "10:30", "endTime": "12:00"},
                ],
                "exceptions": [],
            },
            [
                {"field": "bufferMinutes", "message": "Буфер: 0–120 минут, кратно 15"},
                {"field": "rules[1]", "message": "Интервал пересекается с правилом 1 в тот же день"},
            ],
        ),
        (
            {
                "timezone": "Europe/Moscow",
                "bufferMinutes": 0,
                "rules": [{"weekday": 1, "startTime": "11:00", "endTime": "10:00"}],
                "exceptions": [
                    {"date": "bad-date", "intervals": []},
                    {
                        "date": "2026-09-17",
                        "intervals": [{"startTime": "10:05", "endTime": "11:00"}],
                    },
                ],
            },
            [
                {"field": "rules[0]", "message": "Конец интервала должен быть позже начала"},
                {"field": "exceptions[0].date", "message": "Ожидается дата YYYY-MM-DD"},
                {
                    "field": "exceptions[1].intervals[0]",
                    "message": "Интервал должен быть кратен 15 минутам",
                },
            ],
        ),
    ]
    for availability, expected in cases_and_expected:
        assert validate_availability(availability) == expected
