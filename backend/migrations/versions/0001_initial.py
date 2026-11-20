"""Начальная схема: owners, sessions, event_types, availability, bookings,
notification_settings.

Порт первого блока `db.exec(...)` из `backend/src/db.js` (JS-версия).

Revision ID: 0001
Revises:
Create Date: 2026-09-15
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE owners (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
          token TEXT PRIMARY KEY,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE event_types (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          description TEXT,
          duration_minutes INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE availability (
          owner_id INTEGER PRIMARY KEY REFERENCES owners(id) ON DELETE CASCADE,
          timezone TEXT NOT NULL,
          rules_json TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bookings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          event_type_id INTEGER NOT NULL REFERENCES event_types(id),
          starts_at TEXT NOT NULL,
          ends_at TEXT NOT NULL,
          guest_name TEXT NOT NULL,
          guest_email TEXT NOT NULL,
          comment TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE notification_settings (
          owner_id INTEGER PRIMARY KEY REFERENCES owners(id) ON DELETE CASCADE,
          email_enabled INTEGER NOT NULL DEFAULT 1,
          telegram_chat_id TEXT,
          reminder_hours_before INTEGER NOT NULL DEFAULT 24
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_bookings_owner_status ON bookings(owner_id, status, starts_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bookings_owner_status")
    op.execute("DROP TABLE IF EXISTS notification_settings")
    op.execute("DROP TABLE IF EXISTS bookings")
    op.execute("DROP TABLE IF EXISTS availability")
    op.execute("DROP TABLE IF EXISTS event_types")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS owners")
