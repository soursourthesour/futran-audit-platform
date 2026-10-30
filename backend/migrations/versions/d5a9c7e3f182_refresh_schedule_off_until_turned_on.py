"""refresh schedules nobody turned on are switched off

Revision ID: d5a9c7e3f182
Revises: c4e8f2b61d07
Create Date: 2026-10-30 19:00:00

Data correction only. The schedule used to be on by default, so a laptop with an API key started paid refresh runs
that nobody chose. Settings a person saved (updated_by set) are kept as they are; settings made by default when the
screen first opened are switched off. Idempotent.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5a9c7e3f182'
down_revision = 'c4e8f2b61d07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text("update refresh_settings set schedule_enabled = 0 where updated_by is null and schedule_enabled = 1"))


def downgrade() -> None:
    pass  # a data correction
