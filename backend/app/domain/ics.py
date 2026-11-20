"""Минимальный разбор ICS: VEVENT с DTSTART / DTEND (UTC или с Z).

Порт `backend/src/ics.js`. Не полный RFC5545 — достаточно для busy-sync MVP,
как и в JS-версии.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx

from app.domain.errors import ValidationError
from app.domain.timeutil import to_iso_z

_DATE_ONLY_RE = re.compile(r"^\d{8}$")
_DATETIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$")


def _unfold_ics(text: str) -> str:
    text = re.sub(r"\r\n[ \t]", "", text)
    return re.sub(r"\n[ \t]", "", text)


def _parse_ics_date(value: str | None) -> datetime | None:
    if not value:
        return None
    # DTSTART:20260727T100000Z или DTSTART;VALUE=DATE:20260727
    raw = value.split(":")[-1] if ":" in value else value

    if _DATE_ONLY_RE.match(raw):
        year, month, day = raw[:4], raw[4:6], raw[6:8]
        try:
            return datetime.fromisoformat(f"{year}-{month}-{day}T00:00:00Z")
        except ValueError:
            return None

    match = _DATETIME_RE.match(raw)
    if not match:
        return None
    year, month, day, hour, minute, second, _zone = match.groups()
    # JS: `m[7] || 'Z'` — часовой пояс всегда трактуется как UTC
    try:
        return datetime.fromisoformat(f"{year}-{month}-{day}T{hour}:{minute}:{second}Z")
    except ValueError:
        return None


def parse_ics_busy(ics_text: str) -> list[dict[str, str]]:
    text = _unfold_ics(ics_text)
    events = text.split("BEGIN:VEVENT")[1:]
    busy: list[dict[str, str]] = []
    for chunk in events:
        body = chunk.split("END:VEVENT")[0]
        dt_start: datetime | None = None
        dt_end: datetime | None = None
        for line in re.split(r"\r?\n", body):
            if line.startswith("DTSTART"):
                dt_start = _parse_ics_date(line)
            if line.startswith("DTEND"):
                dt_end = _parse_ics_date(line)
        if dt_start is not None and dt_end is not None and dt_end > dt_start:
            busy.append({"startsAt": to_iso_z(dt_start), "endsAt": to_iso_z(dt_end)})
    return busy


async def fetch_ics_busy(url: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers={"Accept": "text/calendar, text/plain, */*"})
    if response.is_error:
        raise ValidationError(f"Не удалось загрузить ICS ({response.status_code})")
    return parse_ics_busy(response.text)
