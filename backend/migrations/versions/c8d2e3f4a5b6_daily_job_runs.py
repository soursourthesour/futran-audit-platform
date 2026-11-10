"""daily job runs: one claimed run of the daily jobs per date

Revision ID: c8d2e3f4a5b6
Revises: b7c1d2e3f4a5
Create Date: 2026-11-10 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d2e3f4a5b6'
down_revision = 'b7c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('daily_job_runs',
    sa.Column('run_on', sa.Date(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('outcome', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_on', name='uq_daily_job_run_on')
    )


def downgrade() -> None:
    op.drop_table('daily_job_runs')
