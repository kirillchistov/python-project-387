"""API-тесты P0/P1 — порт сценариев из backend/test/api.test.js (node:test)
на pytest + FastAPI TestClient. Один сценарий JS-файла = один тест здесь,
с тем же значением проверок (коды ответов, количество слотов, поля тел)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = "Europe/Moscow"
SLUG = "kirill"


def _today_in_tz() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


def next_workday() -> str:
    day = _today_in_tz() + timedelta(days=1)
    while day.weekday() in (5, 6):  # Python: Пн=0 … Сб=5, Вс=6
        day += timedelta(days=1)
    return day.isoformat()


def login(client, email="owner@example.com", password="secret"):
    res = client.post("/api/session", json={"email": email, "password": password})
    assert res.status_code == 200
    return res


def test_healthcheck_without_auth(api_client):
    res = api_client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_guest_sees_public_profile_and_event_types(api_client):
    profile = api_client.get(f"/api/public/{SLUG}")
    assert profile.status_code == 200
    assert profile.json()["slug"] == SLUG
    assert profile.json()["timezone"] == TZ

    types = api_client.get(f"/api/public/{SLUG}/event-types")
    assert types.status_code == 200
    assert len(types.json()) >= 2
    assert any(t["durationMinutes"] == 60 for t in types.json())


def test_weekday_slots_30min_gives_16(api_client):
    day = next_workday()
    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    thirty = next(t for t in types if t["durationMinutes"] == 30)
    res = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": thirty["id"]}
    )
    assert res.status_code == 200
    slots = res.json()
    assert len(slots) == 16
    first_local = datetime.fromisoformat(slots[0]["startsAt"]).astimezone(ZoneInfo(TZ))
    assert first_local.strftime("%H:%M") == "10:00"


def test_60min_type_gives_fewer_slots_and_blocks_neighbor(api_client):
    day = next_workday()
    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    hour = next(t for t in types if t["durationMinutes"] == 60)
    slots_res = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": hour["id"]}
    )
    assert len(slots_res.json()) == 8

    slot = slots_res.json()[0]
    api_client.post(
        f"/api/public/{SLUG}/bookings",
        json={
            "eventTypeId": hour["id"],
            "startsAt": slot["startsAt"],
            "guestName": "Иван",
            "guestEmail": "ivan@example.com",
        },
    )

    after = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": hour["id"]}
    ).json()
    assert not any(s["startsAt"] == slot["startsAt"] for s in after)


def test_slots_invalid_period_422(api_client):
    res = api_client.get(
        f"/api/public/{SLUG}/slots",
        params={"from": "2026-08-10", "to": "2026-08-01", "eventTypeId": 1},
    )
    assert res.status_code == 422


def test_slots_beyond_horizon_empty(api_client):
    day = (_today_in_tz() + timedelta(days=20)).isoformat()
    res = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": 1}
    )
    assert res.status_code == 200
    assert res.json() == []


def test_booking_success_then_conflict_409(api_client):
    day = next_workday()
    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    et = types[0]
    slot = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()[0]

    payload = {
        "eventTypeId": et["id"],
        "startsAt": slot["startsAt"],
        "guestName": "Иван Петров",
        "guestEmail": "ivan@example.com",
    }
    created = api_client.post(f"/api/public/{SLUG}/bookings", json=payload)
    assert created.status_code == 201

    conflict = api_client.post(f"/api/public/{SLUG}/bookings", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "slot_unavailable"


def test_booking_in_the_past_409(api_client):
    res = api_client.post(
        f"/api/public/{SLUG}/bookings",
        json={
            "eventTypeId": 1,
            "startsAt": "2020-01-06T10:00:00Z",
            "guestName": "Иван",
            "guestEmail": "ivan@example.com",
        },
    )
    assert res.status_code == 409


def test_register_new_owner_gets_session_and_public_page(api_client):
    res = api_client.post(
        "/api/owners",
        json={"name": "Анна", "email": "anna@example.com", "password": "secret1", "slug": "anna"},
    )
    assert res.status_code == 201
    assert res.json()["owner"]["slug"] == "anna"
    assert "session=" in res.headers.get("set-cookie", "")

    public_page = api_client.get("/api/public/anna")
    assert public_page.status_code == 200
    assert public_page.json()["name"] == "Анна"


def test_register_duplicate_slug_409(api_client):
    res = api_client.post(
        "/api/owners",
        json={"name": "Другой", "email": "other@example.com", "password": "secret1", "slug": "kirill"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "already_exists"


def test_owner_event_type_crud(api_client):
    login(api_client)

    created = api_client.post(
        "/api/event-types", json={"name": "Созвон 45", "durationMinutes": 45, "description": "Длинный"}
    )
    assert created.status_code == 201
    assert created.json()["durationMinutes"] == 45

    event_type_id = created.json()["id"]
    updated = api_client.put(
        f"/api/event-types/{event_type_id}", json={"name": "Созвон 90", "durationMinutes": 90}
    )
    assert updated.status_code == 200
    assert updated.json()["durationMinutes"] == 90

    removed = api_client.delete(f"/api/event-types/{event_type_id}")
    assert removed.status_code == 204


def test_owner_endpoints_require_session_401(api_client):
    for method, url in [
        ("GET", "/api/bookings"),
        ("DELETE", "/api/bookings/1"),
        ("GET", "/api/availability"),
        ("GET", "/api/event-types"),
    ]:
        res = api_client.request(method, url)
        assert res.status_code == 401, f"{method} {url}"


def test_owner_login_list_bookings_cancel_frees_slot(api_client):
    day = next_workday()
    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    et = types[0]
    slot = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()[0]

    api_client.post(
        f"/api/public/{SLUG}/bookings",
        json={
            "eventTypeId": et["id"],
            "startsAt": slot["startsAt"],
            "guestName": "Иван",
            "guestEmail": "ivan@example.com",
        },
    )

    login(api_client)
    listed = api_client.get("/api/bookings")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["eventTypeName"] == et["name"]

    cancel = api_client.delete(f"/api/bookings/{listed.json()[0]['id']}")
    assert cancel.status_code == 204

    slots_after = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()
    assert any(s["startsAt"] == slot["startsAt"] for s in slots_after)


def test_malformed_json_is_400_not_500(api_client):
    res = api_client.post(
        f"/api/public/{SLUG}/bookings",
        content='{"oops": ',
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "bad_request"


def test_availability_read_update_overlap_422(api_client):
    login(api_client)

    current = api_client.get("/api/availability")
    assert current.status_code == 200
    assert current.json()["timezone"] == TZ
    assert current.json()["bufferMinutes"] == 0
    assert current.json()["exceptions"] == []

    overlapping = api_client.put(
        "/api/availability",
        json={
            "timezone": TZ,
            "bufferMinutes": 0,
            "exceptions": [],
            "rules": [
                {"weekday": 1, "startTime": "10:00", "endTime": "14:00"},
                {"weekday": 1, "startTime": "13:00", "endTime": "18:00"},
            ],
        },
    )
    assert overlapping.status_code == 422


def test_availability_break_buffer_and_holiday_affect_slots(api_client):
    login(api_client)
    day = next_workday()
    weekday = date.fromisoformat(day).isoweekday()

    api_client.put(
        "/api/availability",
        json={
            "timezone": TZ,
            "bufferMinutes": 30,
            "rules": [
                {"weekday": weekday, "startTime": "10:00", "endTime": "13:00"},
                {"weekday": weekday, "startTime": "14:00", "endTime": "18:00"},
            ],
            "exceptions": [{"date": day, "intervals": []}],
        },
    )

    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    et = next(t for t in types if t["durationMinutes"] == 30)
    holiday_slots = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    )
    assert holiday_slots.json() == []

    api_client.put(
        "/api/availability",
        json={
            "timezone": TZ,
            "bufferMinutes": 30,
            "rules": [
                {"weekday": weekday, "startTime": "10:00", "endTime": "13:00"},
                {"weekday": weekday, "startTime": "14:00", "endTime": "18:00"},
            ],
            "exceptions": [],
        },
    )

    slots = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()
    # 10–13 → 6 слотов, 14–18 → 8 слотов
    assert len(slots) == 14

    first = slots[0]
    api_client.post(
        f"/api/public/{SLUG}/bookings",
        json={
            "eventTypeId": et["id"],
            "startsAt": first["startsAt"],
            "guestName": "Иван",
            "guestEmail": "ivan@example.com",
        },
    )
    after = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()
    # Буфер 30 мин блокирует и соседний слот после встречи
    assert not any(s["startsAt"] == first["startsAt"] for s in after)
    assert not any(s["startsAt"] == slots[1]["startsAt"] for s in after)


def test_guest_cancel_and_reschedule_by_manage_token(api_client):
    day = next_workday()
    types = api_client.get(f"/api/public/{SLUG}/event-types").json()
    et = types[0]
    slots = api_client.get(
        f"/api/public/{SLUG}/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()

    created = api_client.post(
        f"/api/public/{SLUG}/bookings",
        json={
            "eventTypeId": et["id"],
            "startsAt": slots[0]["startsAt"],
            "guestName": "Иван",
            "guestEmail": "ivan@example.com",
        },
    )
    assert created.status_code == 201
    token = created.json()["manageToken"]
    assert token

    view = api_client.get(f"/api/guest/bookings/{token}")
    assert view.status_code == 200
    assert view.json()["guestEmail"] == "ivan@example.com"

    moved = api_client.patch(f"/api/guest/bookings/{token}", json={"startsAt": slots[2]["startsAt"]})
    assert moved.status_code == 200
    assert moved.json()["startsAt"] == slots[2]["startsAt"]

    cancelled = api_client.delete(f"/api/guest/bookings/{token}")
    assert cancelled.status_code == 204

    gone = api_client.get(f"/api/guest/bookings/{token}")
    assert gone.json()["status"] == "cancelled"


def test_notification_settings_read_and_save(api_client):
    login(api_client)
    current = api_client.get("/api/notification-settings")
    assert current.status_code == 200
    assert current.json()["emailEnabled"] is True

    updated = api_client.put(
        "/api/notification-settings",
        json={"emailEnabled": True, "telegramChatId": "12345", "reminderHoursBefore": 12},
    )
    assert updated.status_code == 200
    assert updated.json()["telegramChatId"] == "12345"
    assert updated.json()["reminderHoursBefore"] == 12
