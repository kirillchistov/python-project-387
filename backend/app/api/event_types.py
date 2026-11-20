"""Типы событий владельца. Порт `app.js` §«Типы событий владельца»."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import OwnerDep, StoreDep
from app.api.schemas.generated import EventType, EventTypeWrite
from app.domain.errors import NotFoundError, ValidationError
from app.domain.slots import validate_duration_minutes

router = APIRouter(tags=["event-types"])


def _check_duration(duration_minutes: int) -> None:
    error = validate_duration_minutes(duration_minutes)
    if error:
        raise ValidationError(error, errors=[{"field": "durationMinutes", "message": error}])


@router.get("/api/event-types", response_model=list[EventType])
def list_event_types(owner: OwnerDep, store: StoreDep) -> list[dict]:
    return store.list_event_types(owner["id"])


@router.post("/api/event-types", status_code=status.HTTP_201_CREATED, response_model=EventType)
def create_event_type(body: EventTypeWrite, owner: OwnerDep, store: StoreDep) -> dict:
    _check_duration(body.durationMinutes)
    return store.create_event_type(
        owner["id"],
        name=body.name,
        description=body.description,
        duration_minutes=body.durationMinutes,
        price_rub=body.priceRub,
    )


@router.put("/api/event-types/{event_type_id}", response_model=EventType)
def update_event_type(
    event_type_id: int, body: EventTypeWrite, owner: OwnerDep, store: StoreDep
) -> dict:
    _check_duration(body.durationMinutes)
    event_type = store.update_event_type(
        owner["id"],
        event_type_id,
        name=body.name,
        description=body.description,
        duration_minutes=body.durationMinutes,
        price_rub=body.priceRub,
    )
    if event_type is None:
        raise NotFoundError("Тип события не найден")
    return event_type


@router.delete("/api/event-types/{event_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event_type(event_type_id: int, owner: OwnerDep, store: StoreDep) -> None:
    ok = store.delete_event_type(owner["id"], event_type_id)
    if not ok:
        raise NotFoundError("Тип события не найден")
