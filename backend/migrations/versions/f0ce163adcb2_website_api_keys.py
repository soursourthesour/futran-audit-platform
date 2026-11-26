"""website api keys (the website library API, /api/public/v1/library)

Additive: one new table. Autogenerate also proposed widening eight existing String columns; those widenings are made on
PostgreSQL by earlier migrations and are left out here on purpose (SQLite ignores String lengths).

Revision ID: f0ce163adcb2
Revises: e3c1a9f0b742
Create Date: 2026-11-26 11:28:21.723047
"""
from alembic import op
import sqlalchemy as sa


revision = 'f0ce163adcb2'
down_revision = 'e3c1a9f0b742'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('website_api_keys',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('allowed_origins', sa.JSON(), nullable=False),
    sa.Column('rate_limit_per_minute', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_by', sa.String(length=36), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('website_api_keys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_website_api_keys_key_hash'), ['key_hash'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('website_api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_website_api_keys_key_hash'))
    op.drop_table('website_api_keys')
