"""Тесты слоя данных (infra/store.py) — порт ключевых сценариев из
backend/test/api.test.js на уровне store, без HTTP."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine

from app.domain.errors import (
    AlreadyExistsError,
    NotFoundError,
    SlotUnavailableError,
    ValidationError,
)
from app.infra.store import Store


def _make_owner(store: Store, *, email="owner@example.com", slug="kirill") -> dict:
    return store.create_owner(name="Кирилл", email=email, password="secret", slug=slug)


# --- владельцы / сессии ---------------------------------------------------


def test_create_owner_seeds_availability_and_event_type(store: Store):
    owner = _make_owner(store)
    assert owner["email"] == "owner@example.com"
    assert owner["plan"] == "free"

    availability = store.get_availability(owner["id"])
    assert availability["timezone"] == "Europe/Moscow"
    assert len(availability["rules"]) == 5

    event_types = store.list_event_types(owner["id"])
    assert len(event_types) == 1
    assert event_types[0]["name"] == "Вводный звонок"


def test_create_owner_duplicate_email_or_slug_raises(store: Store):
    _make_owner(store)
    with pytest.raises(AlreadyExistsError):
        store.create_owner(name="Другой", email="OWNER@example.com", password="x", slug="other")
    with pytest.raises(AlreadyExistsError):
        store.create_owner(name="Другой", email="other@example.com", password="x", slug="KIRILL")


def test_check_credentials_and_sessions(store: Store):
    _make_owner(store)
    assert store.check_credentials("owner@example.com", "secret") is not None
    assert store.check_credentials("owner@example.com", "wrong") is None
    assert store.check_credentials("nobody@example.com", "secret") is None

    owner = store.check_credentials("owner@example.com", "secret")
    token = store.create_session(owner["id"])
    assert store.get_session_owner(token)["id"] == owner["id"]
    assert store.get_session_owner("bogus-token") is None
    assert store.get_session_owner(None) is None

    store.destroy_session(token)
    assert store.get_session_owner(token) is None


# --- типы событий ----------------------------------------------------------


def test_event_type_crud_and_delete_guard(store: Store):
    owner = _make_owner(store)
    created = store.create_event_type(
        owner["id"], name="Консультация", description=None, duration_minutes=60, price_rub=0
    )
    assert created["durationMinutes"] == 60
    assert "description" not in created

    updated = store.update_event_type(
        owner["id"], created["id"], name="Консультация+", description="долгая", duration_minutes=90, price_rub=500
    )
    assert updated["name"] == "Консультация+"
    assert updated["priceRub"] == 500

    assert store.update_event_type(owner["id"], 999999, name="x", description=None, duration_minutes=30, price_rub=0) is None

    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": created["id"],
            "startsAt": "2099-01-05T10:00:00.000Z",
            "endsAt": "2099-01-05T11:30:00.000Z",
            "guestName": "Гость",
            "guestEmail": "guest@example.com",
        },
    )
    assert booking is not None
    with pytest.raises(ValidationError):
        store.delete_event_type(owner["id"], created["id"])

    # Тип без единой брони (в т.ч. отменённой) — FK без ON DELETE в схеме
    # (как в JS-версии) не даёт удалить тип, на который ссылается ЛЮБАЯ бронь.
    unused = store.create_event_type(
        owner["id"], name="Неиспользуемый", description=None, duration_minutes=30, price_rub=0
    )
    assert store.delete_event_type(owner["id"], unused["id"]) is True
    assert store.delete_event_type(owner["id"], unused["id"]) is False


# --- доступность -------------------------------------------------------------


def test_set_and_get_availability_roundtrip(store: Store):
    owner = _make_owner(store)
    new_availability = {
        "timezone": "Asia/Yekaterinburg",
        "bufferMinutes": 15,
        "rules": [{"weekday": 3, "startTime": "09:00", "endTime": "12:00"}],
        "exceptions": [{"date": "2099-01-01", "intervals": []}],
    }
    result = store.set_availability(owner["id"], new_availability)
    assert result == new_availability
    assert store.get_availability(owner["id"]) == new_availability


# --- брони + гонка бронирования (§2.3 плана порта) --------------------------


def test_create_and_cancel_booking(store: Store):
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-02-01T10:00:00.000Z",
            "endsAt": "2099-02-01T10:30:00.000Z",
            "guestName": "Гость",
            "guestEmail": "guest@example.com",
        },
    )
    assert booking["status"] == "active"
    assert "manageToken" in booking

    active = store.get_active_bookings(owner["id"])
    assert len(active) == 1

    cancelled = store.cancel_booking(owner["id"], booking["id"])
    assert cancelled["status"] == "cancelled"
    assert store.get_active_bookings(owner["id"]) == []
    assert store.cancel_booking(owner["id"], booking["id"]) is None


def test_create_booking_same_slot_raises_slot_unavailable(store: Store):
    """Последовательная гонка: второй INSERT на тот же (owner_id, starts_at)
    должен упасть на уникальном индексе idx_bookings_owner_slot_active."""
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    payload = {
        "eventTypeId": et["id"],
        "startsAt": "2099-03-01T10:00:00.000Z",
        "endsAt": "2099-03-01T10:30:00.000Z",
        "guestName": "Гость 1",
        "guestEmail": "guest1@example.com",
    }
    first = store.create_booking(owner["id"], payload)
    assert first is not None

    with pytest.raises(SlotUnavailableError):
        store.create_booking(owner["id"], {**payload, "guestName": "Гость 2", "guestEmail": "guest2@example.com"})


def test_create_booking_concurrent_same_slot_only_one_succeeds(file_engine: Engine):
    """Регресс-тест на §2.3 port-to-python-plan.md: в асинхронном/многопоточном
    рантайме проверка-и-вставка больше не атомарна сама по себе — гонку должен
    предотвращать уникальный индекс в БД, а не порядок вызовов в тесте.

    Файловая БД (не `:memory:`) намеренно: только она использует отдельное
    SQLite-соединение на поток (QueuePool), как в проде — см. tests/conftest.py.
    """
    store = Store(file_engine)
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]

    def attempt(n: int):
        try:
            store.create_booking(
                owner["id"],
                {
                    "eventTypeId": et["id"],
                    "startsAt": "2099-04-01T10:00:00.000Z",
                    "endsAt": "2099-04-01T10:30:00.000Z",
                    "guestName": f"Гость {n}",
                    "guestEmail": f"guest{n}@example.com",
                },
            )
            return "ok"
        except SlotUnavailableError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))

    assert results.count("ok") == 1
    assert results.count("conflict") == 7
    assert len(store.get_active_bookings(owner["id"])) == 1


def test_guest_booking_lifecycle_by_manage_token(store: Store):
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-05-01T10:00:00.000Z",
            "endsAt": "2099-05-01T10:30:00.000Z",
            "guestName": "Гость",
            "guestEmail": "guest@example.com",
            "comment": "по видео",
        },
    )
    token = booking["manageToken"]

    view = store.get_guest_booking(token)
    assert view["eventTypeName"] == et["name"]
    assert view["comment"] == "по видео"
    assert view["_manageToken"] == token

    assert store.get_guest_booking("unknown-token") is None

    rescheduled = store.reschedule_booking_by_token(
        token, starts_at="2099-05-01T12:00:00.000Z", ends_at="2099-05-01T12:30:00.000Z"
    )
    assert rescheduled["startsAt"] == "2099-05-01T12:00:00.000Z"

    cancelled = store.cancel_booking_by_token(token)
    assert cancelled["status"] == "cancelled"
    assert store.reschedule_booking_by_token(token, starts_at="2099-05-02T10:00:00.000Z", ends_at="2099-05-02T10:30:00.000Z") is None
    assert store.cancel_booking_by_token(token) is None


def test_reschedule_into_occupied_slot_raises_slot_unavailable(store: Store):
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    booking_a = store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-06-01T10:00:00.000Z",
            "endsAt": "2099-06-01T10:30:00.000Z",
            "guestName": "A",
            "guestEmail": "a@example.com",
        },
    )
    store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-06-01T11:00:00.000Z",
            "endsAt": "2099-06-01T11:30:00.000Z",
            "guestName": "B",
            "guestEmail": "b@example.com",
        },
    )
    with pytest.raises(SlotUnavailableError):
        store.reschedule_booking_by_token(
            booking_a["manageToken"], starts_at="2099-06-01T11:00:00.000Z", ends_at="2099-06-01T11:30:00.000Z"
        )


# --- уведомления -------------------------------------------------------------


def test_notification_settings_defaults_and_update(store: Store):
    owner = _make_owner(store)
    defaults = store.get_notification_settings(owner["id"])
    assert defaults == {"emailEnabled": True, "reminderHoursBefore": 24}

    updated = store.set_notification_settings(
        owner["id"], {"emailEnabled": False, "telegramChatId": "12345", "reminderHoursBefore": 2}
    )
    assert updated == {"emailEnabled": False, "telegramChatId": "12345", "reminderHoursBefore": 2}


def test_list_due_reminders(store: Store):
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-07-01T10:00:00.000Z",
            "endsAt": "2099-07-01T10:30:00.000Z",
            "guestName": "Гость",
            "guestEmail": "guest@example.com",
        },
    )
    due = store.list_due_reminders(now="2099-06-30T11:00:00.000Z")
    assert any(r["id"] == booking["id"] for r in due)

    store.mark_reminder_sent(booking["id"])
    due_after = store.list_due_reminders(now="2099-06-30T11:00:00.000Z")
    assert not any(r["id"] == booking["id"] for r in due_after)


# --- P2: организации, серии, платежи (минимальное покрытие) -----------------


def test_organizations_invite_and_join(store: Store):
    owner = _make_owner(store)
    other = _make_owner(store, email="other@example.com", slug="other")

    org = store.create_organization(owner["id"], "Моя команда")
    assert store.is_org_member(org["id"], owner["id"])

    invite = store.create_organization_invite(org["id"], "other@example.com")
    with pytest.raises(ValidationError):
        store.join_organization({"id": 999, "email": "wrong@example.com"}, invite["token"])

    joined = store.join_organization(other, invite["token"])
    assert joined["id"] == org["id"]
    assert store.is_org_member(org["id"], other["id"])

    with pytest.raises(NotFoundError):
        store.join_organization(other, "no-such-token")


def test_payment_lifecycle(store: Store):
    owner = _make_owner(store)
    et = store.list_event_types(owner["id"])[0]
    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": et["id"],
            "startsAt": "2099-08-01T10:00:00.000Z",
            "endsAt": "2099-08-01T10:30:00.000Z",
            "guestName": "Гость",
            "guestEmail": "guest@example.com",
            "paymentStatus": "pending",
        },
    )
    payment = store.create_payment_record(
        booking_id=booking["id"],
        amount_rub=500,
        status="pending",
        provider="stub",
        confirmation_url="https://example.com/pay/stub/1",
    )
    assert payment["status"] == "pending"

    paid = store.mark_payment_paid(payment["id"])
    assert paid["status"] == "paid"
    assert store.find_payment_by_booking(booking["id"])["status"] == "paid"
