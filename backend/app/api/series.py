"""Серии повторяющихся встреч (еженедельно). Pro-функция.

Порт `app.js` §«P2: booking series».
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, status

from app.api.deps import ProOwnerDep, StoreDep
from app.api.schemas.generated import BookingSeries, BookingSeriesCreate
from app.api.shared import slot_busy_args
from app.domain.errors import NotFoundError, SlotUnavailableError, ValidationError
from app.domain.slots import is_free_slot
from app.domain.timeutil import to_iso_z

router = APIRouter(tags=["booking-series"])


@router.get("/api/booking-series", response_model=list[BookingSeries])
def list_series(owner: ProOwnerDep, store: StoreDep) -> list[dict]:
    return store.list_booking_series(owner["id"])


@router.post(
    "/api/booking-series", status_code=status.HTTP_201_CREATED, response_model=BookingSeries
)
def create_series(body: BookingSeriesCreate, owner: ProOwnerDep, store: StoreDep) -> dict:
    event_type = store.find_event_type(owner["id"], body.eventTypeId)
    if event_type is None:
        raise ValidationError(
            "Неизвестный тип события",
            errors=[{"field": "eventTypeId", "message": "Тип события не найден"}],
        )

    duration = timedelta(minutes=event_type["durationMinutes"])
    starts = [body.startsAt + timedelta(weeks=i) for i in range(body.count)]

    busy_args = slot_busy_args(store, owner["id"])
    for start in starts:
        free = is_free_slot(
            availability=busy_args["availability"],
            active_bookings=busy_args["active_bookings"],
            external_busy=busy_args["external_busy"],
            starts_at=to_iso_z(start),
            duration_minutes=event_type["durationMinutes"],
        )
        if not free:
            raise SlotUnavailableError(f"Слот {to_iso_z(start)} недоступен для серии")

    for i in range(len(starts)):
        a0, a1 = starts[i], starts[i] + duration
        for j in range(i + 1, len(starts)):
            b0, b1 = starts[j], starts[j] + duration
            if a0 < b1 and b0 < a1:
                raise SlotUnavailableError("Встречи серии пересекаются")

    series_id = store.create_booking_series_record(
        owner["id"],
        {
            "eventTypeId": body.eventTypeId,
            "guestName": body.guestName,
            "guestEmail": body.guestEmail,
            "comment": body.comment,
            "startsAt": to_iso_z(body.startsAt),
            "count": body.count,
        },
    )

    for start in starts:
        store.create_booking(
            owner["id"],
            {
                "eventTypeId": body.eventTypeId,
                "startsAt": to_iso_z(start),
                "endsAt": to_iso_z(start + duration),
                "guestName": body.guestName,
                "guestEmail": body.guestEmail,
                "comment": body.comment,
                "seriesId": series_id,
                "paymentStatus": "none",
            },
        )

    return store.find_booking_series(owner["id"], series_id)


@router.delete("/api/booking-series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_series(series_id: int, owner: ProOwnerDep, store: StoreDep) -> None:
    ok = store.cancel_booking_series(owner["id"], series_id)
    if not ok:
        raise NotFoundError("Серия не найдена")
