"""law version effective text is unbounded

The EU AI Act phased text in seeds/regmaster.yaml is 206 characters. SQLite ignored the 200 limit; PostgreSQL refused it
and seed-reference stopped (BUG-K08). Widening keeps every row.

On SQLite a batch type change copies the table, and dropping the old law_versions fails the foreign keys that
regulations and proposed changes hold on it. SQLite's own ALTER TABLE (add, drop and rename column, SQLite 3.35 or
later) changes the declared type without touching other tables. The column moves to the end of the table; nothing
depends on column order.

Revision ID: 66e4fe67c5ba
Revises: 58f307875d99
Create Date: 2026-11-25 15:03:31.948051
"""
from alembic import op
import sqlalchemy as sa


revision = '66e4fe67c5ba'
down_revision = '58f307875d99'
branch_labels = None
depends_on = None


def _sqlite_retype(declared: str) -> None:
    op.execute(f"ALTER TABLE law_versions ADD COLUMN effective_text_retyped {declared}")
    op.execute("UPDATE law_versions SET effective_text_retyped = effective_text")
    op.execute("ALTER TABLE law_versions DROP COLUMN effective_text")
    op.execute("ALTER TABLE law_versions RENAME COLUMN effective_text_retyped TO effective_text")


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_retype("TEXT")
        return
    op.alter_column('law_versions', 'effective_text', existing_type=sa.VARCHAR(length=200), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_retype("VARCHAR(200)")
        return
    op.alter_column('law_versions', 'effective_text', existing_type=sa.Text(), type_=sa.VARCHAR(length=200), existing_nullable=True)
