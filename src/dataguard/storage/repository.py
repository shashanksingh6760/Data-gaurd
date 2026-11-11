"""
Repository pattern for DataGuard storage operations and idempotency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import desc
from sqlalchemy.orm import Session

from dataguard.models.alert import Alert, AlertCategory, AlertSeverity
from dataguard.models.profile import BaselineMetadata, ColumnProfile, DatasetProfile
from dataguard.models.run import PipelineRunStatus, PipelineRunSummary, ReconciliationResult
from dataguard.storage.database import (
    BaselineVersionRecord,
    ColumnProfileRecord,
    DriftAlertRecord,
    PipelineRunRecord,
    get_session_factory,
)


class StorageRepository:
    """Handles all persistent storage operations, baseline versioning, and idempotency."""

    def __init__(self, database_url: str = "sqlite:///dataguard.db"):
        self.database_url = database_url
        self.session_factory = get_session_factory(database_url)

    def get_session(self) -> Session:
        return self.session_factory()

    # --- Idempotency & Run Management ---

    def find_successful_run_by_fingerprint(self, fingerprint: str) -> Optional[PipelineRunRecord]:
        """Find an existing successful or partial pipeline run with the exact same fingerprint."""
        with self.get_session() as session:
            return (
                session.query(PipelineRunRecord)
                .filter(
                    PipelineRunRecord.file_fingerprint == fingerprint,
                    PipelineRunRecord.status.in_([PipelineRunStatus.SUCCESS.value, PipelineRunStatus.PARTIAL_SUCCESS.value])
                )
                .first()
            )

    def create_run(
        self,
        run_id: str,
        dataset_name: str,
        source_file: str,
        file_fingerprint: str,
        started_at: Optional[datetime] = None,
    ) -> PipelineRunRecord:
        """Create a new pipeline run entry with status RUNNING."""
        started = started_at or datetime.now(timezone.utc)
        record = PipelineRunRecord(
            run_id=run_id,
            dataset_name=dataset_name,
            source_file=source_file,
            file_fingerprint=file_fingerprint,
            started_at=started,
            status=PipelineRunStatus.RUNNING.value,
        )
        with self.get_session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def update_run_status(
        self,
        run_id: str,
        status: PipelineRunStatus,
        input_count: int,
        valid_count: int,
        rejected_count: int,
        output_count: int,
        completed_at: Optional[datetime] = None,
        duration_seconds: float = 0.0,
        failure_reason: Optional[str] = None,
    ) -> None:
        """Update run statistics and terminal status."""
        completed = completed_at or datetime.now(timezone.utc)
        with self.get_session() as session:
            record = session.query(PipelineRunRecord).filter(PipelineRunRecord.run_id == run_id).first()
            if record:
                record.status = status.value
                record.input_count = input_count
                record.valid_count = valid_count
                record.rejected_count = rejected_count
                record.output_count = output_count
                record.completed_at = completed
                record.duration_seconds = duration_seconds
                record.failure_reason = failure_reason
                session.commit()

    def get_run(self, run_id: str) -> Optional[PipelineRunRecord]:
        """Fetch a specific pipeline run by ID."""
        with self.get_session() as session:
            return session.query(PipelineRunRecord).filter(PipelineRunRecord.run_id == run_id).first()

    def list_runs(self, limit: int = 50) -> List[PipelineRunRecord]:
        """List historical runs sorted newest first."""
        with self.get_session() as session:
            return (
                session.query(PipelineRunRecord)
                .order_by(desc(PipelineRunRecord.started_at))
                .limit(limit)
                .all()
            )

    # --- Baseline Versioning ---

    def save_baseline_version(
        self,
        dataset_name: str,
        source_file: str,
        row_count: int,
        profile: DatasetProfile,
    ) -> int:
        """
        Save a new baseline version.
        Atomically bumps version number and deactivates earlier baselines.
        Never silently overwrites.
        """
        with self.get_session() as session:
            latest = (
                session.query(BaselineVersionRecord)
                .filter(BaselineVersionRecord.dataset_name == dataset_name)
                .order_by(desc(BaselineVersionRecord.version))
                .first()
            )
            next_version = (latest.version + 1) if latest else 1

            # Deactivate previous active baselines
            session.query(BaselineVersionRecord).filter(
                BaselineVersionRecord.dataset_name == dataset_name,
                BaselineVersionRecord.is_active == True,
            ).update({"is_active": False})

            new_baseline = BaselineVersionRecord(
                dataset_name=dataset_name,
                version=next_version,
                source_file=source_file,
                row_count=row_count,
                profile_json=json.dumps(profile.to_dict()),
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(new_baseline)
            session.commit()
            return next_version

    def get_latest_baseline(self, dataset_name: str) -> Optional[BaselineMetadata]:
        """Fetch the active/latest baseline for a dataset."""
        with self.get_session() as session:
            record = (
                session.query(BaselineVersionRecord)
                .filter(
                    BaselineVersionRecord.dataset_name == dataset_name,
                    BaselineVersionRecord.is_active == True,
                )
                .order_by(desc(BaselineVersionRecord.version))
                .first()
            )
            if not record:
                # Fallback to absolute highest version if none marked active
                record = (
                    session.query(BaselineVersionRecord)
                    .filter(BaselineVersionRecord.dataset_name == dataset_name)
                    .order_by(desc(BaselineVersionRecord.version))
                    .first()
                )
            if not record:
                return None

            profile_data = json.loads(record.profile_json)
            profile = DatasetProfile(**profile_data)
            return BaselineMetadata(
                version=record.version,
                dataset_name=record.dataset_name,
                created_at=record.created_at,
                row_count=record.row_count,
                source_file=record.source_file,
                is_active=record.is_active,
                profile=profile,
            )

    def get_baseline_version(self, dataset_name: str, version: int) -> Optional[BaselineMetadata]:
        """Fetch a specific baseline version."""
        with self.get_session() as session:
            record = (
                session.query(BaselineVersionRecord)
                .filter(
                    BaselineVersionRecord.dataset_name == dataset_name,
                    BaselineVersionRecord.version == version,
                )
                .first()
            )
            if not record:
                return None
            profile_data = json.loads(record.profile_json)
            profile = DatasetProfile(**profile_data)
            return BaselineMetadata(
                version=record.version,
                dataset_name=record.dataset_name,
                created_at=record.created_at,
                row_count=record.row_count,
                source_file=record.source_file,
                is_active=record.is_active,
                profile=profile,
            )

    # --- Profiles & Alerts ---

    def save_profile(self, run_id: str, profile: DatasetProfile) -> None:
        """Persist dataset column profiles."""
        with self.get_session() as session:
            for col_name, col_prof in profile.columns.items():
                record = ColumnProfileRecord(
                    run_id=run_id,
                    dataset_name=profile.dataset_name,
                    column_name=col_name,
                    inferred_type=col_prof.inferred_type,
                    total_rows=col_prof.total_rows,
                    null_count=col_prof.null_count,
                    null_percentage=col_prof.null_percentage,
                    unique_count=col_prof.unique_count,
                    profile_json=json.dumps(col_prof.model_dump(mode="json")),
                    created_at=datetime.now(timezone.utc),
                )
                session.add(record)
            session.commit()

    def save_alerts(self, alerts: List[Alert]) -> None:
        """Persist generated alerts."""
        if not alerts:
            return
        with self.get_session() as session:
            for alert in alerts:
                record = DriftAlertRecord(
                    alert_id=alert.alert_id,
                    run_id=alert.run_id,
                    dataset=alert.dataset,
                    column_name=alert.column,
                    category=alert.category.value,
                    severity=alert.severity.value,
                    baseline_value=str(alert.baseline_value) if alert.baseline_value is not None else None,
                    current_value=str(alert.current_value) if alert.current_value is not None else None,
                    threshold=str(alert.threshold) if alert.threshold is not None else None,
                    deviation=str(alert.deviation) if alert.deviation is not None else None,
                    explanation=alert.explanation,
                    recommended_action=alert.recommended_action,
                    created_at=alert.timestamp,
                )
                session.add(record)
            session.commit()

    def get_alerts_for_run(self, run_id: str) -> List[Alert]:
        """Fetch all alerts associated with a specific run ID."""
        with self.get_session() as session:
            records = (
                session.query(DriftAlertRecord)
                .filter(DriftAlertRecord.run_id == run_id)
                .all()
            )
            results = []
            for r in records:
                results.append(
                    Alert(
                        alert_id=r.alert_id,
                        run_id=r.run_id,
                        dataset=r.dataset,
                        column=r.column_name,
                        category=AlertCategory(r.category),
                        severity=AlertSeverity(r.severity),
                        baseline_value=r.baseline_value,
                        current_value=r.current_value,
                        threshold=r.threshold,
                        deviation=r.deviation,
                        explanation=r.explanation,
                        recommended_action=r.recommended_action,
                        timestamp=r.created_at,
                    )
                )
            return results
