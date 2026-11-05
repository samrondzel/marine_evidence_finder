"""Create uploaded document metadata table.

Revision ID: 0001_uploaded_documents
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_uploaded_documents"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "uploaded_documents",
        sa.Column("source_id", sa.String(length=41), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("doi", sa.String(length=255), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sha256", name="uq_uploaded_documents_sha256"),
        sa.CheckConstraint("pages > 0", name="ck_uploaded_documents_pages_positive"),
        sa.CheckConstraint("chunks > 0", name="ck_uploaded_documents_chunks_positive"),
    )


def downgrade():
    # Do not run downgrade on a database holding real document metadata.
    op.drop_table("uploaded_documents")
