"""Брони владельца. Порт `app.js` §«Бронирования владельца»."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import OwnerDep, StoreDep
from app.api.schemas.generated import Booking
from app.domain.errors import NotFoundError
from app.domain.timeutil import now_utc, parse_iso
from app.infra.notifications import notify_for_owner_booking

router = APIRouter(tags=["bookings"])


@router.get("/api/bookings", response_model=list[Booking])
def list_bookings(owner: OwnerDep, store: StoreDep) -> list[dict]:
    now = now_utc()
    upcoming = [
        b for b in store.get_active_bookings(owner["id"]) if parse_iso(b["startsAt"]) > now
    ]
    upcoming.sort(key=lambda b: b["startsAt"])
    return upcoming


@router.delete("/api/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(booking_id: int, owner: OwnerDep, store: StoreDep) -> None:
    cancelled = store.cancel_booking(owner["id"], booking_id)
    if cancelled is None:
        raise NotFoundError("Встреча не найдена")
    await notify_for_owner_booking(store, owner, cancelled, "cancelled")
