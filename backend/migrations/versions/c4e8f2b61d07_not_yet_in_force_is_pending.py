"""law versions whose matrix status says "not yet in force" are pending, not in force

Revision ID: c4e8f2b61d07
Revises: b7d1e3a90c21
Create Date: 2026-10-30 18:45:00

Data correction only. The v1 data move in d39fa4e82416 (already run on laptop data, so left unchanged) read
"not yet in force" as in force, because the text contains "in force". This sets those versions to pending, unless a
person has since approved a status for the law. Idempotent: a second run finds nothing to change.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8f2b61d07'
down_revision = 'b7d1e3a90c21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "update law_versions set status = 'pending' "
        "where status = 'in_force' "
        "and regulation_id in (select id from regulations where lower(coalesce(status_text, '')) like '%not yet in force%') "
        "and regulation_id not in (select regulation_id from proposed_changes where field_path = 'law.status' "
        "                          and status in ('approved', 'edited_approved') and regulation_id is not null)"))


def downgrade() -> None:
    pass  # a data correction; the earlier reading was wrong
