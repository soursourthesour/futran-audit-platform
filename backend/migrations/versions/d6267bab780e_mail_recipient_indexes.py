"""mail recipient indexes

The dispatcher reads a send's due recipients by (send_id, status), and link revocation finds a person's other links
by lower-case email (load test bottleneck 7).

Revision ID: d6267bab780e
Revises: 4ad772512e7e
Create Date: 2026-11-25 17:00:00
"""
from alembic import op


revision = 'd6267bab780e'
down_revision = '4ad772512e7e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_recipients_email_ci ON mail_recipients (lower(email))')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_recipients_send_status ON mail_recipients (send_id, status)')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_mail_recipients_send_status')
    op.execute('DROP INDEX IF EXISTS ix_mail_recipients_email_ci')
