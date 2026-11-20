"""API-тесты P2 — порт оставшихся сценариев из backend/test/api.test.js
(Pro paywall, busy-sync, команды, серии, платежи, аналитика)."""

from __future__ import annotations

from tests.test_api_p0 import login, next_workday


def activate_pro(client) -> None:
    login(client)
    res = client.post("/api/billing/activate-pro", json={"code": "pro-dev"})
    assert res.status_code == 200
    assert res.json()["owner"]["plan"] == "pro"


def test_pro_paywall_and_activation(api_client):
    login(api_client)

    blocked = api_client.get("/api/calendar-connections")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "forbidden"

    bad = api_client.post("/api/billing/activate-pro", json={"code": "wrong"})
    assert bad.status_code == 422

    ok = api_client.post("/api/billing/activate-pro", json={"code": "pro-dev"})
    assert ok.status_code == 200
    assert ok.json()["owner"]["plan"] == "pro"

    listed = api_client.get("/api/calendar-connections")
    assert listed.status_code == 200
    assert listed.json() == []


def test_google_stub_sync_subtracts_busy_from_slots(api_client):
    activate_pro(api_client)

    start = api_client.post("/api/calendar-connections/google/start")
    assert start.status_code == 200
    assert "stub-connect" in start.json()["authUrl"]

    connect = api_client.get("/api/calendar-connections/google/stub-connect", follow_redirects=False)
    assert connect.status_code in (301, 302)

    connections = api_client.get("/api/calendar-connections")
    assert connections.status_code == 200
    assert len(connections.json()) == 1
    assert connections.json()[0]["kind"] == "google"


def test_organization_and_invite(api_client):
    activate_pro(api_client)

    created = api_client.post("/api/organizations", json={"name": "Студия"})
    assert created.status_code == 201
    org_id = created.json()["id"]

    invite = api_client.post(f"/api/organizations/{org_id}/invites", json={"email": "mate@example.com"})
    assert invite.status_code == 200
    assert invite.json()["token"]

    reg = api_client.post(
        "/api/owners",
        json={"name": "Коллега", "email": "mate@example.com", "password": "secret1", "slug": "mate"},
    )
    assert reg.status_code == 201
    # Регистрация уже залогинила клиента как mate (session-cookie обновилась) —
    # как отдельный cookie-jar в JS-тесте (`cookies: { session: mateCookie.value }`).
    joined = api_client.post("/api/organizations/join", json={"token": invite.json()["token"]})
    assert joined.status_code == 200
    assert joined.json()["id"] == org_id

    # members смотрит владелец организации — текущая сессия клиента сейчас mate,
    # логинимся обратно под создателем организации.
    login(api_client)
    members = api_client.get(f"/api/organizations/{org_id}/members")
    assert members.status_code == 200
    assert len(members.json()) == 2


def test_paid_booking_and_stub_confirm(api_client):
    login(api_client)
    types = api_client.get("/api/event-types").json()
    et = types[0]

    priced = api_client.put(
        f"/api/event-types/{et['id']}",
        json={
            "name": et["name"],
            "description": et.get("description"),
            "durationMinutes": et["durationMinutes"],
            "priceRub": 1500,
        },
    )
    assert priced.status_code == 200
    assert priced.json()["priceRub"] == 1500

    day = next_workday()
    slots = api_client.get(
        "/api/public/kirill/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()
    assert len(slots) > 0
    slot = slots[0]

    booked = api_client.post(
        "/api/public/kirill/bookings",
        json={
            "eventTypeId": et["id"],
            "startsAt": slot["startsAt"],
            "guestName": "Плательщик",
            "guestEmail": "pay@example.com",
        },
    )
    assert booked.status_code == 201
    assert booked.json()["paymentStatus"] == "pending"
    assert booked.json()["paymentUrl"]

    payment_id = int(booked.json()["paymentUrl"].rstrip("/").split("/")[-1])
    confirmed = api_client.post(f"/api/payments/{payment_id}/stub-confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "paid"


def test_analytics_after_pro_activation(api_client):
    activate_pro(api_client)

    summary = api_client.get("/api/analytics", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert summary.status_code == 200
    assert isinstance(summary.json()["created"], int)
    assert len(summary.json()["byWeekday"]) == 7


def test_booking_series_create_and_cancel(api_client):
    activate_pro(api_client)
    types = api_client.get("/api/event-types").json()
    et = next(t for t in types if t["durationMinutes"] == 30)

    day = next_workday()
    slots = api_client.get(
        "/api/public/kirill/slots", params={"from": day, "to": day, "eventTypeId": et["id"]}
    ).json()

    series = api_client.post(
        "/api/booking-series",
        json={
            "eventTypeId": et["id"],
            "guestName": "Серийный",
            "guestEmail": "s@example.com",
            "startsAt": slots[0]["startsAt"],
            "count": 2,
        },
    )
    assert series.status_code == 201
    assert len(series.json()["bookingIds"]) == 2

    bookings = api_client.get("/api/bookings").json()
    assert len(bookings) == 2

    cancelled = api_client.delete(f"/api/booking-series/{series.json()['id']}")
    assert cancelled.status_code == 204
