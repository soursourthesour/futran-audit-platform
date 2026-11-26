"""Widen code columns whose values are longer than the column. SQLite ignores varchar lengths; PostgreSQL (RDS, the AWS
target) refuses the write:
- catalog_changes.status 12 -> 20 ("awaiting_check" is 14)
- refresh_runs.source_set, refresh_settings.source_set 12 -> 20 ("with_secondary" is 14)
- mail_replies.kind 12 -> 20 ("out_of_office" is 13)
- update_digest_runs.status 12 -> 20 ("no_recipients" is 13)
- findings.origin 14 -> 20 ("document_request" is 16)
- opportunities.stage 10 -> 20 ("negotiation" is 11)

From the 20 Nov hand-off build, kept under its own revision id (see 9a1f3c5e7b20). Idempotent and never narrowing: a
column already at least 20 characters, or unbounded, is left as it is.

Revision ID: b7d2e4f6a8c1
Revises: 9a1f3c5e7b20
Create Date: 2026-11-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'b7d2e4f6a8c1'
down_revision = '9a1f3c5e7b20'
branch_labels = None
depends_on = None

WIDEN = [  # (table, column, new length, nullable)
    ('catalog_changes', 'status', 20, False),
    ('refresh_runs', 'source_set', 20, False),
    ('refresh_settings', 'source_set', 20, False),
    ('mail_replies', 'kind', 20, False),
    ('update_digest_runs', 'status', 20, False),
    ('findings', 'origin', 20, False),
    ('opportunities', 'stage', 20, False),
]


def live_type(bind, table: str, column: str):
    return next(c['type'] for c in sa.inspect(bind).get_columns(table) if c['name'] == column)


def wide_enough(type_, length: int) -> bool:
    """Unbounded text (TEXT, or a varchar without a length) or a varchar of at least `length` characters."""
    n = getattr(type_, 'length', None)
    return n is None or n >= length


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        return  # SQLite does not enforce varchar lengths; rebuilding these tables would trip their foreign keys
    for table, column, length, nullable in WIDEN:
        current = live_type(bind, table, column)
        if not wide_enough(current, length):
            op.alter_column(table, column, existing_type=current, type_=sa.String(length=length), existing_nullable=nullable)


def downgrade() -> None:
    pass  # widening only; never shorten stored codes
