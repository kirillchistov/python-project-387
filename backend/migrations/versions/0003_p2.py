"""P2: тариф владельца, цена типа события, платёж и серия брони,
календари/busy-sync, организации, серии, платежи.

Порт третьего блока `db.js` («--- P2 ---»).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE owners ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
    op.execute(
        "ALTER TABLE event_types ADD COLUMN price_rub INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE bookings ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'none'"
    )
    op.execute("ALTER TABLE bookings ADD COLUMN series_id INTEGER")

    op.execute(
        """
        CREATE TABLE calendar_connections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          kind TEXT NOT NULL,
          label TEXT NOT NULL,
          config_json TEXT NOT NULL DEFAULT '{}',
          last_synced_at TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE busy_blocks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          connection_id INTEGER NOT NULL REFERENCES calendar_connections(id) ON DELETE CASCADE,
          starts_at TEXT NOT NULL,
          ends_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE organizations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE organization_members (
          org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          role TEXT NOT NULL,
          PRIMARY KEY (org_id, owner_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE organization_invites (
          token TEXT PRIMARY KEY,
          org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          email TEXT NOT NULL COLLATE NOCASE,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE booking_series (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
          event_type_id INTEGER NOT NULL REFERENCES event_types(id),
          guest_name TEXT NOT NULL,
          guest_email TEXT NOT NULL,
          comment TEXT,
          starts_at TEXT NOT NULL,
          count INTEGER NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
          amount_rub INTEGER NOT NULL,
          status TEXT NOT NULL,
          provider TEXT NOT NULL,
          provider_payment_id TEXT,
          confirmation_url TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_busy_owner_range ON busy_blocks(owner_id, starts_at, ends_at)"
    )
    op.execute("CREATE INDEX idx_payments_booking ON payments(booking_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payments_booking")
    op.execute("DROP INDEX IF EXISTS idx_busy_owner_range")
    op.execute("DROP TABLE IF EXISTS payments")
    op.execute("DROP TABLE IF EXISTS booking_series")
    op.execute("DROP TABLE IF EXISTS organization_invites")
    op.execute("DROP TABLE IF EXISTS organization_members")
    op.execute("DROP TABLE IF EXISTS organizations")
    op.execute("DROP TABLE IF EXISTS busy_blocks")
    op.execute("DROP TABLE IF EXISTS calendar_connections")
    op.execute("ALTER TABLE bookings DROP COLUMN series_id")
    op.execute("ALTER TABLE bookings DROP COLUMN payment_status")
    op.execute("ALTER TABLE event_types DROP COLUMN price_rub")
    op.execute("ALTER TABLE owners DROP COLUMN plan")
