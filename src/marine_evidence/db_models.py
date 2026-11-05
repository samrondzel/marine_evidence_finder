"""PostgreSQL metadata schema for uploaded PDFs.

Deliberately separate from CorpusStore: the application still uses registry.json
until data backfill + integration are verified in a later sprint.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_uploaded_documents_sha256"),
        CheckConstraint("pages > 0", name="ck_uploaded_documents_pages_positive"),
        CheckConstraint("chunks > 0", name="ck_uploaded_documents_chunks_positive"),
    )

    source_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doi: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    pages: Mapped[int] = mapped_column(Integer, nullable=False)
    chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
