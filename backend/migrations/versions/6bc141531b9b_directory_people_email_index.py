"""directory people email index

People are looked up by organisation and lower-case email (ensure_platform_people, find_person). Without an index on
the expression each lookup scanned the organisation's people (load test BUG-V02).

Revision ID: 6bc141531b9b
Revises: bc5522b5d295
Create Date: 2026-11-25 16:20:00
"""
from alembic import op


revision = '6bc141531b9b'
down_revision = 'bc5522b5d295'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE INDEX IF NOT EXISTS ix_directory_people_org_email_ci ON directory_people (organization_id, lower(email))')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_directory_people_org_email_ci')
