"""mail subject ref counter

Thread references (FAP-n) come from a counter instead of a read of every mail thread (load test BUG-V01, gap G8).
A counter row for SQLite; on PostgreSQL also a sequence, so concurrent sends never collide or wait. Both start after
the highest reference already used.

Revision ID: bc5522b5d295
Revises: 58f307875d99
Create Date: 2026-11-25 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'bc5522b5d295'
down_revision = '58f307875d99'
branch_labels = None
depends_on = None

NUMBER_START = 1000


def upgrade() -> None:
    op.create_table('mail_counters',
                    sa.Column('name', sa.String(length=40), nullable=False),
                    sa.Column('value', sa.Integer(), nullable=False),
                    sa.PrimaryKeyConstraint('name'))
    conn = op.get_bind()
    highest = NUMBER_START - 1
    for (ref,) in conn.execute(sa.text("SELECT subject_ref FROM mail_threads")):
        tail = (ref or "").split("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    conn.execute(sa.text("INSERT INTO mail_counters (name, value) VALUES ('subject_ref', :v)"), {"v": highest})
    if conn.dialect.name == "postgresql":
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS mail_subject_ref_seq START WITH {highest + 1}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS mail_subject_ref_seq")
    op.drop_table('mail_counters')
