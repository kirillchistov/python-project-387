"""Общие помощники времени: UTC ISO-строки в формате `Date.toISOString()`.

Используется и доменом (slots.py), и слоем данных (store.py) — везде, где
JS-версия хранит/сравнивает время как ISO-строку с миллисекундами и `Z`.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso_z(dt: datetime) -> str:
    """`2026-09-15T12:34:56.789Z` — как `Date.prototype.toISOString()`."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso() -> str:
    return to_iso_z(now_utc())


def parse_iso(value: str) -> datetime:
    """Разбирает ISO-строку (в т.ч. с суффиксом `Z`) в aware-datetime."""
    return datetime.fromisoformat(value)
