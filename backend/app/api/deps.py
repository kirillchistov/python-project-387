"""Зависимости роутов: доступ к Store и авторизация владельца.

Порт `requireOwner`/`requirePro` (preHandler-хуков) из `backend/src/app.js`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from app.domain.errors import ForbiddenError, UnauthorizedError
from app.infra.store import Store

SESSION_COOKIE = "session"


def get_store(request: Request) -> Store:
    return request.app.state.store


StoreDep = Annotated[Store, Depends(get_store)]


def require_owner(request: Request, store: StoreDep) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    owner = store.get_session_owner(token)
    if owner is None:
        raise UnauthorizedError("Требуется вход владельца")
    return owner


OwnerDep = Annotated[dict[str, Any], Depends(require_owner)]


def require_pro(owner: OwnerDep) -> dict[str, Any]:
    if owner.get("plan") != "pro":
        raise ForbiddenError(
            "Функция доступна на тарифе Pro. Активируйте Pro в разделе Биллинг."
        )
    return owner


ProOwnerDep = Annotated[dict[str, Any], Depends(require_pro)]
