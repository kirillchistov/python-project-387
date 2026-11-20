"""Публичные эндпоинты платежей: статус, stub-подтверждение, вебхук YooKassa.

Порт `app.js` §«P2: payments». Без авторизации — как и в JS-версии
(платёж адресуется по числовому id из ссылки, отдельного секрета нет —
сознательное упрощение MVP, унаследованное от оригинала).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import StoreDep
from app.api.schemas.generated import PaymentInfo
from app.domain.errors import NotFoundError

router = APIRouter(tags=["payments"])


@router.get("/api/payments/{payment_id}", response_model=PaymentInfo)
def get_payment(payment_id: int, store: StoreDep) -> dict:
    payment = store.find_payment(payment_id)
    if payment is None:
        raise NotFoundError("Платёж не найден")
    return payment


@router.post("/api/payments/{payment_id}/stub-confirm", response_model=PaymentInfo)
def stub_confirm(payment_id: int, store: StoreDep) -> dict:
    payment = store.find_payment(payment_id)
    if payment is None:
        raise NotFoundError("Платёж не найден")
    if payment["status"] == "paid":
        return payment
    return store.mark_payment_paid(payment["id"])


@router.post("/api/payments/yookassa/webhook")
async def yookassa_webhook(request: Request, store: StoreDep) -> dict[str, Any]:
    event = await request.json()
    obj = (event or {}).get("object") or {}
    if obj.get("status") == "succeeded" and obj.get("id"):
        payment = store.find_payment_by_provider_id(obj["id"])
        if payment:
            store.mark_payment_paid(payment["id"])
        else:
            payment_id = (obj.get("metadata") or {}).get("paymentId")
            if payment_id:
                store.mark_payment_paid(int(payment_id))
    return {}
