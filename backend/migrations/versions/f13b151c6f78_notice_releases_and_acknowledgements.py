"""notice releases and acknowledgements

Additive: two new tables for the employee AI audit and data notice (versions sent, and who acknowledged each).

Revision ID: f13b151c6f78
Revises: 5d4c31402520
Create Date: 2026-10-27 17:56:30.257114
"""
from alembic import op
import sqlalchemy as sa


revision = 'f13b151c6f78'
down_revision = '5d4c31402520'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('notice_releases',
    sa.Column('engagement_id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('body_md', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=False),
    sa.Column('sent_by', sa.String(length=36), nullable=True),
    sa.Column('recipient_count', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['package_documents.id'], ),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ),
    sa.ForeignKeyConstraint(['sent_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('engagement_id', 'version', name='uq_notice_release_version')
    )
    with op.batch_alter_table('notice_releases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notice_releases_engagement_id'), ['engagement_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notice_releases_organization_id'), ['organization_id'], unique=False)

    op.create_table('notice_acknowledgements',
    sa.Column('release_id', sa.String(length=36), nullable=False),
    sa.Column('engagement_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['notice_releases.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'user_id', name='uq_notice_ack_user')
    )
    with op.batch_alter_table('notice_acknowledgements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notice_acknowledgements_engagement_id'), ['engagement_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notice_acknowledgements_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notice_acknowledgements_release_id'), ['release_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notice_acknowledgements_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('notice_acknowledgements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notice_acknowledgements_user_id'))
        batch_op.drop_index(batch_op.f('ix_notice_acknowledgements_release_id'))
        batch_op.drop_index(batch_op.f('ix_notice_acknowledgements_organization_id'))
        batch_op.drop_index(batch_op.f('ix_notice_acknowledgements_engagement_id'))

    op.drop_table('notice_acknowledgements')
    with op.batch_alter_table('notice_releases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notice_releases_organization_id'))
        batch_op.drop_index(batch_op.f('ix_notice_releases_engagement_id'))

    op.drop_table('notice_releases')
