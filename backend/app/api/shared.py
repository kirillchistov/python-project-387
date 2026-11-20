"""Общие для нескольких роутеров хелперы поверх Store.

Порт `slotBusyArgs` из `backend/src/app.js` — используется и публичным
бронированием, и гостевым переносом встречи.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.domain.timeutil import now_utc, to_iso_z
from app.infra.store import Store


def slot_busy_args(store: Store, owner_id: int) -> dict[str, Any]:
    availability = store.get_availability(owner_id)
    active_bookings = store.get_active_bookings(owner_id)
    now = now_utc()
    from_iso = to_iso_z(now)
    to_iso = to_iso_z(now + timedelta(days=16))
    external_busy = store.get_busy_blocks(owner_id, from_iso, to_iso)
    return {
        "availability": availability,
        "active_bookings": active_bookings,
        "external_busy": external_busy,
    }
