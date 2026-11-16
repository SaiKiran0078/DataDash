from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    datasets: Mapped[list[Dataset]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(64))  # random file name on disk, never the user's
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    schema_json: Mapped[list] = mapped_column(JSON)    # [{name, kind}]
    profile_json: Mapped[dict] = mapped_column(JSON)   # per-column statistics
    notes_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="datasets")
    dashboards: Mapped[list[Dashboard]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    analysis_reports: Mapped[list[AnalysisReport]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    history: Mapped[list[DatasetHistory]] = relationship(cascade="all, delete-orphan")


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    widgets: Mapped[list] = mapped_column(JSON, default=list)   # [{id, title, spec, filters}]
    filters: Mapped[list] = mapped_column(JSON, default=list)   # dashboard-wide filters
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="dashboards")


class AnalysisReport(Base):
    """Persisted analyst narrative linked to a dataset."""
    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    business_question: Mapped[str] = mapped_column(String(1200), default="")
    audience: Mapped[str] = mapped_column(String(300), default="")
    row_grain: Mapped[str] = mapped_column(String(500), default="")
    executive_summary: Mapped[str] = mapped_column(String(12000), default="")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    dataset: Mapped[Dataset] = relationship(back_populates="analysis_reports")


class DatasetHistory(Base):
    """Undo/redo snapshots. Each entry points to an immutable CSV snapshot on disk."""
    __tablename__ = "dataset_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    stack: Mapped[str] = mapped_column(String(8), index=True)  # undo or redo
    stored_name: Mapped[str] = mapped_column(String(64))
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    schema_json: Mapped[list] = mapped_column(JSON)
    profile_json: Mapped[dict] = mapped_column(JSON)
    notes_json: Mapped[list] = mapped_column(JSON, default=list)
    label: Mapped[str] = mapped_column(String(180), default="Transformation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetFile(Base):
    """CSV snapshots stored in the database so they survive ephemeral app restarts."""
    __tablename__ = "dataset_files"

    stored_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    csv_content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
