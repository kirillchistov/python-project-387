"""Доступность владельца. Порт `app.js` §«Доступность»."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import OwnerDep, StoreDep
from app.api.schemas.generated import Availability
from app.domain.errors import ValidationError
from app.domain.slots import validate_availability

router = APIRouter(tags=["availability"])


@router.get("/api/availability", response_model=Availability)
def get_availability(owner: OwnerDep, store: StoreDep) -> dict:
    return store.get_availability(owner["id"])


@router.put("/api/availability", response_model=Availability)
def update_availability(body: Availability, owner: OwnerDep, store: StoreDep) -> dict:
    payload = body.model_dump(mode="json")
    errors = validate_availability(payload)
    if errors:
        raise ValidationError("Некорректные правила доступности", errors=errors)
    return store.set_availability(owner["id"], payload)
