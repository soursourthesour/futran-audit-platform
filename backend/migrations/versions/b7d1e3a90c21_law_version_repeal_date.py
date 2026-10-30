"""law versions keep the repeal date

Revision ID: b7d1e3a90c21
Revises: 4acc52a327dc
Create Date: 2026-10-30 18:30:00

Additive: a nullable law_versions.repealed_on. Versions written by an approved repeal that named a date get it back
from that change (the date was dropped before); other rows stay null, which means "repealed already", as before.
"""
import json

from alembic import op
import sqlalchemy as sa


revision = 'b7d1e3a90c21'
down_revision = '4acc52a327dc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('law_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('repealed_on', sa.Date(), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "select pc.applied_version_id, pc.new_value from proposed_changes pc join law_versions v on v.id = pc.applied_version_id "
        "where pc.field_path = 'repeal' and pc.status in ('approved', 'edited_approved') and v.status = 'repealed' and v.repealed_on is null")).fetchall()
    for vid, raw in rows:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            on = str((value or {}).get("effective_on") or "")[:10]
            if len(on) == 10:
                conn.execute(sa.text("update law_versions set repealed_on = :on where id = :id"), {"on": on, "id": vid})
        except (ValueError, TypeError, AttributeError):
            continue


def downgrade() -> None:
    with op.batch_alter_table('law_versions', schema=None) as batch_op:
        batch_op.drop_column('repealed_on')
