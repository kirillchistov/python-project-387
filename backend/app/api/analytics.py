"""Аналитика владельца. Pro-функция. Порт `app.js` §«P2: analytics»."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ProOwnerDep, StoreDep
from app.api.schemas.generated import AnalyticsSummary
from app.domain.errors import ValidationError

router = APIRouter(tags=["analytics"])


@router.get("/api/analytics", response_model=AnalyticsSummary)
def get_analytics(
    owner: ProOwnerDep,
    store: StoreDep,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
) -> dict:
    if to < from_:
        raise ValidationError("from не может быть позже to")
    return store.get_analytics_summary(owner["id"], from_.isoformat(), to.isoformat())
