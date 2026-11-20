"""Индекс по manage_token + бэкфилл для брони без токена.

Порт хвоста `db.js`: `CREATE INDEX idx_bookings_manage_token` и цикл
по броням с пустым manage_token (`cryptoRandom()` на каждую строку).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15
"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX idx_bookings_manage_token ON bookings(manage_token)")

    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id FROM bookings WHERE manage_token IS NULL OR manage_token = ''")
    ).fetchall()
    for (booking_id,) in rows:
        bind.execute(
            text("UPDATE bookings SET manage_token = :token WHERE id = :id"),
            {"token": str(uuid.uuid4()), "id": booking_id},
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bookings_manage_token")
