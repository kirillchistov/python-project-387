"""Настройки уведомлений владельца. Порт `app.js` §«Уведомления».

`reminderHoursBefore` (1–168) валидируется схемой контракта — Pydantic-модель
`NotificationSettings` уже несёт `ge=1, le=168` (см. docs/api/openapi.yaml),
поэтому отдельная ручная проверка, как в app.js, здесь не нужна: FastAPI
отклонит запрос до вызова хендлера.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import OwnerDep, StoreDep
from app.api.schemas.generated import NotificationSettings

router = APIRouter(tags=["notification-settings"])


@router.get("/api/notification-settings", response_model=NotificationSettings)
def get_notification_settings(owner: OwnerDep, store: StoreDep) -> dict:
    return store.get_notification_settings(owner["id"])


@router.put("/api/notification-settings", response_model=NotificationSettings)
def update_notification_settings(
    body: NotificationSettings, owner: OwnerDep, store: StoreDep
) -> dict:
    return store.set_notification_settings(owner["id"], body.model_dump(mode="json"))
