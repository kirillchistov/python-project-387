"""Регистрация и сессия владельца. Порт `app.js` §«Регистрация»/«Сессия»."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import SESSION_COOKIE, StoreDep
from app.api.schemas.generated import OwnerCreate, Session, SessionCreate
from app.domain.errors import UnauthorizedError

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
    )


@router.post("/api/owners", status_code=status.HTTP_201_CREATED, response_model=Session)
def register(body: OwnerCreate, response: Response, store: StoreDep) -> dict:
    owner = store.create_owner(
        name=body.name, email=body.email, password=body.password, slug=body.slug
    )
    token = store.create_session(owner["id"])
    _set_session_cookie(response, token)
    return {"owner": owner}


@router.post("/api/session", response_model=Session)
def login(body: SessionCreate, response: Response, store: StoreDep) -> dict:
    owner = store.check_credentials(body.email, body.password)
    if owner is None:
        raise UnauthorizedError("Неверный email или пароль")
    token = store.create_session(owner["id"])
    _set_session_cookie(response, token)
    return {"owner": owner}


@router.get("/api/session", response_model=Session)
def current(request: Request, store: StoreDep) -> dict:
    owner = store.get_session_owner(request.cookies.get(SESSION_COOKIE))
    if owner is None:
        raise UnauthorizedError("Требуется вход владельца")
    return {"owner": owner}


@router.delete("/api/session", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, store: StoreDep) -> None:
    store.destroy_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
