"""opportunity scan: when it was switched on

Revision ID: b7c1d2e3f4a5
Revises: 1972a48d6d27
Create Date: 2026-11-10 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c1d2e3f4a5'
down_revision = '1972a48d6d27'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('opportunity_scan_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('enabled_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('opportunity_scan_settings', schema=None) as batch_op:
        batch_op.drop_column('enabled_at')
