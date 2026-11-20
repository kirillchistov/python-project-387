"""Публичные эндпоинты гостя: профиль владельца, типы событий, слоты, бронь.

Порт `backend/src/app.js` §«Публичные эндпоинты гостя».
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import StoreDep
from app.api.schemas.generated import BookingCreate, BookingCreated, EventType, OwnerPublic, Slot
from app.api.shared import slot_busy_args
from app.domain.errors import NotFoundError, SlotUnavailableError, ValidationError
from app.domain.slots import compute_free_slots, is_free_slot
from app.domain.timeutil import to_iso_z
from app.infra.notifications import notify_for_owner_booking
from app.infra.payments import create_payment_confirmation

router = APIRouter(tags=["public"])


def _public_base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "http://localhost:5173").rstrip("/")


@router.get("/api/public/{slug}", response_model=OwnerPublic)
def get_owner(slug: str, store: StoreDep) -> dict:
    profile = store.get_owner_public(slug)
    if profile is None:
        raise NotFoundError("Владелец не найден")
    return profile


@router.get("/api/public/{slug}/event-types", response_model=list[EventType])
def list_event_types(slug: str, store: StoreDep) -> list[dict]:
    owner = store.find_owner_by_slug(slug)
    if owner is None:
        raise NotFoundError("Владелец не найден")
    return store.list_event_types(owner["id"])


@router.get("/api/public/{slug}/slots", response_model=list[Slot])
def list_slots(
    slug: str,
    store: StoreDep,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    event_type_id: Annotated[int, Query(alias="eventTypeId")],
) -> list[dict]:
    owner = store.find_owner_by_slug(slug)
    if owner is None:
        raise NotFoundError("Владелец не найден")
    if to < from_:
        raise ValidationError("Начало периода (from) не может быть позже конца (to)")
    event_type = store.find_event_type(owner["id"], event_type_id)
    if event_type is None:
        raise ValidationError(
            "Неизвестный тип события",
            errors=[{"field": "eventTypeId", "message": "Тип события не найден"}],
        )
    busy_args = slot_busy_args(store, owner["id"])
    return compute_free_slots(
        availability=busy_args["availability"],
        active_bookings=busy_args["active_bookings"],
        external_busy=busy_args["external_busy"],
        from_=from_.isoformat(),
        to=to.isoformat(),
        duration_minutes=event_type["durationMinutes"],
    )


@router.post(
    "/api/public/{slug}/bookings", status_code=status.HTTP_201_CREATED, response_model=BookingCreated
)
async def create_booking(slug: str, body: BookingCreate, store: StoreDep) -> dict:
    owner = store.find_owner_by_slug(slug)
    if owner is None:
        raise NotFoundError("Владелец не найден")

    event_type = store.find_event_type(owner["id"], body.eventTypeId)
    if event_type is None:
        raise ValidationError(
            "Неизвестный тип события",
            errors=[{"field": "eventTypeId", "message": "Тип события не найден"}],
        )

    busy_args = slot_busy_args(store, owner["id"])
    starts_at_iso = to_iso_z(body.startsAt)
    free = is_free_slot(
        availability=busy_args["availability"],
        active_bookings=busy_args["active_bookings"],
        external_busy=busy_args["external_busy"],
        starts_at=starts_at_iso,
        duration_minutes=event_type["durationMinutes"],
    )
    if not free:
        raise SlotUnavailableError("Слот уже занят, находится в прошлом или вне расписания")

    price_rub = event_type.get("priceRub") or 0
    payment_status = "pending" if price_rub > 0 else "none"
    ends_at = body.startsAt + timedelta(minutes=event_type["durationMinutes"])
    booking = store.create_booking(
        owner["id"],
        {
            "eventTypeId": body.eventTypeId,
            "startsAt": starts_at_iso,
            "endsAt": to_iso_z(ends_at),
            "guestName": body.guestName,
            "guestEmail": body.guestEmail,
            "comment": body.comment,
            "paymentStatus": payment_status,
        },
    )

    payment_url = None
    if price_rub > 0:
        draft = store.create_payment_record(
            booking_id=booking["id"],
            amount_rub=price_rub,
            status="pending",
            provider="pending",
            confirmation_url=f"{_public_base_url()}/pay/pending",
        )
        confirmation = await create_payment_confirmation(
            payment_id=draft["id"],
            amount_rub=price_rub,
            description=f"{event_type['name']} — {owner['name']}",
        )
        payment = store.update_payment_details(
            draft["id"],
            provider=confirmation["provider"],
            provider_payment_id=confirmation["providerPaymentId"],
            confirmation_url=confirmation["confirmationUrl"],
            status="pending",
        )
        payment_url = payment["confirmationUrl"]

    await notify_for_owner_booking(store, owner, booking, "created")

    if payment_url:
        return {**booking, "paymentUrl": payment_url}
    return booking
