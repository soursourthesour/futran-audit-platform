"""Claude Platform on AWS connection fields: how requests are signed (API key or the server's AWS role), the region and
the workspace ID. Three nullable columns on ai_connections; additive only.

Revision ID: 130c86deb93f
Revises: e3c1a9f0b742
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa


revision = '130c86deb93f'
down_revision = 'e3c1a9f0b742'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_connections', sa.Column('auth_mode', sa.String(length=20), nullable=True))
    op.add_column('ai_connections', sa.Column('aws_region', sa.String(length=40), nullable=True))
    op.add_column('ai_connections', sa.Column('aws_workspace_id', sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_connections', schema=None) as batch_op:
        batch_op.drop_column('aws_workspace_id')
        batch_op.drop_column('aws_region')
        batch_op.drop_column('auth_mode')
