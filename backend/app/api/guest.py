"""Гость управляет своей бронью по секретному manage_token.

Порт `backend/src/app.js` §«Гость: управление по секретному токену».
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import StoreDep
from app.api.schemas.generated import BookingReschedule, GuestBooking
from app.api.shared import slot_busy_args
from app.domain.errors import NotFoundError, SlotUnavailableError
from app.domain.slots import is_free_slot
from app.domain.timeutil import to_iso_z
from app.infra.notifications import notify_for_owner_booking

router = APIRouter(tags=["guest"])


def _public_guest_booking(view: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in view.items() if not k.startswith("_")}


@router.get("/api/guest/bookings/{token}", response_model=GuestBooking)
def get_guest_booking(token: str, store: StoreDep) -> dict:
    view = store.get_guest_booking(token)
    if view is None:
        raise NotFoundError("Встреча не найдена")
    return _public_guest_booking(view)


@router.delete("/api/guest/bookings/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_guest_booking(token: str, store: StoreDep) -> None:
    before = store.get_guest_booking(token)
    if before is None or before["status"] != "active":
        raise NotFoundError("Встреча не найдена")
    cancelled = store.cancel_booking_by_token(token)
    owner = store.find_owner_by_id(before["_ownerId"])
    if owner is not None and cancelled is not None:
        await notify_for_owner_booking(store, owner, cancelled, "cancelled")


@router.patch("/api/guest/bookings/{token}", response_model=GuestBooking)
async def reschedule_guest_booking(
    token: str, body: BookingReschedule, store: StoreDep
) -> dict:
    current = store.get_guest_booking(token)
    if current is None or current["status"] != "active":
        raise NotFoundError("Встреча не найдена")
    owner = store.find_owner_by_id(current["_ownerId"])
    event_type = store.find_event_type(current["_ownerId"], current["_eventTypeId"])
    if owner is None or event_type is None:
        raise NotFoundError("Встреча не найдена")

    busy_args = slot_busy_args(store, owner["id"])
    starts_at_iso = to_iso_z(body.startsAt)
    free = is_free_slot(
        availability=busy_args["availability"],
        active_bookings=store.get_active_bookings_except(owner["id"], current["id"]),
        external_busy=busy_args["external_busy"],
        starts_at=starts_at_iso,
        duration_minutes=event_type["durationMinutes"],
    )
    if not free:
        raise SlotUnavailableError("Слот уже занят, находится в прошлом или вне расписания")

    ends_at = body.startsAt + timedelta(minutes=event_type["durationMinutes"])
    updated = store.reschedule_booking_by_token(
        token, starts_at=starts_at_iso, ends_at=to_iso_z(ends_at)
    )
    await notify_for_owner_booking(
        store,
        owner,
        {
            "startsAt": updated["startsAt"],
            "endsAt": updated["endsAt"],
            "guestName": updated["guestName"],
            "guestEmail": updated["guestEmail"],
            "comment": updated.get("comment"),
            "manageToken": updated["_manageToken"],
            "eventTypeId": current["_eventTypeId"],
        },
        "rescheduled",
    )
    return _public_guest_booking(updated)
