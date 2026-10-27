"""attestation agents, in-app line items and answer review

Additive only: new nullable columns, two with server defaults, and one new table. Existing answers load unchanged.

Revision ID: 46c4afb7f017
Revises: f13b151c6f78
Create Date: 2026-10-27 18:03:26.524966
"""
from alembic import op
import sqlalchemy as sa


revision = '46c4afb7f017'
down_revision = 'f13b151c6f78'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('attestation_assignments',
    sa.Column('campaign_id', sa.String(length=36), nullable=False),
    sa.Column('engagement_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['attestation_campaigns.id'], ),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'user_id', name='uq_attestation_assignment')
    )
    with op.batch_alter_table('attestation_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attestation_assignments_campaign_id'), ['campaign_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attestation_assignments_engagement_id'), ['engagement_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attestation_assignments_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attestation_assignments_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('ai_tools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=8), server_default='tool', nullable=False))

    with op.batch_alter_table('attestation_campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sent_in_app_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('attestations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('purpose_other', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('user_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('source', sa.String(length=8), server_default='link', nullable=False))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('reviewer_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('edited_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('edited_by', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('removed_by', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('removed_reason', sa.String(length=300), nullable=True))
        batch_op.create_index(batch_op.f('ix_attestations_user_id'), ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_attestations_user_id', 'users', ['user_id'], ['id'])



def downgrade() -> None:
    with op.batch_alter_table('attestations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attestations_user_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_attestations_user_id'))
        batch_op.drop_column('removed_reason')
        batch_op.drop_column('removed_by')
        batch_op.drop_column('edited_by')
        batch_op.drop_column('edited_at')
        batch_op.drop_column('reviewer_note')
        batch_op.drop_column('reviewed_by')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('source')
        batch_op.drop_column('user_id')
        batch_op.drop_column('purpose_other')

    with op.batch_alter_table('attestation_campaigns', schema=None) as batch_op:
        batch_op.drop_column('sent_in_app_at')

    with op.batch_alter_table('ai_tools', schema=None) as batch_op:
        batch_op.drop_column('kind')

    with op.batch_alter_table('attestation_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attestation_assignments_user_id'))
        batch_op.drop_index(batch_op.f('ix_attestation_assignments_organization_id'))
        batch_op.drop_index(batch_op.f('ix_attestation_assignments_engagement_id'))
        batch_op.drop_index(batch_op.f('ix_attestation_assignments_campaign_id'))

    op.drop_table('attestation_assignments')
