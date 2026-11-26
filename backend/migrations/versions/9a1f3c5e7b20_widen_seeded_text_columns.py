"""Widen two columns whose seeded values are longer than the column: law_versions.effective_text (206 > 200) and
monitor_checks.frequency (37 > 20). SQLite ignores the length; PostgreSQL refuses the insert.

From the 20 Nov hand-off build (shipped to the AWS team), kept under its own revision id so a database stamped with it
is recognised. It is a branch off 717087b4a6c3, joined to the main line by e3c1a9f0b742.

Idempotent and never narrowing: build/v1's 66e4fe67c5ba makes law_versions.effective_text TEXT, and whichever of the
two runs second must not turn it back into a varchar. Each column is widened only when its live type is shorter.

Revision ID: 9a1f3c5e7b20
Revises: 717087b4a6c3
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = '9a1f3c5e7b20'
down_revision = '717087b4a6c3'
branch_labels = None
depends_on = None

WIDEN = [  # (table, column, new length, nullable)
    ('law_versions', 'effective_text', 500, True),
    ('monitor_checks', 'frequency', 100, False),
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
    pass  # widening only; never shorten stored text
