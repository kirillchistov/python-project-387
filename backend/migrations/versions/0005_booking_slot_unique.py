"""Уникальный частичный индекс против гонки двойного бронирования.

Единственная миграция без прямого аналога в JS-версии: там проверка
свободного слота и вставка брони выполнялись синхронно в одном event loop
(`node:sqlite` — синхронный API), поэтому гонка была невозможна благодаря
рантайму. В асинхронном FastAPI эта гарантия не действует — БД должна
сама отклонять дубли активных бронирований на один и тот же старт.
См. port-to-python-plan.md §2.3.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX idx_bookings_owner_slot_active
          ON bookings(owner_id, starts_at)
          WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bookings_owner_slot_active")
