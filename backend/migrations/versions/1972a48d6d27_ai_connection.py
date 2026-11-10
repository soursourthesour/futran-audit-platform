"""ai connection: the platform's AI provider, model and sealed API key (11-03 F1). New table only.

Revision ID: 1972a48d6d27
Revises: a1103c6b0001
Create Date: 2026-11-10 01:08:22.035172
"""
from alembic import op
import sqlalchemy as sa


revision = '1972a48d6d27'
down_revision = 'a1103c6b0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_connections',
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('endpoint', sa.String(length=300), nullable=True),
    sa.Column('deployment', sa.String(length=80), nullable=True),
    sa.Column('key_encrypted', sa.Text(), nullable=False),
    sa.Column('key_ref', sa.String(length=40), nullable=False),
    sa.Column('key_hint', sa.String(length=12), nullable=False),
    sa.Column('last_tested_at', sa.DateTime(), nullable=True),
    sa.Column('last_test_ok', sa.Boolean(), nullable=True),
    sa.Column('last_test_message', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('ai_connections')
