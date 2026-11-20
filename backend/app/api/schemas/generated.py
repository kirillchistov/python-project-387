# СГЕНЕРИРОВАНО из docs/api/openapi.yaml командой scripts/generate_schemas.sh — не редактировать руками.

from __future__ import annotations

from datetime import date as date_aliased
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, EmailStr, Field


class ActivatePro(BaseModel):
    """
    Ручная активация Pro (заглушка подписки)
    """

    code: str = Field(
        ...,
        description='Код активации. Совпадает с BILLING_PRO_CODE или "pro-dev"\nв development без переменной.',
        min_length=1,
    )


class Code(StrEnum):
    already_exists = 'already_exists'


class AlreadyExistsError(BaseModel):
    """
    409 — email или slug уже заняты при регистрации
    """

    code: Code
    message: str


class AnalyticsSummary(BaseModel):
    from_: date_aliased = Field(..., alias='from')
    to: date_aliased
    created: int
    cancelled: int
    upcoming: int = Field(..., description='Активные будущие на момент запроса')
    byWeekday: list[int] = Field(..., description='Число броней по ISO-дню недели 1..7')


class AvailabilityRule(BaseModel):
    """
    Правило доступности: повторяющийся недельный интервал,
    в котором владелец готов принимать звонки (например, Пн 10:00–18:00).
    Перерыв внутри дня = два непересекающихся правила в один weekday.
    """

    weekday: int = Field(
        ...,
        description='День недели по ISO 8601: 1 — понедельник … 7 — воскресенье',
        ge=1,
        le=7,
    )
    startTime: str = Field(
        ...,
        description='Начало интервала, локальное время владельца в формате HH:MM',
        pattern='^([01][0-9]|2[0-3]):[0-5][0-9]$',
    )
    endTime: str = Field(
        ...,
        description='Конец интервала, локальное время владельца в формате HH:MM',
        pattern='^([01][0-9]|2[0-3]):[0-5][0-9]$',
    )


class BookingCreate(BaseModel):
    """
    Данные для создания бронирования гостем
    """

    eventTypeId: int
    startsAt: AwareDatetime = Field(
        ...,
        description='Начало выбранного слота, UTC. Должно совпадать со слотом из GET …/slots.',
    )
    guestName: str = Field(..., min_length=1)
    guestEmail: EmailStr
    comment: str | None = None


class BookingReschedule(BaseModel):
    """
    Перенос встречи гостем на другой свободный слот того же типа
    """

    startsAt: AwareDatetime


class BookingSeries(BaseModel):
    """
    Серия повторяющихся встреч (тьютор ↔ ученик), еженедельно
    """

    id: int
    eventTypeId: int
    guestName: str
    guestEmail: EmailStr
    comment: str | None = None
    startsAt: AwareDatetime = Field(..., description='Первый старт серии, UTC')
    count: int = Field(..., description='Число встреч в серии (1–52)', ge=1, le=52)
    bookingIds: list[int] = Field(..., description='Созданные брони (id)')


class BookingSeriesCreate(BaseModel):
    eventTypeId: int
    guestName: str = Field(..., min_length=1)
    guestEmail: EmailStr
    comment: str | None = None
    startsAt: AwareDatetime
    count: int = Field(..., ge=1, le=52)


class BookingStatus(StrEnum):
    active = 'active'
    cancelled = 'cancelled'


class CalendarConnectionKind(StrEnum):
    google = 'google'
    ics = 'ics'


class Code1(StrEnum):
    slot_unavailable = 'slot_unavailable'


class ConflictError(BaseModel):
    """
    409 — конфликт: слот уже занят или находится в прошлом
    """

    code: Code1
    message: str


class DayInterval(BaseModel):
    """
    Интервал времени в пределах одного календарного дня (локальное время владельца)
    """

    startTime: str = Field(..., pattern='^([01][0-9]|2[0-3]):[0-5][0-9]$')
    endTime: str = Field(..., pattern='^([01][0-9]|2[0-3]):[0-5][0-9]$')


class EventType(BaseModel):
    """
    Тип события — то, на что гость записывается (например, «Вводный звонок»)
    """

    id: int
    name: str
    description: str | None = None
    durationMinutes: int = Field(
        ...,
        description='Длительность встречи в минутах: 15–240, кратно 15.\nОт неё зависят длина слота и шаг сетки при вычислении свободного времени.',
        ge=15,
        le=240,
    )
    priceRub: int = Field(..., description='Цена в рублях; 0 — бесплатно', ge=0)


class EventTypeWrite(BaseModel):
    """
    Создание / обновление типа события владельцем
    """

    name: str = Field(..., min_length=1)
    description: str | None = None
    durationMinutes: int = Field(..., ge=15, le=240)
    priceRub: int | None = Field(None, ge=0)


class FieldError(BaseModel):
    """
    Ошибка одного поля при валидации
    """

    field: str
    message: str


class Code2(StrEnum):
    forbidden = 'forbidden'


class ForbiddenError(BaseModel):
    """
    403 — нужна подписка Pro
    """

    code: Code2
    message: str


class GoogleAuthStart(BaseModel):
    authUrl: str = Field(
        ..., description='URL для OAuth-редиректа пользователя в Google'
    )


class IcsConnectionCreate(BaseModel):
    url: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)


class Code3(StrEnum):
    not_found = 'not_found'


class NotFoundError(BaseModel):
    """
    404 — ресурс не найден
    """

    code: Code3
    message: str


class NotificationSettings(BaseModel):
    """
    Настройки уведомлений владельца
    """

    emailEnabled: bool = Field(
        ...,
        description='Письма о новых / отменённых / перенесённых встречах и напоминания',
    )
    telegramChatId: str | None = Field(
        None,
        description='Chat id Telegram для уведомлений владельцу.\nПустая строка / отсутствие — Telegram выключен.',
    )
    reminderHoursBefore: int = Field(
        ...,
        description='За сколько часов до встречи слать напоминание гостю и владельцу (1–168)',
        ge=1,
        le=168,
    )


class OrgRole(StrEnum):
    owner = 'owner'
    member = 'member'


class Organization(BaseModel):
    id: int
    name: str
    ownerId: int = Field(..., description='Владелец-создатель организации')


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1)


class OrganizationInvite(BaseModel):
    token: str
    joinPath: str = Field(
        ..., description='Ссылка для принявшего приглашение (фронт /team/join?token=)'
    )


class OrganizationInviteCreate(BaseModel):
    email: EmailStr


class OrganizationJoin(BaseModel):
    token: str = Field(..., min_length=1)


class OrganizationMember(BaseModel):
    ownerId: int
    name: str
    email: str
    slug: str
    role: OrgRole


class OwnerCreate(BaseModel):
    """
    Данные регистрации нового владельца
    """

    name: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=6)
    slug: str = Field(..., pattern='^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$')


class OwnerPublic(BaseModel):
    """
    Публичный профиль владельца для гостевой страницы бронирования
    """

    id: int
    name: str
    slug: str
    timezone: str = Field(
        ..., description='IANA-таймзона владельца (в ней заданы правила доступности)'
    )


class PaymentStatus(StrEnum):
    none = 'none'
    pending = 'pending'
    paid = 'paid'
    failed = 'failed'


class Plan(StrEnum):
    free = 'free'
    pro = 'pro'


class SessionCreate(BaseModel):
    """
    Учётные данные владельца для входа
    """

    email: EmailStr
    password: str = Field(..., min_length=1)


class Slot(BaseModel):
    """
    Свободный слот. Вычисляется на лету из правил доступности и длительности
    выбранного типа события за вычетом активных бронирований — в базе не хранится.
    """

    startsAt: AwareDatetime = Field(..., description='Начало слота, UTC')
    endsAt: AwareDatetime = Field(
        ..., description='Конец слота, UTC (startsAt + durationMinutes типа события)'
    )


class Code4(StrEnum):
    unauthorized = 'unauthorized'


class UnauthorizedError(BaseModel):
    """
    401 — нет активной сессии владельца или неверные учётные данные
    """

    code: Code4
    message: str


class Code5(StrEnum):
    validation_error = 'validation_error'


class ValidationError(BaseModel):
    """
    422 — ошибка валидации входных данных
    """

    code: Code5
    message: str
    errors: list[FieldError] | None = None


class AvailabilityException(BaseModel):
    """
    Исключение из недельного расписания на конкретную дату
    (праздник, отпуск, особый день приёма).
    Пустой `intervals` — день полностью недоступен.
    """

    date: date_aliased = Field(..., description='Дата YYYY-MM-DD в календаре владельца')
    intervals: list[DayInterval] = Field(
        ..., description='Рабочие интервалы в этот день; [] = выходной'
    )


class Booking(BaseModel):
    """
    Бронирование для владельца (без секретного токена гостя)
    """

    id: int
    eventTypeId: int
    eventTypeName: str = Field(
        ...,
        description='Название типа события на момент ответа (для списков владельца)',
    )
    startsAt: AwareDatetime
    endsAt: AwareDatetime
    guestName: str
    guestEmail: EmailStr
    comment: str | None = Field(
        None, description='Комментарий гостя владельцу (тема звонка и т. п.)'
    )
    status: BookingStatus
    paymentStatus: PaymentStatus
    createdAt: AwareDatetime


class BookingCreated(BaseModel):
    """
    Ответ при создании брони: обычные поля + секретный токен
    для отмены/переноса гостем (ссылка /b/{manageToken}).
    """

    id: int
    eventTypeId: int
    startsAt: AwareDatetime
    endsAt: AwareDatetime
    guestName: str
    guestEmail: EmailStr
    comment: str | None = None
    status: BookingStatus
    paymentStatus: PaymentStatus
    createdAt: AwareDatetime
    manageToken: str = Field(
        ..., description='Секретный токен управления встречей гостем'
    )
    paymentUrl: str | None = Field(
        None, description='URL оплаты, если тип события платный и статус pending'
    )


class CalendarConnection(BaseModel):
    """
    Подключённый источник занятости (busy)
    """

    id: int
    kind: CalendarConnectionKind
    label: str = Field(
        ..., description='Для ICS — URL; для Google — email календаря или "primary"'
    )
    lastSyncedAt: AwareDatetime | None = None


class GuestBooking(BaseModel):
    """
    Карточка встречи для гостя по секретному токену
    """

    id: int
    eventTypeName: str
    durationMinutes: int
    ownerName: str
    ownerSlug: str
    ownerTimezone: str
    startsAt: AwareDatetime
    endsAt: AwareDatetime
    guestName: str
    guestEmail: EmailStr
    comment: str | None = None
    status: BookingStatus
    paymentStatus: PaymentStatus


class Owner(BaseModel):
    """
    Владелец календаря. Создаётся через регистрацию; публичная страница —
    /u/{slug} на фронтенде и /api/public/{slug} в API.
    """

    id: int
    name: str = Field(
        ..., description='Отображаемое имя, показывается гостю на странице бронирования'
    )
    email: EmailStr
    slug: str = Field(
        ...,
        description='Публичный идентификатор в URL: латиница, цифры, дефис;\n2–32 символа, начинается и заканчивается буквой или цифрой.',
        pattern='^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$',
    )
    plan: Plan = Field(
        ..., description='Тариф: free или pro (команда, sync, аналитика, серии)'
    )


class PaymentInfo(BaseModel):
    id: int
    bookingId: int
    amountRub: int
    status: PaymentStatus
    confirmationUrl: str = Field(..., description='URL оплаты (YooKassa или stub)')


class Session(BaseModel):
    """
    Активная сессия
    """

    owner: Owner


class Availability(BaseModel):
    """
    Настройки доступности владельца
    """

    timezone: str = Field(
        ...,
        description='Часовой пояс владельца, IANA-идентификатор (например, Europe/Moscow)',
    )
    bufferMinutes: int = Field(
        ...,
        description='Буфер до и после каждой активной встречи (минуты, кратно 15).\nВ это время новые слоты не предлагаются.',
        ge=0,
        le=120,
    )
    rules: list[AvailabilityRule]
    exceptions: list[AvailabilityException] = Field(
        ..., description='Праздники, отпуска и разовые переопределения дней'
    )
