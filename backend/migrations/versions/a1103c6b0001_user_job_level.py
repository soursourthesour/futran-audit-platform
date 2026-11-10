"""user job level

Revision ID: a1103c6b0001
Revises: 85f55c9289dd
Create Date: 2026-11-10 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1103c6b0001'
down_revision = '85f55c9289dd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('job_level', sa.String(length=30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('job_level')
