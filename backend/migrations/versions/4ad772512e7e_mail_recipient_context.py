"""mail recipient context

A queued system email to many people (the employee data notice) keeps each person's own merge values on their
recipient row, so it can be sent after the request (load test BUG-V01, gap G1).

Revision ID: 4ad772512e7e
Revises: 6bc141531b9b
Create Date: 2026-11-25 16:40:00
"""
from alembic import op
import sqlalchemy as sa


revision = '4ad772512e7e'
down_revision = '6bc141531b9b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('mail_recipients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('context', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('mail_recipients', schema=None) as batch_op:
        batch_op.drop_column('context')
