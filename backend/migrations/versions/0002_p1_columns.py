"""P1: буфер и исключения availability, manage_token и reminder_sent_at брони.

Порт второго блока `db.js` (ALTER TABLE ... IF NOT EXISTS-эквиваленты).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE availability ADD COLUMN buffer_minutes INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE availability ADD COLUMN exceptions_json TEXT NOT NULL DEFAULT '[]'"
    )
    op.execute("ALTER TABLE bookings ADD COLUMN manage_token TEXT")
    op.execute("ALTER TABLE bookings ADD COLUMN reminder_sent_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP COLUMN reminder_sent_at")
    op.execute("ALTER TABLE bookings DROP COLUMN manage_token")
    op.execute("ALTER TABLE availability DROP COLUMN exceptions_json")
    op.execute("ALTER TABLE availability DROP COLUMN buffer_minutes")
