"""Add persistent job status for Redis-backed background PDF ingestion.

Revision ID: 0002_ingestion_jobs
Revises: 0001_uploaded_documents
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_ingestion_jobs'
down_revision = '0001_uploaded_documents'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ingestion_jobs',
        sa.Column('job_id', sa.String(32), primary_key=True),
        sa.Column('filename', sa.String(180), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('source_id', sa.String(41), nullable=True),
        sa.Column('duplicate', sa.Boolean(), nullable=True),
        sa.Column('error', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name='ck_ingestion_jobs_status'),
    )


def downgrade():
    op.drop_table('ingestion_jobs')
