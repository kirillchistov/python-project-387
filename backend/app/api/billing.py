"""Биллинг: активация Pro кодом (заглушка подписки). Порт `app.js` §«P2: биллинг»."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import OwnerDep, StoreDep
from app.api.schemas.generated import ActivatePro, Session
from app.domain.errors import ValidationError
from app.infra.payments import is_valid_pro_code

router = APIRouter(tags=["billing"])


@router.post("/api/billing/activate-pro", response_model=Session)
def activate_pro(body: ActivatePro, owner: OwnerDep, store: StoreDep) -> dict:
    if not is_valid_pro_code(body.code):
        raise ValidationError(
            "Неверный код активации Pro", errors=[{"field": "code", "message": "Неверный код"}]
        )
    updated = store.set_owner_plan(owner["id"], "pro")
    return {"owner": updated}
