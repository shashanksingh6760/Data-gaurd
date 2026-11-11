"""
SQLAlchemy database setup and schema definitions for DataGuard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"

    run_id = Column(String(64), primary_key=True)
    dataset_name = Column(String(128), nullable=False, index=True)
    source_file = Column(String(512), nullable=False)
    file_fingerprint = Column(String(64), nullable=False, index=True)
    input_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    rejected_count = Column(Integer, default=0)
    output_count = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    status = Column(String(32), nullable=False)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BaselineVersionRecord(Base):
    __tablename__ = "baseline_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_name = Column(String(128), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    source_file = Column(String(512), nullable=False)
    row_count = Column(Integer, nullable=False)
    profile_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ColumnProfileRecord(Base):
    __tablename__ = "column_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("pipeline_runs.run_id"), nullable=False, index=True)
    dataset_name = Column(String(128), nullable=False)
    column_name = Column(String(128), nullable=False)
    inferred_type = Column(String(64), nullable=False)
    total_rows = Column(Integer, nullable=False)
    null_count = Column(Integer, nullable=False)
    null_percentage = Column(Float, nullable=False)
    unique_count = Column(Integer, nullable=False)
    profile_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DriftAlertRecord(Base):
    __tablename__ = "drift_alerts"

    alert_id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("pipeline_runs.run_id"), nullable=False, index=True)
    dataset = Column(String(128), nullable=False)
    column_name = Column(String(128), nullable=True)
    category = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)
    baseline_value = Column(String(256), nullable=True)
    current_value = Column(String(256), nullable=True)
    threshold = Column(String(256), nullable=True)
    deviation = Column(String(256), nullable=True)
    explanation = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def get_db_engine(database_url: str = "sqlite:///dataguard.db", echo: bool = False):
    """Create and return a SQLAlchemy engine."""
    return create_engine(
        database_url,
        echo=echo,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
    )


def init_db(database_url: str = "sqlite:///dataguard.db") -> None:
    """Initialize database tables."""
    engine = get_db_engine(database_url)
    Base.metadata.create_all(engine)


def get_session_factory(database_url: str = "sqlite:///dataguard.db"):
    """Get session factory for the given DB URL."""
    engine = get_db_engine(database_url)
    init_db(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
