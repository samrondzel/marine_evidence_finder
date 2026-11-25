"""Add durable attempt ownership and retry scheduling.

Revision ID: 0003_ingestion_reliability
Revises: 0002_ingestion_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_ingestion_reliability'
down_revision = '0002_ingestion_jobs'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ingestion_jobs', sa.Column('attempts', sa.Integer(), nullable=False,
                                              server_default='0'))
    op.add_column('ingestion_jobs', sa.Column('rq_job_id', sa.String(90), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True))
    # Existing Sprint 1 jobs have RQ IDs equal to their durable job IDs.
    op.execute('UPDATE ingestion_jobs SET rq_job_id = job_id')
    op.execute("UPDATE ingestion_jobs SET attempts = 1 WHERE started_at IS NOT NULL")
    op.create_index('ix_ingestion_jobs_status', 'ingestion_jobs', ['status'])


def downgrade():
    op.drop_index('ix_ingestion_jobs_status', table_name='ingestion_jobs')
    op.drop_column('ingestion_jobs', 'retry_at')
    op.drop_column('ingestion_jobs', 'rq_job_id')
    op.drop_column('ingestion_jobs', 'attempts')
