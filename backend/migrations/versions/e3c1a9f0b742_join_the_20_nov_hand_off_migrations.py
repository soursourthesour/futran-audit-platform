"""Join the 20 Nov hand-off migrations to the main line

The AWS team received a build whose migrations went 717087b4a6c3 -> 9a1f3c5e7b20 -> b7d2e4f6a8c1; build/v1 went
717087b4a6c3 -> 58f307875d99 -> ... -> d6267bab780e. This revision has both as parents, so a database at either head,
or at 717087b4a6c3 (the laptop), upgrades to one head. Every column change on both branches is idempotent and never
narrows a column, so the order alembic runs them in does not change the result.

Revision ID: e3c1a9f0b742
Revises: d6267bab780e, b7d2e4f6a8c1
Create Date: 2026-11-26
"""

revision = 'e3c1a9f0b742'
down_revision = ('d6267bab780e', 'b7d2e4f6a8c1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
