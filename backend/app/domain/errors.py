"""Доменные исключения с HTTP-семантикой.

В JS-версии `store.js`/`ics.js` бросают обычные `Error` с полем `err.code`
(`'validation_error'`, `'not_found'`, `'already_exists'`, …), а каждый роут
в `app.js` вручную ловит их и подбирает статус-код (`grep '.code ==='`
в `app.js` — три места, не общий middleware). В Python-порту это обобщено
в один набор исключений + один обработчик в `app/main.py`
(см. port-to-python-plan.md §4.5) — набор кодов/статусов и тексты ошибок
идентичны, различается только механизм диспетчеризации.
"""

from __future__ import annotations


class DomainError(Exception):
    """Базовая доменная ошибка: статус, машинный код, сообщение, поля."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(DomainError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class SlotUnavailableError(DomainError):
    status_code = 409
    code = "slot_unavailable"


class AlreadyExistsError(DomainError):
    status_code = 409
    code = "already_exists"
