"""Тесты парсера ICS — сверены с эталонным выводом backend/src/ics.js."""

import pytest
import respx
from httpx import Response

from app.domain.errors import ValidationError
from app.domain.ics import fetch_ics_busy, parse_ics_busy

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1@example.com
DTSTART:20260916T100000Z
DTEND:20260916T110000Z
SUMMARY:Busy 1
END:VEVENT
BEGIN:VEVENT
UID:2@example.com
DTSTART;VALUE=DATE:20260918
DTEND;VALUE=DATE:20260919
SUMMARY:All day
END:VEVENT
BEGIN:VEVENT
UID:3@example.com
DTSTART:bad
DTEND:20260920T120000Z
SUMMARY:Broken
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_busy_matches_js_reference():
    assert parse_ics_busy(SAMPLE_ICS) == [
        {"startsAt": "2026-09-16T10:00:00.000Z", "endsAt": "2026-09-16T11:00:00.000Z"},
        {"startsAt": "2026-09-18T00:00:00.000Z", "endsAt": "2026-09-19T00:00:00.000Z"},
    ]


def test_parse_ics_busy_ignores_events_without_valid_dates():
    assert parse_ics_busy("BEGIN:VEVENT\nDTSTART:garbage\nEND:VEVENT") == []


def test_parse_ics_busy_no_events():
    assert parse_ics_busy("BEGIN:VCALENDAR\nEND:VCALENDAR") == []


@respx.mock
async def test_fetch_ics_busy_parses_response_body():
    respx.get("https://example.com/calendar.ics").mock(
        return_value=Response(200, text=SAMPLE_ICS)
    )
    busy = await fetch_ics_busy("https://example.com/calendar.ics")
    assert len(busy) == 2


@respx.mock
async def test_fetch_ics_busy_raises_validation_error_on_http_failure():
    respx.get("https://example.com/calendar.ics").mock(return_value=Response(404))
    with pytest.raises(ValidationError):
        await fetch_ics_busy("https://example.com/calendar.ics")
