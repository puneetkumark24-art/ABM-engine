"""add sequence/journey engine tables (Blueprint Module 08)

Ports decimal_abm's Phase 1 sequencing onto DRIP's ORM. Purely additive — four
new tables, no change to any existing column. Safe to run on a populated DB.

Revision ID: c7d1f0a2b9e4
Revises: b1e4a9c07d32
Create Date: 2026-07-16 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d1f0a2b9e4'
down_revision = 'b1e4a9c07d32'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sequence_definitions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('relationship_type', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'sequence_steps',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('sequence_id', sa.String(length=36), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(), nullable=True),
        sa.Column('wait_days_after_previous', sa.Integer(), nullable=True),
        sa.Column('template_id', sa.String(length=36), nullable=True),
        sa.Column('is_final', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['sequence_id'], ['sequence_definitions.id']),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sequence_id', 'step_number'),
    )
    op.create_index('idx_seqstep_seq', 'sequence_steps', ['sequence_id'])

    op.create_table(
        'sequence_enrollments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('sequence_id', sa.String(length=36), nullable=False),
        sa.Column('person_id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('pause_reason', sa.String(), nullable=True),
        sa.Column('enrolled_at', sa.DateTime(), nullable=True),
        sa.Column('last_step_at', sa.DateTime(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sequence_id'], ['sequence_definitions.id']),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id']),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('person_id', 'sequence_id'),
    )
    op.create_index('idx_enroll_status', 'sequence_enrollments', ['status'])
    op.create_index('idx_enroll_org', 'sequence_enrollments', ['org_id'])
    op.create_index('idx_enroll_person', 'sequence_enrollments', ['person_id'])

    op.create_table(
        'sequence_enrollment_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('enrollment_id', sa.String(length=36), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['enrollment_id'], ['sequence_enrollments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_seqevent_enroll', 'sequence_enrollment_events', ['enrollment_id'])


def downgrade():
    op.drop_index('idx_seqevent_enroll', table_name='sequence_enrollment_events')
    op.drop_table('sequence_enrollment_events')
    op.drop_index('idx_enroll_person', table_name='sequence_enrollments')
    op.drop_index('idx_enroll_org', table_name='sequence_enrollments')
    op.drop_index('idx_enroll_status', table_name='sequence_enrollments')
    op.drop_table('sequence_enrollments')
    op.drop_index('idx_seqstep_seq', table_name='sequence_steps')
    op.drop_table('sequence_steps')
    op.drop_table('sequence_definitions')
