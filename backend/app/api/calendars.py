"""Подключения календарей (busy-sync): ICS-фид и Google stub. Pro-функция.

Порт `app.js` §«P2: calendar connections».
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, status
from fastapi.responses import RedirectResponse

from app.api.deps import ProOwnerDep, StoreDep
from app.api.schemas.generated import CalendarConnection, GoogleAuthStart, IcsConnectionCreate
from app.domain.errors import NotFoundError, ValidationError
from app.domain.ics import fetch_ics_busy
from app.domain.timeutil import to_iso_z

router = APIRouter(tags=["calendars"])


def _public_base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "http://localhost:5173").rstrip("/")


def _is_valid_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _demo_google_busy_blocks() -> list[dict[str, str]]:
    """Демо-занятость: ближайший будний день 12:00–13:00 UTC на 7 дней вперёд."""
    blocks = []
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(1, 8):
        day = today + timedelta(days=i, hours=12)
        if day.weekday() in (5, 6):  # Пн=0…Вс=6; JS: day.day() 0=Вс, 6=Сб
            continue
        blocks.append({"startsAt": to_iso_z(day), "endsAt": to_iso_z(day + timedelta(hours=1))})
    return blocks


@router.get("/api/calendar-connections", response_model=list[CalendarConnection])
def list_calendar_connections(owner: ProOwnerDep, store: StoreDep) -> list[dict]:
    return store.list_calendar_connections(owner["id"])


@router.post(
    "/api/calendar-connections/ics",
    status_code=status.HTTP_201_CREATED,
    response_model=CalendarConnection,
)
async def connect_ics(body: IcsConnectionCreate, owner: ProOwnerDep, store: StoreDep) -> dict:
    if not _is_valid_http_url(body.url):
        raise ValidationError(
            "Некорректный URL ICS", errors=[{"field": "url", "message": "Ожидается http(s) URL"}]
        )
    connection = store.create_calendar_connection(
        owner["id"], kind="ics", label=body.label, config={"url": body.url}
    )
    try:
        busy = await fetch_ics_busy(body.url)
        store.replace_busy_blocks(owner["id"], connection["id"], busy)
    except Exception as exc:
        store.delete_calendar_connection(owner["id"], connection["id"])
        raise ValidationError(str(exc) or "Не удалось загрузить ICS") from exc
    return store.find_calendar_connection(owner["id"], connection["id"])


@router.post("/api/calendar-connections/google/start", response_model=GoogleAuthStart)
def start_google(owner: ProOwnerDep) -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        return {"authUrl": f"{_public_base_url()}/api/calendar-connections/google/stub-connect"}
    redirect_uri = os.environ.get(
        "GOOGLE_REDIRECT_URI", f"{_public_base_url()}/api/calendar-connections/google/callback"
    )
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/calendar.freebusy",
            "access_type": "offline",
            "prompt": "consent",
            "state": str(owner["id"]),
        }
    )
    return {"authUrl": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@router.get("/api/calendar-connections/google/stub-connect")
def google_stub_connect(owner: ProOwnerDep, store: StoreDep) -> RedirectResponse:
    existing = next(
        (c for c in store.list_calendar_connections(owner["id"]) if c["kind"] == "google"), None
    )
    if existing is None:
        connection = store.create_calendar_connection(
            owner["id"], kind="google", label="Google Calendar (stub)", config={"mode": "stub"}
        )
        store.replace_busy_blocks(owner["id"], connection["id"], _demo_google_busy_blocks())
    frontend = os.environ.get("FRONTEND_ORIGIN") or "http://localhost:5173"
    return RedirectResponse(url=f"{frontend}/admin/calendars?connected=1", status_code=302)


@router.post("/api/calendar-connections/{connection_id}/sync", response_model=CalendarConnection)
async def sync_calendar_connection(
    connection_id: int, owner: ProOwnerDep, store: StoreDep
) -> dict:
    row = store.get_calendar_connection_row(owner["id"], connection_id)
    if row is None:
        raise NotFoundError("Подключение не найдено")
    config = json.loads(row["config_json"] or "{}")

    if row["kind"] == "ics":
        try:
            busy = await fetch_ics_busy(config["url"])
        except Exception as exc:
            raise ValidationError(str(exc) or "Ошибка sync ICS") from exc
        return store.replace_busy_blocks(owner["id"], row["id"], busy)

    if config.get("mode") == "stub" or not os.environ.get("GOOGLE_CLIENT_ID"):
        return store.replace_busy_blocks(owner["id"], row["id"], _demo_google_busy_blocks())

    raise ValidationError("Google FreeBusy требует refresh token (полный OAuth callback)")


@router.delete("/api/calendar-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_connection(connection_id: int, owner: ProOwnerDep, store: StoreDep) -> None:
    ok = store.delete_calendar_connection(owner["id"], connection_id)
    if not ok:
        raise NotFoundError("Подключение не найдено")
