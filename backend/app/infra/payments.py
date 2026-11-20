"""Одноразовые платежи за встречу: YooKassa или stub без ключей.

Порт `backend/src/payments.js`.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from app.domain.errors import ValidationError


def _public_base() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "http://localhost:5173").rstrip("/")


def _yookassa_configured() -> bool:
    return bool(os.environ.get("YOOKASSA_SHOP_ID") and os.environ.get("YOOKASSA_SECRET_KEY"))


def is_yookassa_configured() -> bool:
    return _yookassa_configured()


async def create_payment_confirmation(
    *, payment_id: int, amount_rub: int, description: str, return_url: str | None = None
) -> dict[str, Any]:
    if not _yookassa_configured():
        return {
            "provider": "stub",
            "providerPaymentId": f"stub-{payment_id}",
            "confirmationUrl": f"{_public_base()}/pay/stub/{payment_id}",
        }

    shop_id = os.environ["YOOKASSA_SHOP_ID"]
    secret = os.environ["YOOKASSA_SECRET_KEY"]
    auth = base64.b64encode(f"{shop_id}:{secret}".encode()).decode()
    body = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url or f"{_public_base()}/pay/return",
        },
        "description": description[:128],
        "metadata": {"paymentId": str(payment_id)},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.yookassa.ru/v3/payments",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "Idempotence-Key": f"cc-pay-{payment_id}",
            },
            json=body,
        )
    if response.is_error:
        raise ValidationError(f"YooKassa: {response.status_code} {response.text}")

    data = response.json()
    confirmation_url = (data.get("confirmation") or {}).get("confirmation_url") or (
        f"{_public_base()}/pay/return"
    )
    return {
        "provider": "yookassa",
        "providerPaymentId": data["id"],
        "confirmationUrl": confirmation_url,
    }


def is_valid_pro_code(code: Any) -> bool:
    expected = os.environ.get("BILLING_PRO_CODE") or "pro-dev"
    return isinstance(code, str) and code == expected
