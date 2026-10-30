"""append-only change log and action traces

Revision ID: bbfa9c36cee5
Revises: e4e6a82e223f
Create Date: 2026-10-30 14:30:00.000000
"""
from alembic import op


revision = 'bbfa9c36cee5'
down_revision = 'e4e6a82e223f'
branch_labels = None
depends_on = None

TABLES = {"change_log": "register change log", "action_traces": "action trace"}


def upgrade() -> None:
    # Database-level guard, as for audit_log and admin_log: no row of these tables is ever updated or deleted.
    bind = op.get_bind()
    for table, label in TABLES.items():
        if bind.dialect.name == "sqlite":
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{label} is append-only'); END")
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{label} is append-only'); END")
        elif bind.dialect.name == "postgresql":
            op.execute(f"CREATE OR REPLACE FUNCTION {table}_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{label} is append-only'; END; $$ LANGUAGE plpgsql")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_change ON {table}")
            op.execute(f"CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_append_only()")


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if bind.dialect.name == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        elif bind.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_change ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_append_only()")
